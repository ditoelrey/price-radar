"""Loader tests.

The validator is pure and always runs. The staging/promotion tests need a
Postgres and skip cleanly without one, so a clean checkout still gets a green
suite; CI should set ``DATABASE_URL`` so they do run.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

from mkagg.load import (Baseline, Decision, RunMetrics, Thresholds,
                        validate_run)
from mkagg.models import RawOffer, RawVariant

#: Tests TRUNCATE, so they default to a SEPARATE database. Pointing them at
#: the development database would wipe it -- which is exactly what happened
#: once before this default existed. Override with MKAGG_TEST_DSN only.
DSN = os.environ.get(
    "MKAGG_TEST_DSN",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg_test")


# ===========================================================================
# Validator -- pure, no database
# ===========================================================================

def metrics(offers=100, mpn=100, price=100, size=100, requests=100, errors=0):
    return RunMetrics(offers_seen=offers, variants_seen=offers * 8,
                      requests=requests, http_errors=errors,
                      offers_with_mpn=mpn, offers_with_price=price,
                      offers_with_size=size)


HEALTHY = Baseline(runs=7, median_offers=100.0, median_sku_fill=1.0,
                   median_price_fill=1.0, median_size_fill=1.0)


class TestValidatorAbsoluteFloors:
    def test_empty_run_is_rejected(self):
        """A run that parsed nothing is a failure, not an empty catalogue.

        This is the single most important check: the cheapest way to wipe a
        site is to promote a run where the parser matched nothing.
        """
        result = validate_run(metrics(offers=0, mpn=0, price=0, size=0),
                              Baseline())
        assert result.decision is Decision.REJECTED
        assert not result.promote
        assert "parsed 0 offers" in result.reason

    def test_missing_prices_are_rejected_even_on_a_first_run(self):
        """No baseline to compare against, so the absolute floor must catch it."""
        result = validate_run(metrics(price=50), Baseline())
        assert result.decision is Decision.REJECTED
        assert "price fill" in result.reason

    def test_catastrophic_error_rate_is_rejected(self):
        result = validate_run(metrics(requests=100, errors=50), Baseline())
        assert result.decision is Decision.REJECTED
        assert "error rate" in result.reason

    def test_first_run_with_good_shape_is_promoted(self):
        """Bootstrap: no history yet, so relative checks are skipped."""
        result = validate_run(metrics(), Baseline())
        assert result.decision is Decision.OK
        assert result.promote
        assert any(c.name == "baseline" and "bootstrap" in c.note
                   for c in result.checks)


class TestValidatorRelativeChecks:
    def test_healthy_run_passes(self):
        assert validate_run(metrics(), HEALTHY).decision is Decision.OK

    def test_catalogue_shrinking_30_percent_is_rejected(self):
        """Could be a broken parser or an end-of-season clear-out.

        Either way a human should look, so it is refused rather than guessed
        at -- the cost of being wrong in the promote direction is much higher.
        """
        result = validate_run(metrics(offers=70, mpn=70, price=70, size=70),
                              HEALTHY)
        assert result.decision is Decision.REJECTED
        assert "outside" in result.reason

    def test_catalogue_growing_30_percent_is_also_rejected(self):
        result = validate_run(metrics(offers=130, mpn=130, price=130, size=130),
                              HEALTHY)
        assert result.decision is Decision.REJECTED

    def test_small_catalogue_drift_is_fine(self):
        result = validate_run(metrics(offers=92, mpn=92, price=92, size=92),
                              HEALTHY)
        assert result.decision is Decision.OK

    def test_sku_fill_collapse_is_rejected(self):
        """The earliest signal that a site changed its markup.

        Prices still parse, counts look normal, but the article codes stopped
        coming -- which silently destroys matching.
        """
        result = validate_run(metrics(mpn=40), HEALTHY)
        assert result.decision is Decision.REJECTED
        assert "sku_fill" in result.reason

    def test_size_fill_drop_is_rejected(self):
        result = validate_run(metrics(size=50), HEALTHY)
        assert result.decision is Decision.REJECTED
        assert "size_fill" in result.reason

    def test_elevated_but_tolerable_errors_are_degraded_not_rejected(self):
        result = validate_run(metrics(requests=100, errors=5), HEALTHY)
        assert result.decision is Decision.DEGRADED
        assert result.promote, "a few errors must not block the whole run"

    def test_provisional_baseline_degrades_instead_of_rejecting(self):
        """With only one or two prior runs the band is not trustworthy yet."""
        thin = Baseline(runs=1, median_offers=100.0, median_sku_fill=1.0,
                        median_price_fill=1.0, median_size_fill=1.0)
        result = validate_run(metrics(offers=60, mpn=60, price=60, size=60),
                              thin)
        assert result.decision is Decision.DEGRADED
        assert result.promote

    def test_checks_are_recorded_for_later_reading(self):
        result = validate_run(metrics(mpn=40), HEALTHY)
        names = {c.name for c in result.checks}
        assert {"offers_seen_min", "price_fill_min", "sku_fill"} <= names
        failed = [c for c in result.checks if not c.passed]
        assert failed and failed[0].limit is not None
        assert result.as_dict()["decision"] == "rejected"

    def test_thresholds_are_tunable(self):
        lenient = Thresholds(offers_delta=0.50)
        result = validate_run(metrics(offers=70, mpn=70, price=70, size=70),
                              HEALTHY, lenient)
        assert result.decision is Decision.OK


# ===========================================================================
# Staging and promotion -- needs Postgres
# ===========================================================================

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
    """Truncate transactional data, keep the V4/V5 reference seed."""
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE stage_offer, stage_variant, ingest_run, price_point,
                     click_event, verification_event, match_candidate,
                     user_price_report, product_price_summary, offer_variant,
                     merchant_offer, product_identifier, product
            RESTART IDENTITY CASCADE""")
    conn.commit()
    return conn


