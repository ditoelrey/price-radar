"""Per-domain politeness budget and failure isolation.

The rate limiter is the single most important control in the fetcher, because
*every* kind of work shares one budget per merchant domain: the nightly
catalogue crawl, the 15-minute stock probes, the page-view revalidations and
the click-time verification all draw from the same bucket.

The measured volume is small -- roughly 25k requests per store per day, about
0.3 req/s averaged -- so the limiter exists to shape *when* requests happen,
not to stay under some heroic ceiling. Its real job is the reservation:
background work must never be able to starve a user who is standing at the
redirect waiting to be sent to a shop.

Reservation rule
----------------
High-priority work (click-time, hover warm-up) may draw the bucket down to
empty. Background work (SWR, hot/warm/cold probes) may only take a token if
doing so leaves at least ``reserve`` tokens behind. So a cold crawl saturating
a domain still cannot consume the headroom a click needs; the crawl pauses
instead. Freshness degrades, the user-facing path does not.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol


class Priority(IntEnum):
    """Lower value wins. Mirrors the queue's priority ladder."""

    CLICK = 0    # user is waiting at /out/{id}; never preempted
    HOVER = 1    # pre-click warm-up
    SWR = 2      # page-view revalidation
    HOT = 3      # 15-30 min probe tier
    WARM = 4     # 2-4 h probe tier
    COLD = 5     # nightly full crawl; fully preemptible

    @property
    def is_user_facing(self) -> bool:
        """Whether this priority may spend the reserved headroom."""
        return self <= Priority.HOVER


#: Hard wall-clock budget per priority. The click budget is the one that
#: matters: past it the redirect goes out unverified rather than making the
#: user wait. Fail open, always.
BUDGET_MS: dict[Priority, int] = {
    Priority.CLICK: 1200,
    Priority.HOVER: 3000,
    Priority.SWR: 10_000,
    Priority.HOT: 20_000,
    Priority.WARM: 30_000,
    Priority.COLD: 30_000,
}


class RateLimiter(Protocol):
    def acquire(self, key: str, priority: Priority,
                timeout_ms: int | None = ...) -> bool: ...
    def tokens(self, key: str) -> float: ...


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class MemoryRateLimiter:
    """Token bucket in process memory.

    Correct for a single worker and for tests. Use :class:`RedisRateLimiter`
    once more than one process fetches, or the per-domain budget is silently
    multiplied by the worker count.
    """

    def __init__(self, rps: float = 1.0, capacity: float | None = None,
                 reserve: float = 1.0, clock=time.monotonic,
                 sleep=time.sleep) -> None:
        if rps <= 0:
            raise ValueError("rps must be positive")
        self.rps = float(rps)
        self.capacity = float(capacity if capacity is not None else max(rps, 2.0))
        # Headroom only user-facing work may spend.
        self.reserve = min(float(reserve), self.capacity)
        self._clock = clock
        # `sleep` MUST advance whatever `clock` reads. Injecting a clock but
        # sleeping on the real one makes the wait loop measure a time that
        # never moves, and acquire() spins forever.
        self._sleep = sleep
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    # -- internals ---------------------------------------------------------

    def _refill(self, key: str) -> _Bucket:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, last_refill=now)
            self._buckets[key] = bucket
            return bucket
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rps)
            bucket.last_refill = now
        return bucket

    def _try_take(self, key: str, priority: Priority) -> bool:
        bucket = self._refill(key)
        floor = 0.0 if priority.is_user_facing else self.reserve
        if bucket.tokens - 1.0 >= floor - 1e-9:
            bucket.tokens -= 1.0
            return True
        return False

    # -- public ------------------------------------------------------------

    def acquire(self, key: str, priority: Priority = Priority.COLD,
                timeout_ms: int | None = None) -> bool:
        """Take one token for ``key``, waiting up to ``timeout_ms``.

        ``timeout_ms`` defaults to the priority's budget. Returns False when
        the budget expires without a token, which callers must treat as
        "skip this fetch", never as "retry immediately".
        """
        budget = BUDGET_MS[priority] if timeout_ms is None else timeout_ms
        deadline = self._clock() + budget / 1000.0
        while True:
            with self._lock:
                if self._try_take(key, priority):
                    return True
                bucket = self._buckets[key]
                floor = 0.0 if priority.is_user_facing else self.reserve
                deficit = (floor + 1.0) - bucket.tokens
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            self._sleep(min(max(deficit / self.rps, 0.005), remaining))

    def tokens(self, key: str) -> float:
        with self._lock:
            return self._refill(key).tokens


