"""Work queue for the fetcher.

Two properties carry the whole freshness design:

**Priority.** Strict priority with FIFO inside each level. A click-time
verification must never queue behind a nightly crawl, and a crawl must be
preemptible by definition.

**Deduplication.** This is what makes stale-while-revalidate affordable. A
popular product getting 400 page views in a minute must produce *one* fetch,
not 400. Every job carries a dedupe key with a TTL; pushing a duplicate inside
that window is a no-op. Without this, SWR is a self-inflicted denial of
service on the merchants we depend on.
"""
from __future__ import annotations

import heapq
import itertools
import json
import threading
import time
from dataclasses import dataclass, field

from .ratelimit import Priority

#: How long a dedupe key suppresses duplicates, per priority. Short for
#: user-facing work (the user is entitled to a fresh answer), minutes for
#: revalidation (where the point is collapsing a traffic spike).
DEDUPE_TTL_S: dict[Priority, float] = {
    Priority.CLICK: 5.0,
    Priority.HOVER: 15.0,
    Priority.SWR: 300.0,
    Priority.HOT: 300.0,
    Priority.WARM: 900.0,
    Priority.COLD: 3600.0,
}


@dataclass(slots=True)
class FetchJob:
    """One unit of fetch work."""

    merchant_slug: str
    url: str
    #: 'catalog_parse' | 'stock_probe' | 'discovery' -- matches ingest_run.kind
    kind: str = "stock_probe"
    priority: Priority = Priority.COLD

    #: POST payload, for endpoints that refuse GET (sport-m GetVelicini).
    method: str = "GET"
    body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)

    #: What this fetch is for, so the loader can attribute the result.
    offer_variant_id: int | None = None
    offer_id: int | None = None

    #: Category implied by WHERE discovery found this product -- a footwear
    #: facet, a sneakers category page. Used by the loader only when the
    #: product's own title names no category.
    category_hint: str | None = None

    attempt: int = 0
    enqueued_at: float = field(default_factory=time.time)

    @property
    def domain(self) -> str:
        """Rate-limit key. Always the merchant, never the hostname.

        sizeer.com.mk and sport-m.com.mk share a host IP; keying on the
        merchant keeps their budgets separate and intelligible, and keying on
        the hostname would let one starve the other.
        """
        return self.merchant_slug

    def dedupe_key(self) -> str:
        parts = [self.merchant_slug, self.kind, self.method, self.url]
        if self.body:
            parts.append(self.body.decode("utf-8", "replace"))
        return "|".join(parts)

    def to_json(self) -> str:
        return json.dumps({
            "merchant_slug": self.merchant_slug, "url": self.url,
            "kind": self.kind, "priority": int(self.priority),
            "method": self.method,
            "body": self.body.decode("utf-8", "replace") if self.body else None,
            "headers": self.headers, "offer_variant_id": self.offer_variant_id,
            "offer_id": self.offer_id, "attempt": self.attempt,
            "category_hint": self.category_hint,
            "enqueued_at": self.enqueued_at,
        })

    @classmethod
    def from_json(cls, raw: str) -> FetchJob:
        data = json.loads(raw)
        body = data.pop("body", None)
        priority = Priority(data.pop("priority", int(Priority.COLD)))
        return cls(priority=priority,
                   body=body.encode() if body else None, **data)


class MemoryFetchQueue:
    """Strict-priority queue with FIFO within a priority, plus TTL dedupe.

    Thread-safe. Single-process; swap for a Redis implementation when the
    fetcher scales past one worker.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._heap: list[tuple[int, int, FetchJob]] = []
        self._counter = itertools.count()   # FIFO tiebreak within a priority
        #: dedupe key -> (expiry, priority it was admitted at)
        self._seen: dict[str, tuple[float, Priority]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _expire(self) -> None:
        now = self._clock()
        if len(self._seen) > 64:
            self._seen = {k: v for k, v in self._seen.items() if v[0] > now}

    def push(self, job: FetchJob, *, dedupe: bool = True) -> bool:
        """Enqueue ``job``. Returns False when suppressed as a duplicate.

        A higher-priority arrival is **not** suppressed by a lower-priority
        duplicate: someone clicking through deserves a fresh check even if a
        cold crawl of the same URL was queued an hour ago. The escalation is
        one-way, so a cold crawl cannot jump a live click's dedupe window.
        """
        with self._lock:
            self._expire()
            now = self._clock()
            key = job.dedupe_key()
            if dedupe:
                entry = self._seen.get(key)
                if entry is not None and entry[0] > now:
                    # Only a strictly higher priority may break through.
                    if job.priority >= entry[1]:
                        return False
                self._seen[key] = (now + DEDUPE_TTL_S[job.priority], job.priority)
            heapq.heappush(
                self._heap, (int(job.priority), next(self._counter), job))
            return True

    def pop(self) -> FetchJob | None:
        with self._lock:
            if not self._heap:
                return None
            return heapq.heappop(self._heap)[2]

    def requeue(self, job: FetchJob) -> None:
        """Put a job back after a retryable failure, without dedupe."""
        job.attempt += 1
        with self._lock:
            heapq.heappush(
                self._heap, (int(job.priority), next(self._counter), job))

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)

    def depth_by_priority(self) -> dict[Priority, int]:
        with self._lock:
            out: dict[Priority, int] = {}
            for priority, _, _ in self._heap:
                key = Priority(priority)
                out[key] = out.get(key, 0) + 1
            return out

    def clear(self) -> None:
        with self._lock:
            self._heap.clear()
            self._seen.clear()


class RedisFetchQueue:
    """Cross-process queue: one ZSET, score encodes priority then arrival.

    ``score = priority * 1e12 + enqueued_at`` gives strict priority with FIFO
    inside a level, in a single atomic pop.
    """

    def __init__(self, client, namespace: str = "mkagg:q") -> None:
        self.client = client
        self.key = f"{namespace}:jobs"
        self.dedupe_prefix = f"{namespace}:seen"

    @staticmethod
    def _score(job: FetchJob) -> float:
        return int(job.priority) * 1e12 + job.enqueued_at

    def push(self, job: FetchJob, *, dedupe: bool = True) -> bool:
        if dedupe:
            ttl = int(DEDUPE_TTL_S[job.priority])
            dkey = f"{self.dedupe_prefix}:{job.priority}:{job.dedupe_key()}"
            if not self.client.set(dkey, "1", nx=True, ex=max(ttl, 1)):
                return False
        self.client.zadd(self.key, {job.to_json(): self._score(job)})
        return True

    def pop(self) -> FetchJob | None:
        popped = self.client.zpopmin(self.key, 1)
        if not popped:
            return None
        raw = popped[0][0]
        if isinstance(raw, bytes):
            raw = raw.decode()
        return FetchJob.from_json(raw)

    def requeue(self, job: FetchJob) -> None:
        job.attempt += 1
        self.client.zadd(self.key, {job.to_json(): self._score(job)})

    def __len__(self) -> int:
        return int(self.client.zcard(self.key))