def offer(sku="392290-02", price=2863, merchant="sportvision", sizes=("42", "43"),
          title="Patiki Puma Caven 2.0", brand="Puma", mpn=None):
    return RawOffer(
        merchant_slug=merchant, merchant_sku=sku,
        raw_mpn=mpn if mpn is not None else sku,
        raw_title=title, raw_brand=brand,
        product_url=f"https://www.{merchant}.mk/mk/patiki/{sku}",
        currency_code="MKD",
        variants=[RawVariant(size_label=s, size_eu=Decimal(s),
                             price_minor=price, currency_code="MKD",
                             in_stock=True, merchant_variant_id=f"{sku}-{s}")
                  for s in sizes],
        extractors={"mpn": "jsonld", "price": "jsonld", "sizes": "css"})


@pytest.mark.usefixtures("clean_db")
class TestIngestAgainstPostgres:
    def test_bootstrap_creates_the_product_and_promotes(self, conn):
        from mkagg.load import ingest

        outcome = ingest(conn, "sportvision", [offer()], requests=1)
        assert outcome.decision is Decision.OK
        assert outcome.promoted
        assert outcome.promotion.products_created == 1
        assert outcome.promotion.offers_promoted == 1
        assert outcome.promotion.variants_written == 2
        assert outcome.promotion.price_points_written == 2

        with conn.cursor() as cur:
            cur.execute("SELECT canonical_name, primary_mpn FROM product")
            name, mpn = cur.fetchone()
            assert mpn == "39229002"
            assert "Puma" in name

    def test_second_store_matches_into_the_same_product(self, conn):
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer()], requests=1)
        outcome = ingest(conn, "sportreality",
                         [offer(merchant="sportreality", price=2999)],
                         requests=1)
        assert outcome.promotion.products_created == 0, \
            "the same article code must not create a second product"
        assert outcome.promotion.offers_promoted == 1

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM product")
            assert cur.fetchone()[0] == 1
            cur.execute("""SELECT min_price_minor, max_price_minor,
                                  merchant_count
                             FROM product_price_summary""")
            lo, hi, merchants = cur.fetchone()
            assert (lo, hi, merchants) == (2863, 2999, 2)

    def test_reingesting_identical_data_writes_no_history(self, conn):
        """Write-on-change, through the loader rather than the probe path."""
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            before = cur.fetchone()[0]

        ingest(conn, "sportvision", [offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            assert cur.fetchone()[0] == before, \
                "an unchanged re-crawl must not grow the history table"

    def test_price_move_writes_exactly_one_point_per_variant(self, conn):
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            before = cur.fetchone()[0]

        ingest(conn, "sportvision", [offer(price=2563)], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            assert cur.fetchone()[0] == before + 2   # two sizes moved

    def test_a_broken_run_is_rejected_and_the_catalogue_is_untouched(self, conn):
        """The whole point of the gate.

        A parser that has started returning 0 MKD must not be able to publish
        it, and the previously good prices must survive intact.
        """
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT price_minor FROM offer_variant ORDER BY id")
            good = [r[0] for r in cur.fetchall()]
        assert good == [2863, 2863]

        broken = ingest(conn, "sportvision", [offer(price=0)], requests=1)
        assert broken.decision is Decision.REJECTED
        assert not broken.promoted
        assert "price fill" in broken.reason

        with conn.cursor() as cur:
            cur.execute("SELECT price_minor FROM offer_variant ORDER BY id")
            assert [r[0] for r in cur.fetchall()] == good, \
                "a rejected run changed live prices"

    def test_rejected_run_keeps_its_staged_rows_as_evidence(self, conn):
        from mkagg.load import ingest

        outcome = ingest(conn, "sportvision", [offer(price=0)], requests=1)
        assert outcome.decision is Decision.REJECTED
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM stage_offer WHERE ingest_run_id = %s",
                        (outcome.run_id,))
            assert cur.fetchone()[0] == 1, \
                "staged rows are the evidence for diagnosing the parser"

    def test_promoted_run_clears_its_stage(self, conn):
        from mkagg.load import ingest

        outcome = ingest(conn, "sportvision", [offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM stage_offer WHERE ingest_run_id = %s",
                        (outcome.run_id,))
            assert cur.fetchone()[0] == 0

    def test_decision_detail_is_persisted(self, conn):
        from mkagg.load import ingest

        outcome = ingest(conn, "sportvision", [offer(price=0)], requests=1)
        with conn.cursor() as cur:
            cur.execute("""SELECT status, rejected_reason, decision_detail
                             FROM ingest_run WHERE id = %s""", (outcome.run_id,))
            status, reason, detail = cur.fetchone()
        assert status == "rejected"
        assert reason and "price fill" in reason
        assert detail["checks"], "every check weighed should be readable later"

    def test_offer_without_mpn_is_kept_as_unmatched(self, conn):
        """Unmatched offers are retained; they often match later."""
        from mkagg.load import ingest

        outcome = ingest(conn, "sportvision",
                         [offer(sku="internal-991", mpn="",
                                title="Nekakvi patiki bez kod", brand=None)],
                         requests=1)
        assert outcome.promoted
        assert outcome.promotion.offers_unmatched == 1
        with conn.cursor() as cur:
            cur.execute("SELECT status, product_id FROM merchant_offer")
            status, product_id = cur.fetchone()
        assert status == "unmatched" and product_id is None

    def test_full_sweep_delists_what_it_did_not_see(self, conn):
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(sku="392290-02"), offer(sku="403299-01")], requests=2)
        outcome = ingest(conn, "sportvision", [offer(sku="392290-02")],
                         requests=1, full_sweep=True,
                         thresholds=Thresholds(offers_delta=0.95))
        assert outcome.promotion.offers_delisted == 1
        with conn.cursor() as cur:
            cur.execute("""SELECT merchant_sku FROM merchant_offer
                            WHERE status = 'delisted'""")
            assert cur.fetchone()[0] == "403299-01"

    def test_partial_run_never_delists(self, conn):
        """A stock probe or one-category crawl must not wipe the catalogue."""
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(sku="392290-02"), offer(sku="403299-01")], requests=2)
        outcome = ingest(conn, "sportvision", [offer(sku="392290-02")],
                         requests=1, full_sweep=False,
                         thresholds=Thresholds(offers_delta=0.95))
        assert outcome.promotion.offers_delisted == 0
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM merchant_offer WHERE status='active'")
            assert cur.fetchone()[0] == 2

    def test_sizeer_unknown_stock_survives_the_loader(self, conn):
        """None must stay None all the way into the live table."""
        from mkagg.load import ingest

        unknown = RawOffer(
            merchant_slug="sizeer", merchant_sku="M20325", raw_mpn="M20325",
            raw_title="Adidas Stan Smith", raw_brand="Adidas",
            product_url="https://sizeer.com.mk/p?ProductID=M20325",
            variants=[RawVariant(size_label="44", size_eu=Decimal("44"),
                                 price_minor=6799, in_stock=None)],
            extractors={"mpn": "url", "price": "css", "sizes": "api"})
        ingest(conn, "sizeer", [unknown], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT in_stock, stock_qty FROM offer_variant")
            assert cur.fetchone() == (None, None)

    def test_baseline_only_counts_promoted_runs(self, conn):
        """A rejected run must not widen the band that would have caught it."""
        from mkagg.load import baseline_for, ingest, merchant_id_for

        for _ in range(3):
            ingest(conn, "sportvision", [offer()], requests=1)
        ingest(conn, "sportvision", [offer(price=0)], requests=1)  # rejected

        merchant_id = merchant_id_for(conn, "sportvision")
        baseline = baseline_for(conn, merchant_id, "catalog_parse")
        assert baseline.runs == 3
        assert baseline.median_price_fill == 1.0
