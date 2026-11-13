"""The fetcher: the only module in the project that touches the network.

Everything downstream is pure, which is what makes the parsers testable. This
module concentrates all the messy parts in one place: politeness, robots,
conditional requests, retries, failure isolation and the raw archive.

Design commitments, in order of importance:

**Fail open.** A fetch that cannot complete returns a result saying so. It
never raises into the caller and never blocks past its priority's budget. At
click time a missed verification must cost an unverified redirect, not a lost
click.

**Conditional requests always.** Storing ``ETag``/``Last-Modified`` and
replaying them turns the overwhelming majority of probes into 304s that cost
both sides essentially nothing. On a 50k catalogue where ~2% of prices move
per day, this is the difference between a heavy crawler and an invisible one.

**Identify honestly.** A named, contactable bot that sends a shop paying
customers gets an email when something is wrong. An anonymous one gets
blocked. The default User-Agent carries a URL and an address on purpose.
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from .queue import FetchJob
from .ratelimit import (BUDGET_MS, BreakerWait, CircuitBreaker,
                        MemoryRateLimiter, Priority)
from .rawstore import NullRawStore

DEFAULT_USER_AGENT = (
    "MKPriceCompareBot/0.1 (+https://yoursite.mk/bot; bot@yoursite.mk)")

#: Statuses worth a second attempt. 429 and 503 mean "slow down", not "stop",
#: so they are retried with backoff and also trip the breaker.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 522, 524})

#: Statuses that trip the circuit breaker.
BREAKER_STATUS = frozenset({403, 429, 500, 502, 503, 504, 522, 524})


# -----------------------------------------------------------------------------
# Results
# -----------------------------------------------------------------------------

@dataclass(slots=True)
class FetchResult:
    job: FetchJob
    status: int = 0
    body: bytes = b""
    content_type: str = ""
    etag: str | None = None
    last_modified: str | None = None
    latency_ms: float = 0.0
    snapshot_key: str | None = None
    error: str | None = None
    #: Set when the fetch never went out: 'rate_limited', 'circuit_open',
    #: 'robots_disallowed'. Distinguishing these from HTTP failures matters --
    #: a skip is our choice, an error is the merchant's.
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def not_modified(self) -> bool:
        """304: the resource is byte-identical to what we already hold.

        The scheduler treats this as a confirmed "unchanged" observation, so
        it still backs the TTL off -- a cheap 304 is as informative as an
        expensive 200 that happens to match.
        """
        return self.status == 304

    @property
    def should_retry(self) -> bool:
        if self.skipped or self.ok or self.not_modified:
            return False
        return self.status in RETRYABLE_STATUS or self.error is not None


# -----------------------------------------------------------------------------
# Transport
# -----------------------------------------------------------------------------

class Transport(Protocol):
    """Minimal HTTP surface, so tests need no network and no httpx."""

    def request(self, method: str, url: str, *, headers: dict[str, str],
                body: bytes | None, timeout_s: float
                ) -> tuple[int, dict[str, str], bytes]: ...


class HttpxTransport:
    """Production transport. HTTP/2 keeps the probe loop cheap."""

    def __init__(self, *, http2: bool = True, verify: bool = True) -> None:
        import httpx  # imported lazily so stdlib-only test runs still work

        self._client = httpx.Client(
            http2=http2, verify=verify, follow_redirects=True,
            limits=httpx.Limits(max_connections=16,
                                max_keepalive_connections=8))

    def request(self, method, url, *, headers, body, timeout_s):
        response = self._client.request(
            method, url, headers=headers, content=body, timeout=timeout_s)
        return (response.status_code,
                {k.lower(): v for k, v in response.headers.items()},
                response.content)

    def close(self) -> None:
        self._client.close()


# -----------------------------------------------------------------------------
# Conditional-request validators
# -----------------------------------------------------------------------------

class MemoryValidatorStore:
    """Remembers ETag / Last-Modified per URL.

    In production this belongs in Redis or on ``offer_variant``, so validators
    survive a restart; losing them only costs one full fetch per URL.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[str | None, str | None]] = {}

    def get(self, url: str) -> tuple[str | None, str | None]:
        return self._data.get(url, (None, None))

    def put(self, url: str, etag: str | None, last_modified: str | None) -> None:
        if etag or last_modified:
            self._data[url] = (etag, last_modified)


# -----------------------------------------------------------------------------
# robots.txt
# -----------------------------------------------------------------------------