# Atomic token bucket. Returning the deficit lets the caller sleep exactly
# long enough instead of spinning.
_REDIS_LUA = """
local tokens_key = KEYS[1]
local ts_key     = KEYS[2]
local rate       = tonumber(ARGV[1])
local capacity   = tonumber(ARGV[2])
local now        = tonumber(ARGV[3])
local floor      = tonumber(ARGV[4])

local tokens = tonumber(redis.call('get', tokens_key))
local last   = tonumber(redis.call('get', ts_key))
if tokens == nil then tokens = capacity; last = now end
if last == nil then last = now end

local elapsed = math.max(0, now - last)
tokens = math.min(capacity, tokens + elapsed * rate)

local granted = 0
if tokens - 1.0 >= floor then
    tokens = tokens - 1.0
    granted = 1
end

-- Expire idle buckets rather than leaking a key per domain forever.
local ttl = math.ceil(capacity / rate) + 60
redis.call('set', tokens_key, tokens, 'EX', ttl)
redis.call('set', ts_key, now, 'EX', ttl)
return {granted, tostring(tokens)}
"""


class RedisRateLimiter:
    """Token bucket shared across worker processes.

    Same semantics as :class:`MemoryRateLimiter`, including the reservation.
    """

    def __init__(self, client, rps: float = 1.0, capacity: float | None = None,
                 reserve: float = 1.0, namespace: str = "mkagg:rl") -> None:
        self.client = client
        self.rps = float(rps)
        self.capacity = float(capacity if capacity is not None else max(rps, 2.0))
        self.reserve = min(float(reserve), self.capacity)
        self.namespace = namespace
        self._script = client.register_script(_REDIS_LUA)

    def _keys(self, key: str) -> tuple[str, str]:
        return f"{self.namespace}:{key}:t", f"{self.namespace}:{key}:ts"

    def acquire(self, key: str, priority: Priority = Priority.COLD,
                timeout_ms: int | None = None) -> bool:
        budget = BUDGET_MS[priority] if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + budget / 1000.0
        floor = 0.0 if priority.is_user_facing else self.reserve
        tokens_key, ts_key = self._keys(key)
        while True:
            granted, tokens = self._script(
                keys=[tokens_key, ts_key],
                args=[self.rps, self.capacity, time.time(), floor])
            if int(granted) == 1:
                return True
            deficit = (floor + 1.0) - float(tokens)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(max(deficit / self.rps, 0.01), remaining))

    def tokens(self, key: str) -> float:
        tokens_key, _ = self._keys(key)
        raw = self.client.get(tokens_key)
        return self.capacity if raw is None else float(raw)


# -----------------------------------------------------------------------------
# Circuit breaker
# -----------------------------------------------------------------------------

class BreakerState(str):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerEntry:
    failures: int = 0
    successes: int = 0
    opened_at: float | None = None
    cooldown_s: float = 0.0
    consecutive_opens: int = 0


@dataclass
class CircuitBreaker:
    """Per-domain failure isolation with exponential cooldown.

    When a merchant starts erroring or crawling, hammering it is both rude and
    pointless. The breaker opens, background work for that domain stops, and
    the merchant's data should be surfaced as "may be outdated" rather than
    silently served as current -- that is the honest-UI half of the contract.

    ``allow`` is deliberately permissive for user-facing priorities while
    half-open, so a single click can probe recovery.
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    base_cooldown_s: float = 30.0
    max_cooldown_s: float = 1800.0
    clock: object = field(default=time.monotonic)
    _entries: dict[str, _BreakerEntry] = field(default_factory=dict)

    def _entry(self, key: str) -> _BreakerEntry:
        return self._entries.setdefault(key, _BreakerEntry())

    def state(self, key: str) -> str:
        entry = self._entry(key)
        if entry.opened_at is None:
            return BreakerState.CLOSED
        if self.clock() - entry.opened_at >= entry.cooldown_s:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allow(self, key: str, priority: Priority = Priority.COLD) -> bool:
        state = self.state(key)
        if state == BreakerState.CLOSED:
            return True
        if state == BreakerState.HALF_OPEN:
            return True
        # Open: only let a waiting user through, and only to test recovery.
        return priority == Priority.CLICK

    def record_success(self, key: str) -> None:
        entry = self._entry(key)
        entry.failures = 0
        if entry.opened_at is not None:
            entry.successes += 1
            if entry.successes >= self.success_threshold:
                entry.opened_at = None
                entry.successes = 0
                entry.consecutive_opens = 0

    def record_failure(self, key: str) -> None:
        entry = self._entry(key)
        entry.successes = 0
        entry.failures += 1
        if entry.failures >= self.failure_threshold or entry.opened_at is not None:
            entry.consecutive_opens += 1
            entry.cooldown_s = min(
                self.base_cooldown_s * (2 ** (entry.consecutive_opens - 1)),
                self.max_cooldown_s)
            entry.opened_at = self.clock()
            entry.failures = 0

    def is_degraded(self, key: str) -> bool:
        """True when this merchant's data should be flagged as possibly stale."""
        return self.state(key) != BreakerState.CLOSED
