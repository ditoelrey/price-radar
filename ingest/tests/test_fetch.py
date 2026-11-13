"""Fetch-layer tests. No network: every HTTP call goes through StubTransport.

The properties under test are the ones the freshness design actually rests on,
not incidental behaviour:

* background work can never starve a click;
* a traffic spike produces one fetch, not hundreds;
* nothing exceeds its priority's budget, and nothing raises into the caller;
* a 304 is a real observation;
* price history is written only when a value moved.
"""
from __future__ import annotations

import time

import pytest

from mkagg.fetch import (BUDGET_MS, MAX_BREAKER_REFETCHES, BreakerWait,
                         CircuitBreaker, FetchJob, Fetcher, FetcherConfig,
                         LocalRawStore, MemoryFetchQueue, MemoryRateLimiter,
                         Priority, RobotsCache, StubTransport, fetch_patiently,
                         next_ttl, snapshot_key)
from mkagg.fetch.ratelimit import BreakerState


class FakeClock:
    """Manual clock, so rate-limit and breaker tests need no real sleeping.

    ``sleep`` advances this same clock, which is the contract the limiter and
    fetcher require: a component given an injected clock must also be given a
    sleep that moves it, or its wait loops measure a time that never changes.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.slept = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += seconds


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestMemoryRateLimiter:
    def test_capacity_then_refill(self):
        clock = FakeClock()
        limiter = MemoryRateLimiter(rps=1.0, capacity=3, reserve=0, clock=clock, sleep=clock.sleep)
        assert [limiter.acquire("s", Priority.COLD, 0) for _ in range(3)] == \
            [True, True, True]
        assert limiter.acquire("s", Priority.COLD, 0) is False
        clock.advance(2.0)
        assert limiter.acquire("s", Priority.COLD, 0) is True

    def test_buckets_are_per_domain(self):
        clock = FakeClock()
        limiter = MemoryRateLimiter(rps=1.0, capacity=1, reserve=0, clock=clock, sleep=clock.sleep)
        assert limiter.acquire("sportm", Priority.COLD, 0) is True
        # sizeer shares a host IP with sport-m but must have its own budget.
        assert limiter.acquire("sizeer", Priority.COLD, 0) is True

    def test_background_cannot_starve_a_click(self):
        """The reservation, which is the whole point of the limiter.

        A cold crawl saturating a domain must still leave the headroom a
        waiting user needs.
        """
        clock = FakeClock()
        limiter = MemoryRateLimiter(rps=1.0, capacity=3, reserve=1.0, clock=clock, sleep=clock.sleep)

        drained = 0
        while limiter.acquire("dsport", Priority.COLD, 0):
            drained += 1
        assert drained == 2, "cold work should stop one token short of empty"
        assert limiter.acquire("dsport", Priority.COLD, 0) is False

        # The reserved token is still there for the user-facing path.
        assert limiter.acquire("dsport", Priority.CLICK, 0) is True

    def test_hover_also_counts_as_user_facing(self):
        clock = FakeClock()
        limiter = MemoryRateLimiter(rps=1.0, capacity=2, reserve=1.0, clock=clock, sleep=clock.sleep)
        assert limiter.acquire("buzz", Priority.COLD, 0) is True
        assert limiter.acquire("buzz", Priority.COLD, 0) is False
        assert limiter.acquire("buzz", Priority.HOVER, 0) is True

    def test_priority_ordering_is_stable(self):
        assert Priority.CLICK < Priority.HOVER < Priority.SWR \
            < Priority.HOT < Priority.WARM < Priority.COLD
        assert Priority.CLICK.is_user_facing and Priority.HOVER.is_user_facing
        assert not Priority.SWR.is_user_facing
        assert not Priority.COLD.is_user_facing

    def test_click_budget_is_subsecond(self):
        """Past ~1.2s the redirect must go out unverified."""
        assert BUDGET_MS[Priority.CLICK] <= 1200
        assert BUDGET_MS[Priority.CLICK] < BUDGET_MS[Priority.SWR]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_opens_after_threshold_and_recovers(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=3, success_threshold=2,
                                 base_cooldown_s=30, clock=clock)
        for _ in range(3):
            breaker.record_failure("dsport")
        assert breaker.state("dsport") == BreakerState.OPEN
        assert breaker.allow("dsport", Priority.COLD) is False
        assert breaker.is_degraded("dsport") is True

        clock.advance(31)
        assert breaker.state("dsport") == BreakerState.HALF_OPEN
        assert breaker.allow("dsport", Priority.COLD) is True

        breaker.record_success("dsport")
        breaker.record_success("dsport")
        assert breaker.state("dsport") == BreakerState.CLOSED
        assert breaker.is_degraded("dsport") is False

    def test_click_probes_recovery_even_when_open(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, clock=clock)
        breaker.record_failure("sizeer")
        assert breaker.allow("sizeer", Priority.COLD) is False
        assert breaker.allow("sizeer", Priority.CLICK) is True

    def test_cooldown_backs_off_exponentially(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, base_cooldown_s=10,
                                 max_cooldown_s=100, clock=clock)
        cooldowns = []
        for _ in range(5):
            breaker.record_failure("megasport")
            cooldowns.append(breaker._entry("megasport").cooldown_s)
        assert cooldowns == [10, 20, 40, 80, 100]   # capped at max


class TestBreakerWait:
    """Waiting out an open circuit instead of discarding the job.

    The bug this closes: `Fetcher.fetch` fails open, so an open circuit comes
    back as a skip in microseconds. A drain loop that reads that skip as "job
    finished" empties its queue at memory speed -- 2 974 jobs in 23 seconds
    during a real 20-second network drop, which cost a two-hour sweep.
    """

    def _open(self, clock, cooldown=30.0):
        breaker = CircuitBreaker(failure_threshold=1, base_cooldown_s=cooldown,
                                 clock=clock)
        breaker.record_failure("sportvision.mk")
        return breaker

    def test_retry_after_reports_the_remaining_cooldown(self):
        clock = FakeClock()
        breaker = self._open(clock)
        assert breaker.retry_after("sportvision.mk") == 30.0

        clock.advance(18)
        assert breaker.retry_after("sportvision.mk") == 12.0

        clock.advance(13)      # past the cooldown: half-open, so no wait
        assert breaker.retry_after("sportvision.mk") == 0.0

    def test_a_healthy_domain_needs_no_wait(self):
        assert CircuitBreaker().retry_after("buzz.mk") == 0.0

    def test_waiting_makes_the_domain_fetchable_again(self):
        clock = FakeClock()
        breaker = self._open(clock)
        waiter = BreakerWait(sleep=clock.sleep)

        assert waiter.wait(breaker, "sportvision.mk") is True
        assert clock.slept >= 30                     # the cooldown, not a guess
        assert breaker.allow("sportvision.mk", Priority.COLD) is True
        assert waiter.waits == 1

    def test_the_budget_is_shared_across_the_drain(self):
        """A merchant that is genuinely down must not hold a sweep open."""
        clock = FakeClock()
        breaker = self._open(clock, cooldown=100.0)
        waiter = BreakerWait(max_total_s=150.0, sleep=clock.sleep)

        assert waiter.wait(breaker, "sportvision.mk") is True

        breaker.record_failure("sportvision.mk")     # down again: 200s now
        assert waiter.wait(breaker, "sportvision.mk") is False
        assert waiter.waits == 1                     # the second never slept

    def test_user_facing_work_never_waits(self):
        """Fail open is the contract at click time; this must not change it."""
        clock = FakeClock()
        breaker = self._open(clock)
        waiter = BreakerWait(sleep=clock.sleep)

        assert waiter.wait(breaker, "sportvision.mk", Priority.CLICK) is False
        assert waiter.wait(breaker, "sportvision.mk", Priority.HOVER) is False
        assert clock.slept == 0


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class TestFetchQueue:
    def _job(self, priority=Priority.COLD, url="https://x.mk/p/1", **kw):
        return FetchJob(merchant_slug="buzz", url=url, priority=priority, **kw)

    def test_strict_priority_then_fifo(self):
        queue = MemoryFetchQueue()
        queue.push(self._job(Priority.COLD, "https://x.mk/cold"))
        queue.push(self._job(Priority.CLICK, "https://x.mk/click"))
        queue.push(self._job(Priority.WARM, "https://x.mk/warm"))
        queue.push(self._job(Priority.CLICK, "https://x.mk/click2"))
        order = [queue.pop().url for _ in range(4)]
        assert order == ["https://x.mk/click", "https://x.mk/click2",
                         "https://x.mk/warm", "https://x.mk/cold"]
        assert queue.pop() is None

    def test_dedupe_collapses_a_traffic_spike(self):
        """400 page views on one product must produce one fetch."""
        queue = MemoryFetchQueue()
        accepted = sum(
            queue.push(self._job(Priority.SWR, "https://x.mk/p/42"))
            for _ in range(400))
        assert accepted == 1
        assert len(queue) == 1

    def test_dedupe_expires(self):
        clock = FakeClock()
        queue = MemoryFetchQueue(clock=clock)
        assert queue.push(self._job(Priority.SWR)) is True
        assert queue.push(self._job(Priority.SWR)) is False
        clock.advance(301)          # SWR dedupe TTL is 300s
        assert queue.push(self._job(Priority.SWR)) is True

    def test_higher_priority_breaks_through_dedupe(self):
        """A waiting user is not blocked by a queued cold crawl."""
        queue = MemoryFetchQueue()
        assert queue.push(self._job(Priority.COLD, "https://x.mk/p/7")) is True
        assert queue.push(self._job(Priority.CLICK, "https://x.mk/p/7")) is True
        assert queue.pop().priority == Priority.CLICK

    def test_escalation_is_one_way(self):
        queue = MemoryFetchQueue()
        assert queue.push(self._job(Priority.CLICK, "https://x.mk/p/8")) is True
        # A cold crawl must not jump a live click's dedupe window.
        assert queue.push(self._job(Priority.COLD, "https://x.mk/p/8")) is False

    def test_post_body_is_part_of_identity(self):
        """sport-m probes differ only by POST body, not by URL."""
        queue = MemoryFetchQueue()
        url = "https://www.sport-m.com.mk/ProductCatalog/GetVelicini/"
        a = self._job(Priority.HOT, url, method="POST", body=b"ProductID=M20325")
        b = self._job(Priority.HOT, url, method="POST", body=b"ProductID=GX6394")
        assert queue.push(a) is True
        assert queue.push(b) is True, "different products collapsed into one job"

    def test_json_round_trip(self):
        job = FetchJob(merchant_slug="sportm", url="https://x.mk/a",
                       kind="stock_probe", priority=Priority.HOT,
                       method="POST", body=b"ProductID=M20325",
                       offer_variant_id=11)
        clone = FetchJob.from_json(job.to_json())
        assert clone.merchant_slug == "sportm"
        assert clone.priority == Priority.HOT
        assert clone.body == b"ProductID=M20325"
        assert clone.offer_variant_id == 11

    def test_requeue_counts_attempts(self):
        queue = MemoryFetchQueue()
        job = self._job()
        queue.push(job)
        popped = queue.pop()
        queue.requeue(popped)
        assert queue.pop().attempt == 1


# ---------------------------------------------------------------------------
# Raw store
# ---------------------------------------------------------------------------

class TestRawStore:
    def test_round_trip(self, tmp_path):
        store = LocalRawStore(tmp_path)
        key = store.put("buzz", "https://www.buzzsneakers.mk/mk/patiki/2011-x",
                        b"<html>hello</html>", "text/html; charset=utf-8")
        assert key.startswith("buzz/")
        assert key.endswith(".html.gz")
        assert store.exists(key)
        snap = store.get(key)
        assert snap.body == b"<html>hello</html>"
        assert snap.meta["merchant_slug"] == "buzz"
        assert snap.meta["bytes"] == 18

    def test_key_is_stable_for_same_body_and_day(self):
        a = snapshot_key("buzz", "https://x.mk/p/1", "text/html", body=b"same")
        b = snapshot_key("buzz", "https://x.mk/p/1", "text/html", body=b"same")
        assert a == b

    def test_same_url_different_body_does_not_collide(self):
        """A price change mid-day must not overwrite the earlier snapshot."""
        a = snapshot_key("buzz", "https://x.mk/p/1", "text/html", body=b"2863")
        b = snapshot_key("buzz", "https://x.mk/p/1", "text/html", body=b"3999")
        assert a != b

    def test_compresses(self, tmp_path):
        store = LocalRawStore(tmp_path)
        body = b"<html>" + b"x" * 200_000 + b"</html>"
        key = store.put("dsport", "https://www.dsport.mk/p", body, "text/html")
        on_disk = (tmp_path / key).stat().st_size
        assert on_disk < len(body) / 10
        assert store.get(key).body == body

    def test_rejects_traversal(self, tmp_path):
        store = LocalRawStore(tmp_path)
        with pytest.raises(ValueError):
            store.get("../../etc/passwd")


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

def make_fetcher(routes, *, clock=None, respect_robots=False, **kw):
    transport = StubTransport(routes=routes)
    clock = clock or FakeClock()
    fetcher = Fetcher(
        transport,
        limiter=MemoryRateLimiter(rps=100.0, capacity=100, reserve=0, clock=clock, sleep=clock.sleep),
        breaker=CircuitBreaker(clock=clock),
        config=FetcherConfig(respect_robots=respect_robots, max_attempts=2,
                             backoff_base_s=0),
        clock=clock, sleep=clock.sleep, **kw)
    return fetcher, transport, clock


class TestFetcher:
    def test_successful_fetch_archives_the_body(self, tmp_path):
        store = LocalRawStore(tmp_path)
        fetcher, _, _ = make_fetcher(
            {"/p/1": (200, {"content-type": "text/html", "etag": 'W/"abc"'},
                      b"<html>ok</html>")},
            raw_store=store)
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p/1"))
        assert result.ok
        assert result.body == b"<html>ok</html>"
        assert result.snapshot_key and store.exists(result.snapshot_key)

    def test_sends_conditional_headers_on_the_second_fetch(self):
        fetcher, transport, _ = make_fetcher(
            {"/p/1": (200, {"content-type": "text/html", "etag": 'W/"v1"',
                            "last-modified": "Mon, 10 Nov 2026 00:00:00 GMT"},
                      b"body")})
        job = FetchJob(merchant_slug="buzz", url="https://x.mk/p/1")
        fetcher.fetch(job)
        assert "If-None-Match" not in transport.calls[0]["headers"]

        fetcher.fetch(FetchJob(merchant_slug="buzz", url="https://x.mk/p/1"))
        headers = transport.calls[1]["headers"]
        assert headers["If-None-Match"] == 'W/"v1"'
        assert headers["If-Modified-Since"] == "Mon, 10 Nov 2026 00:00:00 GMT"

    def test_304_is_a_real_observation(self):
        fetcher, _, _ = make_fetcher({"/p/1": (304, {}, b"")})
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p/1"))
        assert result.not_modified
        assert not result.ok
        assert not result.should_retry
        assert result.skipped is None

    def test_identifies_itself_contactably(self):
        fetcher, transport, _ = make_fetcher({"/p": (200, {}, b"x")})
        fetcher.fetch(FetchJob(merchant_slug="buzz", url="https://x.mk/p"))
        ua = transport.calls[0]["headers"]["User-Agent"]
        assert "MKPriceCompareBot" in ua
        assert "@" in ua or "http" in ua, "UA must carry a way to reach us"

    def test_exceptions_never_escape(self):
        def boom(*_):
            raise TimeoutError("connection timed out")

        fetcher, _, _ = make_fetcher({"/p": boom})
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p"))
        assert not result.ok
        assert "TimeoutError" in result.error

    def test_rate_limited_is_a_skip_not_an_error(self):
        clock = FakeClock()
        transport = StubTransport(routes={"/p": (200, {}, b"x")})
        fetcher = Fetcher(
            transport,
            limiter=MemoryRateLimiter(rps=1, capacity=1, reserve=1, clock=clock, sleep=clock.sleep),
            config=FetcherConfig(respect_robots=False),
            clock=clock, sleep=clock.sleep)
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p",
                                        priority=Priority.COLD))
        assert result.skipped == "rate_limited"
        assert result.error is None
        assert transport.calls == [], "no request should have gone out"

    def test_open_breaker_skips_background_work(self):
        fetcher, transport, _ = make_fetcher({"/p": (500, {}, b"err")})
        for _ in range(10):
            fetcher.fetch(FetchJob(merchant_slug="buzz", url="https://x.mk/p",
                                    priority=Priority.COLD))
        before = len(transport.calls)
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p",
                                        priority=Priority.COLD))
        assert result.skipped == "circuit_open"
        assert len(transport.calls) == before
        assert fetcher.breaker.is_degraded("buzz")

    def test_archive_failure_does_not_fail_the_fetch(self):
        class BrokenStore:
            def put(self, *a, **k):
                raise OSError("disk full")

        fetcher, _, _ = make_fetcher({"/p": (200, {}, b"body")},
                                      raw_store=BrokenStore())
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/p"))
        assert result.ok, "a full disk must not lose us the data we just fetched"
        assert "archive_failed" in result.error

    def test_post_body_and_headers_are_passed_through(self):
        fetcher, transport, _ = make_fetcher(
            {"GetVelicini": (200, {"content-type": "application/json"}, b"[]")})
        fetcher.fetch(FetchJob(
            merchant_slug="sportm",
            url="https://www.sport-m.com.mk/ProductCatalog/GetVelicini/",
            method="POST", body=b"ProductID=M20325",
            headers={"X-Requested-With": "XMLHttpRequest"}))
        call = transport.calls[0]
        assert call["method"] == "POST"
        assert call["body"] == b"ProductID=M20325"
        assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"

    def test_click_priority_stays_within_budget(self):
        """Real sleeping here, so keep the budget small and the assert loose."""
        def slow(*_):
            time.sleep(0.2)
            return (503, {}, b"busy")

        transport = StubTransport(routes={"/p": slow})
        fetcher = Fetcher(
            transport,
            limiter=MemoryRateLimiter(rps=100, capacity=100, reserve=0),
            config=FetcherConfig(respect_robots=False, max_attempts=5,
                                 backoff_base_s=0.1))
        started = time.monotonic()
        fetcher.fetch(FetchJob(merchant_slug="buzz", url="https://x.mk/p",
                               priority=Priority.CLICK))
        elapsed_ms = (time.monotonic() - started) * 1000
        assert elapsed_ms < BUDGET_MS[Priority.CLICK] * 2.5


class TestRobots:
    def test_404_means_no_restrictions(self):
        """Four of the seven target stores return 404 for robots.txt."""
        transport = StubTransport(routes={"/robots.txt": (404, {}, b"")})
        robots = RobotsCache(transport, clock=FakeClock())
        assert robots.allowed("https://sizeer.com.mk/anything") is True

    def test_5xx_disallows_for_now(self):
        """RFC 9309: a server error is a temporary complete disallow."""
        transport = StubTransport(routes={"/robots.txt": (503, {}, b"")})
        robots = RobotsCache(transport, clock=FakeClock())
        assert robots.allowed("https://x.mk/p") is False

    def test_disallow_is_honoured(self):
        body = b"User-agent: *\nDisallow: /cart\nAllow: /\n"
        transport = StubTransport(
            routes={"/robots.txt": (200, {"content-type": "text/plain"}, body)})
        robots = RobotsCache(transport, clock=FakeClock())
        assert robots.allowed("https://x.mk/mk/patiki/1-x") is True
        assert robots.allowed("https://x.mk/cart") is False

    def test_result_is_cached_per_origin(self):
        transport = StubTransport(routes={"/robots.txt": (404, {}, b"")})
        robots = RobotsCache(transport, clock=FakeClock())
        for _ in range(5):
            robots.allowed("https://x.mk/p")
        assert len(transport.calls) == 1

    def test_fetcher_skips_disallowed_urls(self):
        body = b"User-agent: *\nDisallow: /private\n"
        fetcher, transport, _ = make_fetcher(
            {"/robots.txt": (200, {"content-type": "text/plain"}, body),
             "/private": (200, {}, b"secret")},
            respect_robots=True)
        result = fetcher.fetch(FetchJob(merchant_slug="buzz",
                                        url="https://x.mk/private"))
        assert result.skipped == "robots_disallowed"
        assert all("/private" not in c["url"] for c in transport.calls)


# ---------------------------------------------------------------------------
# Adaptive TTL
# ---------------------------------------------------------------------------

class TestAdaptiveTtl:
    """Adaptive TTL, and the tier floor that bounds it.

    Worth being explicit about the division of labour, because the first
    version of these tests got it wrong: ``next_ttl`` moves a variant *within*
    its tier's band and can never leave it. Moving between bands is
    ``assign_tiers``' job, driven by demand. So a cold variant that starts
    changing hourly tightens only to the cold floor (12 h) until traffic
    promotes it -- which is the politeness floor working as intended, not a
    bug.
    """

    def test_unchanged_backs_off_within_the_band(self):
        # Hot tier spans 900-1800s, so 1000s has room to grow.
        assert next_ttl(1000, changed=False, tier="S") == 1500

    def test_changed_leans_in_within_the_band(self):
        assert next_ttl(1800, changed=True, tier="S") == 900

    def test_backoff_and_lean_in_are_asymmetric(self):
        """Leaning in is faster than backing off, deliberately.

        Being slow to notice a change costs trust; being slow to relax costs
        a few cheap 304s.
        """
        ttl = 50_000
        assert next_ttl(ttl, changed=False, tier="B") == 75_000   # x1.5
        assert next_ttl(75_000, changed=True, tier="B") == 43_200  # /3, clamped

    def test_tier_floor_bounds_the_fastest_cadence(self):
        ttl = 1800
        for _ in range(20):
            ttl = next_ttl(ttl, changed=True, tier="S")
        assert ttl == 900, "hot tier must not probe faster than its floor"

    def test_tier_ceiling_bounds_the_slowest_cadence(self):
        ttl = 900
        for _ in range(20):
            ttl = next_ttl(ttl, changed=False, tier="S")
        assert ttl == 1800, "a quiet week must not push a hot offer to daily"

    def test_cold_tier_settles_at_daily(self):
        ttl = 43_200
        for _ in range(10):
            ttl = next_ttl(ttl, changed=False, tier="B")
        assert ttl == 86_400

    def test_cold_volatility_stops_at_the_cold_floor(self):
        """A volatile cold variant tightens to 12 h and no further.

        Reaching minutes requires promotion by assign_tiers, so traffic -- not
        volatility alone -- is what earns a merchant's bandwidth.
        """
        ttl = 86_400
        for _ in range(5):
            ttl = next_ttl(ttl, changed=True, tier="B")
        assert ttl == 43_200

    def test_unknown_tier_falls_back_to_cold(self):
        assert next_ttl(50_000, changed=False, tier="?") ==             next_ttl(50_000, changed=False, tier="B")


class TestRobotsBlockedRoute:
    """An unauthenticated endpoint is not permission to crawl it.

    Phase 1 recon concluded that dsport (open Magento GraphQL) and megasport
    (open WooCommerce Store API) needed no scraping at all. The first live run
    of the fetcher disproved it: both sites forbid exactly those paths.

        dsport.mk                Disallow: /graphql
        megasportonlineshop.com  Disallow: /wp-json/

    The API adapters stay correct and stay in the tree -- one email converts
    them from forbidden to usable -- but the scheduler must refuse to queue
    them, loudly enough to show up on a dashboard.
    """

    def _due(self, adapter, merchant, blocked):
        from mkagg.fetch.scheduler import DueVariant
        return DueVariant(
            variant_id=1, tier="S", price_minor=3999, size_label="44",
            offer_id=1, merchant_sku="392290-02",
            product_url=f"https://{merchant}.mk/p/1",
            merchant_slug=merchant, adapter=adapter,
            base_url=f"https://{merchant}.mk", publishes_stock=True,
            api_requires_permission=blocked)

    def test_blocked_api_route_raises(self):
        from mkagg.fetch import RobotsBlocked, build_stock_probe
        for adapter, merchant in (("magento", "dsport"),
                                  ("woocommerce", "megasport")):
            with pytest.raises(RobotsBlocked):
                build_stock_probe(self._due(adapter, merchant, blocked=True))

    def test_permission_granted_unblocks_it(self):
        from mkagg.fetch import build_stock_probe
        job = build_stock_probe(self._due("magento", "dsport", blocked=False))
        assert job.method == "POST"
        assert job.url.endswith("/graphql")

    def test_html_adapters_are_never_blocked(self):
        """sportvision and aspnet_mk probe paths their sites permit."""
        from mkagg.fetch import build_stock_probe
        for adapter, merchant in (("sportvision", "buzz"),
                                  ("aspnet_mk", "sportm")):
            job = build_stock_probe(self._due(adapter, merchant, blocked=True))
            assert job.url

    def test_enqueue_reports_blocked_instead_of_dropping(self):
        from mkagg.fetch import MemoryFetchQueue
        from mkagg.fetch.scheduler import build_stock_probe, RobotsBlocked

        due = [self._due("magento", "dsport", True),
               self._due("woocommerce", "megasport", True),
               self._due("aspnet_mk", "sportm", True)]
        queue = MemoryFetchQueue()
        pushed = blocked = 0
        for d in due:
            try:
                queue.push(build_stock_probe(d))
                pushed += 1
            except RobotsBlocked:
                blocked += 1
        assert (pushed, blocked) == (1, 2)


# ---------------------------------------------------------------------------
# Fetching patiently
# ---------------------------------------------------------------------------

HTML_CT = {"content-type": "text/html"}


class TestFetchPatiently:
    """`fetch_patiently` is `fetch` plus "an open circuit is not an answer"."""

    def _fetcher(self):
        # Five 503s trip the default breaker; /ok/ then answers normally.
        return make_fetcher({"/fail/": (503, HTML_CT, b"busy"),
                             "/ok/": (200, HTML_CT, b"<html>ok</html>")})

    def _trip(self, fetcher):
        for i in range(5):
            fetcher.fetch(FetchJob(merchant_slug="sportvision",
                                   url=f"https://x.mk/fail/{i}"))

    def test_without_a_waiter_it_is_plain_fetch(self):
        fetcher, _, _ = self._fetcher()
        self._trip(fetcher)

        result = fetch_patiently(
            fetcher, FetchJob(merchant_slug="sportvision",
                              url="https://x.mk/ok/1"))
        assert result.skipped == "circuit_open"

    def test_with_a_waiter_the_job_is_fetched_after_the_cooldown(self):
        fetcher, _, clock = self._fetcher()
        self._trip(fetcher)
        waiter = BreakerWait(sleep=clock.sleep)

        result = fetch_patiently(
            fetcher, FetchJob(merchant_slug="sportvision",
                              url="https://x.mk/ok/1"), waiter)

        assert result.ok
        assert result.body == b"<html>ok</html>"
        assert waiter.waits == 1
        assert clock.slept >= 30

    def test_a_spent_budget_skips_as_before(self):
        fetcher, _, clock = self._fetcher()
        self._trip(fetcher)
        waiter = BreakerWait(max_total_s=0.0, sleep=clock.sleep)

        result = fetch_patiently(
            fetcher, FetchJob(merchant_slug="sportvision",
                              url="https://x.mk/ok/1"), waiter)

        assert result.skipped == "circuit_open"
        assert clock.slept == 0

    def test_it_cannot_spin_on_one_job(self):
        """The bound exists for a breaker that refuses while promising 0s.

        Single-threaded that cannot happen, but the breaker is shared, and a
        loop with no bound is a loop that one day does not end.
        """
        class AlwaysOpen:
            def allow(self, key, priority=Priority.COLD):
                return False

            def retry_after(self, key, priority=Priority.COLD):
                return 0.0

            def record_success(self, key):
                pass

            def record_failure(self, key):
                pass

        fetcher, _, clock = self._fetcher()
        fetcher.breaker = AlwaysOpen()
        waiter = BreakerWait(sleep=clock.sleep)

        result = fetch_patiently(
            fetcher, FetchJob(merchant_slug="sportvision",
                              url="https://x.mk/ok/1"), waiter)

        assert result.skipped == "circuit_open"
        assert fetcher.stats["circuit_open"] == MAX_BREAKER_REFETCHES + 1