@dataclass
class _RobotsEntry:
    parser: urllib.robotparser.RobotFileParser | None
    fetched_at: float
    allow_all: bool


class RobotsCache:
    """robots.txt per origin, cached for a day.

    Following RFC 9309: a 4xx means no restrictions, while a 5xx or a timeout
    means treat the site as disallowed *for now*. Four of the seven target
    stores return 404 here, so the permissive branch is the common one.

    Honouring robots is not only correct, it is the evidence of good faith
    that makes the later "give us a feed" conversation possible.
    """

    TTL_S = 86_400

    def __init__(self, transport: Transport, user_agent: str = DEFAULT_USER_AGENT,
                 clock=time.monotonic) -> None:
        self.transport = transport
        self.user_agent = user_agent
        self._cache: dict[str, _RobotsEntry] = {}
        self._clock = clock

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def _load(self, origin: str) -> _RobotsEntry:
        try:
            status, _, body = self.transport.request(
                "GET", f"{origin}/robots.txt",
                headers={"User-Agent": self.user_agent}, body=None,
                timeout_s=10.0)
        except Exception:
            return _RobotsEntry(None, self._clock(), allow_all=False)

        if 400 <= status < 500:
            return _RobotsEntry(None, self._clock(), allow_all=True)
        if status >= 500:
            return _RobotsEntry(None, self._clock(), allow_all=False)

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.decode("utf-8", "replace").splitlines())
        return _RobotsEntry(parser, self._clock(), allow_all=False)

    def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        entry = self._cache.get(origin)
        if entry is None or self._clock() - entry.fetched_at > self.TTL_S:
            entry = self._load(origin)
            self._cache[origin] = entry
        if entry.allow_all:
            return True
        if entry.parser is None:
            return False
        return entry.parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        entry = self._cache.get(self._origin(url))
        if entry is None or entry.parser is None:
            return None
        try:
            delay = entry.parser.crawl_delay(self.user_agent)
        except Exception:
            return None
        return float(delay) if delay else None


# -----------------------------------------------------------------------------
# Fetcher
# -----------------------------------------------------------------------------

@dataclass
class FetcherConfig:
    user_agent: str = DEFAULT_USER_AGENT
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    respect_robots: bool = True
    accept_language: str = "mk,en;q=0.8"


