"""Worker-loop tests.

The loop is where everything meets, so these are mostly about what happens
when something goes wrong: a slow store, a 403, a redesign that breaks a
parser, a price that moved implausibly far. The rule being tested throughout
is that a bad merchant costs its own jobs and nothing else.

Database-backed cases skip cleanly without Postgres.
"""
from __future__ import annotations

import gzip
import os
from decimal import Decimal

import pytest
from conftest import load_bytes

from mkagg.fetch import (CircuitBreaker, FetchJob, Fetcher, FetcherConfig,
                         MemoryFetchQueue, MemoryRateLimiter, Priority,
                         StubTransport)
from mkagg.models import RawOffer, RawVariant
from mkagg.worker import (IMPLAUSIBLE_MOVE, WorkerReport, parse_result,
                          run_once)

#: Tests TRUNCATE, so they default to a SEPARATE database. Pointing them at
#: the development database would wipe it -- which is exactly what happened
#: once before this default existed. Override with MKAGG_TEST_DSN only.
DSN = os.environ.get(
    "MKAGG_TEST_DSN",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg_test")

HTML = {"content-type": "text/html"}
JSON = {"content-type": "application/json"}


def make_fetcher(routes, **kw):
    return Fetcher(
        StubTransport(routes=routes),
        limiter=MemoryRateLimiter(rps=1000, capacity=1000, reserve=0),
        breaker=CircuitBreaker(),
        config=FetcherConfig(respect_robots=False, max_attempts=1), **kw)


MERCHANTS = {
    "sportvision": {"slug": "sportvision", "id": 1, "adapter": "sportvision",
                    "base_url": "https://www.sportvision.mk",
                    "publishes_stock": True},
    "sportm": {"slug": "sportm", "id": 6, "adapter": "aspnet_mk",
               "base_url": "https://www.sport-m.com.mk",
               "publishes_stock": True},
    "sizeer": {"slug": "sizeer", "id": 7, "adapter": "aspnet_mk",
               "base_url": "https://sizeer.com.mk", "publishes_stock": False},
}


# ---------------------------------------------------------------------------
# Parsing a fetch result through the right adapter
# ---------------------------------------------------------------------------

class TestParseResult:
    def test_html_adapter_route(self):
        body = load_bytes("sportvision_caven20.html")
        fetcher = make_fetcher({"/mk/patiki": (200, HTML, body)})
        job = FetchJob(
            merchant_slug="sportvision",
            url="https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0")
        result = fetcher.fetch(job)
        offers = parse_result(fetcher, result, MERCHANTS["sportvision"])
        assert len(offers) == 1
        assert offers[0].raw_mpn == "392290-02"
        assert len(offers[0].variants) == 20

    def test_aspnet_catalog_parse_issues_the_companion_size_request(self):
        """sport-m's page has no sizes; they live behind POST /GetVelicini/."""
        page = load_bytes("sportm_stansmith.html")
        sizes = load_bytes("sportm_getvelicini_M20325.json")
        fetcher = make_fetcher({
            "ProductDetails": (200, HTML, page),
            "GetVelicini": (200, JSON, sizes),
        })
        job = FetchJob(
            merchant_slug="sportm",
            url="https://www.sport-m.com.mk/ProductCatalog/"
                "ProductDetails?ProductID=M20325")
        result = fetcher.fetch(job)
        offers = parse_result(fetcher, result, MERCHANTS["sportm"])
        assert len(offers) == 1
        assert len(offers[0].variants) == 8
        assert all(v.stock_qty for v in offers[0].variants)
        posts = [c for c in fetcher.transport.calls if c["method"] == "POST"]
        assert len(posts) == 1
        assert posts[0]["body"] == b"ProductID=M20325"

    def test_aspnet_stock_probe_uses_the_payload_directly(self):
        """A POST job already *is* the size payload: no second request."""
        sizes = load_bytes("sizeer_getvelicini_M20325.json")
        fetcher = make_fetcher({"GetVelicini": (200, JSON, sizes)})
        job = FetchJob(
            merchant_slug="sizeer",
            url="https://sizeer.com.mk/ProductCatalog/GetVelicini/",
            kind="stock_probe", method="POST", body=b"ProductID=M20325")
        result = fetcher.fetch(job)
        offers = parse_result(fetcher, result, MERCHANTS["sizeer"])
        assert len(offers) == 1
        # sizeer publishes no stock, and that must survive the worker.
        assert all(v.in_stock is None for v in offers[0].variants)
        assert len(fetcher.transport.calls) == 1


# ---------------------------------------------------------------------------
# The loop, without a database
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, rows): self._rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, q, p=None):
        self.q = q
        if "FROM merchant WHERE is_active" in q:
            self._out = [(m["slug"], m["id"], m["adapter"], m["base_url"],
                          m["publishes_stock"]) for m in MERCHANTS.values()]
        else:
            self._out = self._rows
    def fetchall(self): return self._out
    def fetchone(self): return self._out[0] if self._out else None