class Fetcher:
    """Politeness, conditional requests, archiving and failure isolation."""

    def __init__(self, transport: Transport, *,
                 limiter=None, breaker: CircuitBreaker | None = None,
                 raw_store=None, validators: MemoryValidatorStore | None = None,
                 robots: RobotsCache | None = None,
                 config: FetcherConfig | None = None,
                 clock=time.monotonic, sleep=time.sleep) -> None:
        self.transport = transport
        self.config = config or FetcherConfig()
        # As in MemoryRateLimiter: `sleep` must advance what `clock` reads.
        self._sleep = sleep
        self.limiter = limiter or MemoryRateLimiter(rps=1.0, reserve=1.0)
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.raw_store = raw_store or NullRawStore()
        self.validators = validators or MemoryValidatorStore()
        self.robots = robots if robots is not None else (
            RobotsCache(transport, self.config.user_agent, clock=clock)
            if self.config.respect_robots else None)
        self._clock = clock
        self.stats: dict[str, int] = {}

    def _bump(self, name: str) -> None:
        self.stats[name] = self.stats.get(name, 0) + 1

    def _headers(self, job: FetchJob) -> dict[str, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept-Language": self.config.accept_language,
            "Accept-Encoding": "gzip",
        }
        # Conditional request: a 304 costs the merchant almost nothing.
        etag, last_modified = self.validators.get(job.url)
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        headers.update(job.headers)
        return headers

    def fetch(self, job: FetchJob) -> FetchResult:
        """Fetch one job. Never raises; never exceeds the priority budget."""
        budget_s = BUDGET_MS[job.priority] / 1000.0
        deadline = self._clock() + budget_s

        if not self.breaker.allow(job.domain, job.priority):
            self._bump("circuit_open")
            return FetchResult(job=job, skipped="circuit_open")

        if self.robots is not None and not self.robots.allowed(job.url):
            self._bump("robots_disallowed")
            return FetchResult(job=job, skipped="robots_disallowed")

        remaining_ms = max(0, int((deadline - self._clock()) * 1000))
        if not self.limiter.acquire(job.domain, job.priority, remaining_ms):
            self._bump("rate_limited")
            return FetchResult(job=job, skipped="rate_limited")

        result = self._attempt(job, deadline)

        # Retry only while budget remains. User-facing priorities have budgets
        # too small for this to fire, which is intentional.
        attempts = 1
        while (result.should_retry and attempts < self.config.max_attempts
               and self._clock() < deadline):
            backoff = self.config.backoff_base_s * (2 ** (attempts - 1))
            if self._clock() + backoff >= deadline:
                break
            self._sleep(backoff)
            remaining_ms = max(0, int((deadline - self._clock()) * 1000))
            if not self.limiter.acquire(job.domain, job.priority, remaining_ms):
                break
            attempts += 1
            self._bump("retry")
            result = self._attempt(job, deadline)

        if result.ok or result.not_modified:
            self.breaker.record_success(job.domain)
        elif result.status in BREAKER_STATUS or result.error:
            self.breaker.record_failure(job.domain)
        return result

    def _attempt(self, job: FetchJob, deadline: float) -> FetchResult:
        timeout_s = max(0.1, deadline - self._clock())
        started = self._clock()
        try:
            status, headers, body = self.transport.request(
                job.method, job.url, headers=self._headers(job),
                body=job.body, timeout_s=timeout_s)
        except Exception as exc:
            self._bump("error")
            return FetchResult(
                job=job, error=f"{type(exc).__name__}: {exc}",
                latency_ms=(self._clock() - started) * 1000)

        latency_ms = (self._clock() - started) * 1000
        content_type = headers.get("content-type", "")
        etag = headers.get("etag")
        last_modified = headers.get("last-modified")

        result = FetchResult(
            job=job, status=status, body=body, content_type=content_type,
            etag=etag, last_modified=last_modified, latency_ms=latency_ms)

        if status == 304:
            self._bump("not_modified")
            return result

        if result.ok:
            self._bump("ok")
            self.validators.put(job.url, etag, last_modified)
            # Archive before parsing, so a parser bug is always recoverable.
            try:
                result.snapshot_key = self.raw_store.put(
                    job.merchant_slug, job.url, body, content_type,
                    status=status, kind=job.kind,
                    priority=int(job.priority), latency_ms=round(latency_ms, 1))
            except Exception as exc:          # archiving must never fail a fetch
                result.error = f"archive_failed: {type(exc).__name__}: {exc}"
                self._bump("archive_failed")
        else:
            self._bump(f"http_{status}")
        return result

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()


# -----------------------------------------------------------------------------
# Draining patiently
# -----------------------------------------------------------------------------

#: How many times one job may be re-fetched after an open circuit. Bounded so
#: a breaker that reopens on every attempt cannot spin on a single job.
MAX_BREAKER_REFETCHES = 4


def fetch_patiently(fetcher: "Fetcher", job: FetchJob,
                    waiter: BreakerWait | None = None) -> FetchResult:
    """Fetch ``job``, waiting out an open circuit instead of abandoning it.

    The fail-open contract belongs to :meth:`Fetcher.fetch` and stays there:
    it must never block a waiting user on a merchant that is misbehaving. But
    a background drain has no user, and for it an immediate ``circuit_open``
    is not an answer about the job -- it is an answer about the domain, and
    the job is still owed a fetch.

    With no ``waiter`` this is exactly ``fetcher.fetch(job)``, so callers that
    genuinely must not wait keep today's behaviour by passing nothing.
    """
    result = fetcher.fetch(job)
    for _ in range(MAX_BREAKER_REFETCHES):
        if result.skipped != "circuit_open":
            return result
        if waiter is None or not waiter.wait(fetcher.breaker, job.domain,
                                             job.priority):
            return result
        result = fetcher.fetch(job)
    return result


# -----------------------------------------------------------------------------
# Test double
# -----------------------------------------------------------------------------

@dataclass
class StubTransport:
    """Scripted transport for tests.

    ``routes`` maps a URL substring to ``(status, headers, body)`` or to a
    callable taking the request. ``calls`` records every request made, which
    is how the tests assert on politeness and conditional headers.
    """

    routes: dict = field(default_factory=dict)
    default: tuple = (404, {}, b"not found")
    calls: list[dict] = field(default_factory=list)

    def request(self, method, url, *, headers, body, timeout_s):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "body": body, "timeout_s": timeout_s})
        for fragment, response in self.routes.items():
            if fragment in url:
                if callable(response):
                    return response(method, url, headers, body)
                return response
        return self.default