class FakeConn:
    """Just enough connection for the no-database paths."""

    def __init__(self, rows=()): self._rows = list(rows); self.commits = 0
    def cursor(self): return FakeCursor(self._rows)
    def commit(self): self.commits += 1
    def rollback(self): pass


def _no_ingest(*args, **kwargs):
    """Stand-in for the loader: these tests are about the loop, not the gate."""
    return None


class TestLoopResilience:
    def _queue(self, *jobs):
        queue = MemoryFetchQueue()
        for job in jobs:
            queue.push(job, dedupe=False)
        return queue

    def test_http_error_costs_only_its_own_job(self):
        body = load_bytes("sportvision_caven20.html")
        fetcher = make_fetcher({"/good": (200, HTML, body),
                                "/bad": (503, HTML, b"busy")})
        queue = self._queue(
            FetchJob(merchant_slug="sportvision", url="https://x.mk/bad"),
            FetchJob(merchant_slug="sportvision", url="https://x.mk/good"))
        report = run_once(FakeConn(), fetcher, queue,
                          ingest_fn=_no_ingest)
        assert report.jobs_processed == 2
        assert report.http_errors == 1
        assert report.offers_parsed == 1

    def test_parser_exception_is_contained(self):
        """A redesign that breaks a parser must not end the cycle."""
        fetcher = make_fetcher({"/x": (200, HTML, b"<html>nothing useful</html>")})
        queue = self._queue(
            FetchJob(merchant_slug="sportvision", url="https://x.mk/x"))
        report = run_once(FakeConn(), fetcher, queue,
                          ingest_fn=_no_ingest)
        assert report.parse_failures == 1
        assert report.offers_parsed == 0

    def test_skips_are_counted_by_reason(self):
        fetcher = Fetcher(
            StubTransport(routes={"/x": (200, HTML, b"x")}),
            limiter=MemoryRateLimiter(rps=1, capacity=1, reserve=1),
            config=FetcherConfig(respect_robots=False))
        queue = self._queue(
            FetchJob(merchant_slug="sportvision", url="https://x.mk/x",
                     priority=Priority.COLD))
        report = run_once(FakeConn(), fetcher, queue,
                          ingest_fn=_no_ingest)
        assert report.skipped["rate_limited"] == 1
        assert report.http_errors == 0

    def test_unknown_merchant_is_ignored_not_fatal(self):
        fetcher = make_fetcher({"/x": (200, HTML, b"x")})
        queue = self._queue(
            FetchJob(merchant_slug="not_a_merchant", url="https://x.mk/x"))
        report = run_once(FakeConn(), fetcher, queue,
                          ingest_fn=_no_ingest)
        assert report.jobs_processed == 1
        assert report.fetched == 0

    def test_max_jobs_bounds_one_cycle(self):
        body = load_bytes("sportvision_caven20.html")
        fetcher = make_fetcher({"/p": (200, HTML, body)})
        queue = self._queue(*[
            FetchJob(merchant_slug="sportvision", url=f"https://x.mk/p/{i}")
            for i in range(10)])
        report = run_once(FakeConn(), fetcher, queue, max_jobs=3,
                          ingest_fn=_no_ingest)
        assert report.jobs_processed == 3
        assert len(queue) == 7

    def test_report_summary_is_readable(self):
        report = WorkerReport(jobs_processed=5, fetched=4, http_errors=1,
                              offers_parsed=4, duration_s=1.25)
        text = report.summary()
        assert "jobs=5" in text and "errors=1" in text and "1.2s" in text


# ---------------------------------------------------------------------------
# End to end, with Postgres
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        connection = psycopg.connect(DSN, connect_timeout=3)
    except Exception as exc:               # pragma: no cover
        pytest.skip(f"no database at {DSN}: {exc}")
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def clean_db(conn):
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE stage_offer, stage_variant, ingest_run, price_point,
                     click_event, verification_event, match_candidate,
                     user_price_report, product_price_summary, offer_variant,
                     merchant_offer, product_identifier, product
            RESTART IDENTITY CASCADE""")
    conn.commit()
    return conn


@pytest.mark.usefixtures("clean_db")
class TestWorkerWithDatabase:
    def test_catalog_job_lands_in_the_catalogue(self, conn):
        body = load_bytes("sportvision_caven20.html")
        fetcher = make_fetcher({"/mk/patiki": (200, HTML, body)})
        queue = MemoryFetchQueue()
        queue.push(FetchJob(
            merchant_slug="sportvision",
            url="https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0",
            kind="catalog_parse"))

        report = run_once(conn, fetcher, queue)
        assert report.offers_parsed == 1
        assert len(report.ingests) == 1
        outcome = report.ingests[0]
        assert outcome.promoted
        assert outcome.promotion.products_created == 1

        with conn.cursor() as cur:
            cur.execute("""SELECT min_price_minor FROM product_price_summary""")
            assert cur.fetchone()[0] == 2863

    def test_offers_batch_into_one_run_per_merchant(self, conn):
        """A sweep is one ingest_run with one gate decision, not one per page."""
        body = load_bytes("sportvision_caven20.html")
        other = load_bytes("sportreality_caven20.html")
        fetcher = make_fetcher({"/a": (200, HTML, body), "/b": (200, HTML, other)})
        queue = MemoryFetchQueue()
        for path in ("/a", "/b"):
            queue.push(FetchJob(
                merchant_slug="sportvision",
                url=f"https://www.sportvision.mk/mk/patiki/8550245-x{path}",
                kind="catalog_parse"), dedupe=False)
        report = run_once(conn, fetcher, queue)
        assert len(report.ingests) == 1, "expected a single run for the merchant"
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingest_run")
            assert cur.fetchone()[0] == 1

    def test_stock_probe_writes_history_only_on_change(self, conn):
        from mkagg.load import ingest

        sizes = load_bytes("sportm_getvelicini_M20325.json")
        page = load_bytes("sportm_stansmith.html")
        fetcher = make_fetcher({"ProductDetails": (200, HTML, page),
                                "GetVelicini": (200, JSON, sizes)})
        offers = parse_result(
            fetcher,
            fetcher.fetch(FetchJob(
                merchant_slug="sportm",
                url="https://www.sport-m.com.mk/ProductCatalog/"
                    "ProductDetails?ProductID=M20325")),
            MERCHANTS["sportm"])
        ingest(conn, "sportm", offers, requests=1)

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM merchant_offer")
            offer_id = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM price_point")
            before = cur.fetchone()[0]

        queue = MemoryFetchQueue()
        queue.push(FetchJob(
            merchant_slug="sportm",
            url="https://www.sport-m.com.mk/ProductCatalog/GetVelicini/",
            kind="stock_probe", method="POST", body=b"ProductID=M20325",
            offer_id=offer_id))
        report = run_once(conn, fetcher, queue)

        assert report.probes_applied == 8
        assert report.probes_changed == 0, "identical probe wrote history"
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            assert cur.fetchone()[0] == before

    def test_implausible_price_move_is_quarantined(self, conn):
        """A parser reading the wrong element produces a huge jump.

        The live price must stay put and the disagreement be recorded, rather
        than a bad number being published because it arrived from a probe.
        """
        from mkagg.load import ingest

        offer = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="Puma Caven 2.0", raw_brand="Puma",
            product_url="https://www.sportvision.mk/mk/patiki/8550245-x",
            variants=[RawVariant(size_label="42", size_eu=Decimal("42"),
                                 price_minor=2863, in_stock=True,
                                 merchant_variant_id="v42")])
        ingest(conn, "sportvision", [offer], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM merchant_offer")
            offer_id = cur.fetchone()[0]

        crashed = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="Puma Caven 2.0",
            product_url="https://www.sportvision.mk/mk/patiki/8550245-x",
            variants=[RawVariant(size_label="42", size_eu=Decimal("42"),
                                 price_minor=99, in_stock=True,
                                 merchant_variant_id="v42")])
        from mkagg.worker import apply_probe
        report = WorkerReport()
        apply_probe(conn, crashed,
                    FetchJob(merchant_slug="sportvision", url="x",
                             kind="stock_probe", offer_id=offer_id), report)
        conn.commit()

        assert report.probes_rejected == 1
        assert report.probes_applied == 0
        with conn.cursor() as cur:
            cur.execute("SELECT price_minor FROM offer_variant")
            assert cur.fetchone()[0] == 2863, "quarantine failed to protect it"
            cur.execute("""SELECT outcome, shown_price_minor, live_price_minor
                             FROM verification_event""")
            outcome, shown, live = cur.fetchone()
        assert outcome == "price_changed" and shown == 2863 and live == 99

    def test_plausible_price_move_is_applied(self, conn):
        from mkagg.load import ingest
        from mkagg.worker import apply_probe

        offer = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="Puma Caven 2.0", raw_brand="Puma",
            product_url="https://www.sportvision.mk/mk/patiki/8550245-x",
            variants=[RawVariant(size_label="42", size_eu=Decimal("42"),
                                 price_minor=2863, in_stock=True,
                                 merchant_variant_id="v42")])
        ingest(conn, "sportvision", [offer], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM merchant_offer")
            offer_id = cur.fetchone()[0]

        # A 20% sale: well inside the guard.
        discounted = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="Puma Caven 2.0",
            product_url="https://www.sportvision.mk/mk/patiki/8550245-x",
            variants=[RawVariant(size_label="42", size_eu=Decimal("42"),
                                 price_minor=2290, in_stock=True,
                                 merchant_variant_id="v42")])
        report = WorkerReport()
        apply_probe(conn, discounted,
                    FetchJob(merchant_slug="sportvision", url="x",
                             kind="stock_probe", offer_id=offer_id), report)
        conn.commit()
        assert report.probes_applied == 1 and report.probes_changed == 1
        with conn.cursor() as cur:
            cur.execute("SELECT price_minor FROM offer_variant")
            assert cur.fetchone()[0] == 2290

    def test_guard_threshold_is_a_sane_fraction(self):
        assert 0.3 <= IMPLAUSIBLE_MOVE <= 0.9


class TestUnpricedOfferFilter:
    """Which price-less offers the worker keeps, and which it drops.

    The filter exists because an offer with no price cannot sit on a
    comparison page. But "sold out and the shop publishes no price" is a real
    state some shops expose -- megasport strips the price when stock runs out
    -- and that offer is worth showing. The two cases have to be told apart
    on positive evidence, not on the absence of a number.
    """

    @staticmethod
    def _offer(price, in_stock, sku="X1"):
        return RawOffer(
            merchant_slug="megasport", merchant_sku=sku, raw_mpn=sku,
            raw_title="Patiki", raw_brand="Adidas",
            product_url=f"https://megasportonlineshop.com/p/{sku}/",
            variants=[RawVariant(size_label="", price_minor=price,
                                 in_stock=in_stock)])

    def test_sold_out_with_no_price_is_a_complete_offer(self):
        assert self._offer(None, False).is_sold_out_unpriced

    def test_no_price_but_stock_unknown_is_not(self):
        """The shape a parser regression takes.

        No price and nothing said about stock is an extraction failure, and
        keeping it would quietly fill the catalogue with price-less rows
        instead of tripping the gate.
        """
        assert not self._offer(None, None).is_sold_out_unpriced

    def test_no_price_but_claimed_in_stock_is_not(self):
        assert not self._offer(None, True).is_sold_out_unpriced

    def test_a_priced_offer_is_not(self):
        assert not self._offer(2863, False).is_sold_out_unpriced

    def test_the_gate_accepts_the_sold_out_one_and_rejects_the_others(self):
        """`quality_issues` is what the loader rejects a run over."""
        assert self._offer(None, False).quality_issues() == []
        assert "missing_price" in self._offer(None, None).quality_issues()
        assert "missing_price" in self._offer(None, True).quality_issues()


class TestStockOnlyProbes:
    """GetVelicini returns sizes and stock, never a price.

    Every variant therefore arrives with price_minor == 0. The first version
    of apply_probe wrote that straight through, because the guard tested
    `old_price and new_price and ...` and 0 is falsy -- so the one value that
    should always be caught was the one value that bypassed the check.
    """

    def test_stock_only_payload_preserves_the_price(self, clean_db):
        from mkagg.load import ingest
        from mkagg.worker import apply_probe

        conn = clean_db
        offer = RawOffer(
            merchant_slug="sportm", merchant_sku="M20325", raw_mpn="M20325",
            raw_title="Adidas Stan Smith", raw_brand="Adidas",
            product_url="https://www.sport-m.com.mk/p?ProductID=M20325",
            variants=[RawVariant(size_label="44", size_eu=Decimal("44"),
                                 price_minor=6799, in_stock=True,
                                 stock_qty=1)])
        ingest(conn, "sportm", [offer], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM merchant_offer")
            offer_id = cur.fetchone()[0]

        # What GetVelicini actually yields: sizes and stock, price 0.
        stock_only = RawOffer(
            merchant_slug="sportm", merchant_sku="M20325", raw_mpn="M20325",
            raw_title="", product_url="x",
            variants=[RawVariant(size_label="44", size_eu=Decimal("44"),
                                 price_minor=0, in_stock=True, stock_qty=4)])
        report = WorkerReport()
        apply_probe(conn, stock_only,
                    FetchJob(merchant_slug="sportm", url="x",
                             kind="stock_probe", offer_id=offer_id), report)
        conn.commit()

        assert report.probes_rejected == 0
        assert report.probes_applied == 1
        with conn.cursor() as cur:
            cur.execute("SELECT price_minor, stock_qty FROM offer_variant")
            price, qty = cur.fetchone()
        assert price == 6799, "a stock-only probe overwrote the price"
        assert qty == 4, "the stock update was dropped"

    def test_zero_price_among_priced_sizes_is_quarantined(self, clean_db):
        """Some sizes priced and one at zero is a parser fault, not a feature."""
        from mkagg.load import ingest
        from mkagg.worker import apply_probe

        conn = clean_db
        offer = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="Puma Caven 2.0", raw_brand="Puma",
            product_url="https://www.sportvision.mk/mk/patiki/8550245-x",
            variants=[
                RawVariant(size_label="42", size_eu=Decimal("42"),
                           price_minor=2863, in_stock=True,
                           merchant_variant_id="v42"),
                RawVariant(size_label="43", size_eu=Decimal("43"),
                           price_minor=2863, in_stock=True,
                           merchant_variant_id="v43")])
        ingest(conn, "sportvision", [offer], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM merchant_offer")
            offer_id = cur.fetchone()[0]

        half_broken = RawOffer(
            merchant_slug="sportvision", merchant_sku="8550245",
            raw_mpn="392290-02", raw_title="", product_url="x",
            variants=[
                RawVariant(size_label="42", size_eu=Decimal("42"),
                           price_minor=2863, in_stock=True,
                           merchant_variant_id="v42"),
                RawVariant(size_label="43", size_eu=Decimal("43"),
                           price_minor=0, in_stock=True,
                           merchant_variant_id="v43")])
        report = WorkerReport()
        apply_probe(conn, half_broken,
                    FetchJob(merchant_slug="sportvision", url="x",
                             kind="stock_probe", offer_id=offer_id), report)
        conn.commit()

        assert report.probes_applied == 1
        assert report.probes_rejected == 1
        with conn.cursor() as cur:
            cur.execute("SELECT price_minor FROM offer_variant ORDER BY size_eu")
            assert [r[0] for r in cur.fetchall()] == [2863, 2863]


class TestUnpricedOffers:
    """A listing with no price is not an offer.

    megasport publishes discontinued stock with `data-product_variations="[]"`,
    an `out-of-stock` marker and a JSON-LD price of 0. Staging those dropped
    the merchant's price fill rate to 80%, which made the gate reject the whole
    run -- so one dud listing blocked four good offers.
    """

    def test_unpriced_offers_are_dropped_and_counted(self):
        from mkagg.worker import run_once

        priced = RawOffer(
            merchant_slug="sportvision", merchant_sku="1", raw_mpn="392290-02",
            raw_title="Puma Caven 2.0", product_url="https://x.mk/p/1",
            variants=[RawVariant(size_label="42", price_minor=2863)])
        unpriced = RawOffer(
            merchant_slug="sportvision", merchant_sku="2", raw_mpn="XX1",
            raw_title="Discontinued thing", product_url="https://x.mk/p/2",
            variants=[])

        captured = {}

        def fake_ingest(conn, slug, offers, **kwargs):
            captured[slug] = offers
            return None

        fetcher = make_fetcher({"/p": (200, HTML, b"<html></html>")})
        queue = MemoryFetchQueue()
        # kind matters: FetchJob defaults to "stock_probe", and the filter
        # deliberately does not apply to probes.
        queue.push(FetchJob(merchant_slug="sportvision", url="https://x.mk/p",
                            kind="catalog_parse"))

        import mkagg.worker as worker
        original = worker.parse_result
        worker.parse_result = lambda f, r, m: [priced, unpriced]
        try:
            report = run_once(FakeConn(), fetcher, queue, ingest_fn=fake_ingest)
        finally:
            worker.parse_result = original

        assert report.offers_unpriced == 1
        assert report.offers_parsed == 1
        assert [o.merchant_sku for o in captured["sportvision"]] == ["1"]

    def test_a_rise_in_unpriced_is_visible_in_the_summary(self):
        report = WorkerReport(jobs_processed=5, fetched=5, offers_parsed=1,
                              offers_unpriced=4, duration_s=1.0)
        # The same symptom as a parser that stopped finding prices, so it has
        # to be legible rather than silent.
        assert "unpriced=4" in report.summary()
