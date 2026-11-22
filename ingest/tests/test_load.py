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
from mkagg.load.promote import ensure_brand, resolve_brand
from mkagg.models import RawOffer, RawVariant
from mkagg.normalize import slugify

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
          title="Patiki Puma Caven 2.0", brand="Puma", mpn=None,
          category_path=None):
    return RawOffer(
        merchant_slug=merchant, merchant_sku=sku,
        raw_mpn=mpn if mpn is not None else sku,
        raw_title=title, raw_brand=brand,
        product_url=f"https://www.{merchant}.mk/mk/patiki/{sku}",
        currency_code="MKD", category_path=category_path,
        variants=[RawVariant(size_label=s, size_eu=Decimal(s),
                             price_minor=price, currency_code="MKD",
                             in_stock=True, merchant_variant_id=f"{sku}-{s}")
                  for s in sizes],
        extractors={"mpn": "jsonld", "price": "jsonld", "sizes": "css"})


def sold_out_offer(sku="H01551", merchant="megasport"):
    """An offer from a shop that takes the price down with the stock.

    megasport does exactly this: once every size is gone the page carries no
    price anywhere, the JSON-LD Product node has no `offers` key, and
    `data-product_variations` is an empty array. One variant, no size claim,
    no price, positively known to be unavailable.
    """
    return RawOffer(
        merchant_slug=merchant, merchant_sku=sku, raw_mpn=sku,
        raw_title="Patiki HOOPS 2.0 CMF I", raw_brand="Adidas",
        product_url=f"https://megasportonlineshop.com/p/{sku}/",
        currency_code="MKD",
        variants=[RawVariant(size_label="", price_minor=None,
                             currency_code="MKD", in_stock=False)],
        extractors={"mpn": "jsonld", "stock": "css"})


@pytest.mark.usefixtures("clean_db")
class TestResolvingABrandFromATitle:
    """Four shops put the brand only in the title, so this path matters.

    It is also where a short brand name that is also a common word did real
    damage: 450 New Era products filed under a brand called "New", 36 Sport
    Ring ones under "Sport", 27 under "Signature", and 23 fragrances under
    "Women" -- because the table was scanned in whatever order Postgres
    returned and the first match won.
    """

    def seed(self, conn, *names):
        with conn.cursor() as cur:
            out = {}
            for name in names:
                cur.execute(
                    """INSERT INTO brand (slug, name, aliases)
                            VALUES (%s, %s, %s)
                       ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                         RETURNING id""",
                    (slugify(name), name, [name.lower()]))
                out[name] = cur.fetchone()[0]
        conn.commit()
        return out

    def test_the_longest_match_wins(self, conn):
        ids = self.seed(conn, "New", "New Balance")
        assert (resolve_brand(conn, None, "New Balance 574 Patiki")
                == ids["New Balance"])

    def test_a_longer_brand_beats_a_word_inside_it(self, conn):
        """The New Era case. Both rows match the title; only one is right."""
        ids = self.seed(conn, "New", "New Era")
        assert (resolve_brand(conn, None, "New Era Cord 9twenty 174")
                == ids["New Era"])

    def test_a_real_brand_beats_a_gender_word(self, conn):
        """23 fragrances were filed under "Women" because their titles end
        "for women" and that row happened to be scanned first."""
        ids = self.seed(conn, "Women", "Moschino")
        assert (resolve_brand(conn, None,
                              "Moschino Toy 2 Eau de parfum for women")
                == ids["Moschino"])

    def test_a_gender_word_alone_resolves_to_nothing(self, conn):
        """Not to the gender word. An offer with no brand we can name is
        honestly unmatched; one branded "Women" is silently wrong, and it
        takes a product page with it."""
        self.seed(conn, "Women")
        assert resolve_brand(conn, None, "Toy 2 Eau de parfum for women") is None

    def test_a_shop_labelling_its_department_mints_no_brand(self, conn):
        """sizeer sent raw_brand "Women" on "WOMEN MELODY cropped top",
        which is how the row got into the table in the first place."""
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM brand")
            before = cur.fetchone()[0]
        assert ensure_brand(conn, "Women", "WOMEN MELODY cropped top") is None
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM brand")
            assert cur.fetchone()[0] == before, "no brand should have been minted"

    def test_a_real_brand_field_still_creates(self, conn):
        """The guard must not stop the thing this function is for: the first
        live run lost "Mont" and "Hoka" to an unseeded brand."""
        brand_id = ensure_brand(conn, "Hoka", "Hoka Clifton 9")
        assert brand_id is not None
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM brand WHERE id=%s", (brand_id,))
            assert cur.fetchone()[0] == "Hoka"


@pytest.mark.usefixtures("clean_db")
class TestSoldOutWithoutAPrice:
    """A sold-out shop should read as sold out, not as absent.

    Dropping these offers told a shopper the shop never carried the item.
    Storing 0 instead would print "0 ден.", which reads as free -- the single
    most damaging thing this site can display. NULL is the only honest answer.
    """

    def test_it_promotes_and_keeps_the_price_null(self, conn):
        from mkagg.load import ingest

        outcome = ingest(conn, "megasport", [sold_out_offer()], requests=1)
        assert outcome.decision is Decision.OK, outcome
        assert outcome.promoted
        assert outcome.promotion.offers_promoted == 1

        with conn.cursor() as cur:
            cur.execute("""
                SELECT ov.price_minor, ov.in_stock
                  FROM offer_variant ov
                  JOIN merchant_offer mo ON mo.id = ov.offer_id
                  JOIN merchant m ON m.id = mo.merchant_id
                 WHERE m.slug = 'megasport'""")
            rows = cur.fetchall()
        assert rows == [(None, False)]

    def test_no_price_point_is_written_for_it(self, conn):
        """price_point is the price history.

        "No price was published" is not an observation of a price; a row for
        it would leave a hole that every later chart has to special-case.
        """
        from mkagg.load import ingest

        outcome = ingest(conn, "megasport", [sold_out_offer()], requests=1)
        assert outcome.promotion.price_points_written == 0
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM price_point")
            assert cur.fetchone()[0] == 0

    def test_it_does_not_advertise_a_price_on_the_listing(self, conn):
        """The summary must not claim a "from" price it has not got."""
        from mkagg.load import ingest

        ingest(conn, "megasport", [sold_out_offer()], requests=1)
        with conn.cursor() as cur:
            cur.execute("""SELECT min_price_minor, max_price_minor, offer_count
                             FROM product_price_summary""")
            row = cur.fetchone()
        assert row is not None
        assert row[0] is None and row[1] is None, row

    def test_the_schema_refuses_an_unpriced_variant_that_is_not_sold_out(self, conn):
        """The guard against a parser that quietly stopped finding prices.

        That failure looks identical to a sell-out from the outside, and left
        alone it would empty the comparison tables instead of failing loudly.
        """
        import psycopg
        from mkagg.load import ingest

        ingest(conn, "megasport", [sold_out_offer()], requests=1)
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""UPDATE offer_variant SET in_stock = TRUE
                                WHERE price_minor IS NULL""")
        conn.rollback()


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

    def test_full_sweep_proposes_what_it_did_not_see(self, conn):
        """A sweep nominates; it no longer decides.

        The listing's silence is all a sweep can observe, and it does not
        distinguish "the shop removed this" from "the shop stopped linking
        it". So the offer stays active until something asks its page.
        """
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(sku="392290-02"), offer(sku="403299-01")], requests=2)
        outcome = ingest(conn, "sportvision", [offer(sku="392290-02")],
                         requests=1, full_sweep=True,
                         thresholds=Thresholds(offers_delta=0.95))

        assert outcome.promotion.offers_delisted == 0
        assert outcome.promotion.delist_unchecked == 1
        skus = [c.merchant_sku
                for c in outcome.promotion.delist_candidates]
        assert skus == ["403299-01"]
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM merchant_offer "
                        "WHERE status = 'delisted'")
            assert cur.fetchone()[0] == 0

    def test_full_sweep_delists_what_a_fetch_confirms_is_gone(self, conn):
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(sku="392290-02"), offer(sku="403299-01")], requests=2)
        outcome = ingest(conn, "sportvision", [offer(sku="392290-02")],
                         requests=1, full_sweep=True,
                         thresholds=Thresholds(offers_delta=0.95),
                         confirm_gone=lambda candidates: candidates)

        assert outcome.promotion.offers_delisted == 1
        assert outcome.promotion.delist_kept == 0
        with conn.cursor() as cur:
            cur.execute("""SELECT merchant_sku FROM merchant_offer
                            WHERE status = 'delisted'""")
            assert cur.fetchone()[0] == "403299-01"

    def test_a_candidate_whose_page_is_alive_keeps_its_offer(self, conn):
        """The Vans case: hidden from browse, still on sale.

        sportvision serves `/mk/patiki/8578840-vans-sport` at 200 with one
        size left and links it from no listing we can find. Retiring it
        would also stop it being probed -- `enqueue_due` filters on
        `status = 'active'` -- so the mistake would never be corrected.
        """
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(sku="392290-02"), offer(sku="403299-01")], requests=2)
        outcome = ingest(conn, "sportvision", [offer(sku="392290-02")],
                         requests=1, full_sweep=True,
                         thresholds=Thresholds(offers_delta=0.95),
                         confirm_gone=lambda candidates: [])

        assert outcome.promotion.offers_delisted == 0
        assert outcome.promotion.delist_kept == 1
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM merchant_offer "
                        "WHERE status = 'active'")
            assert cur.fetchone()[0] == 2

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


@pytest.mark.usefixtures("clean_db")
class TestCategoryHint:
    """A hint is context, not evidence: it fills silence, never overrides."""

    def _offer(self, title, hint, sku="HQ7261", mpn="HQ7261"):
        return RawOffer(
            merchant_slug="sportm", merchant_sku=sku, raw_mpn=mpn,
            raw_title=title, raw_brand="Adidas",
            product_url=f"https://www.sport-m.com.mk/p?ProductID={sku}",
            category_hint=hint,
            variants=[RawVariant(size_label="44", size_eu=Decimal("44"),
                                 price_minor=6799, in_stock=True)],
            extractors={"mpn": "url"})

    def _category(self, conn):
        with conn.cursor() as cur:
            cur.execute("""SELECT c.slug FROM product p
                             LEFT JOIN category c ON c.id = p.category_id""")
            return cur.fetchone()[0]

    def test_hint_fills_a_silent_title(self, conn):
        """The whole point: these titles are bare "Brand Model"."""
        from mkagg.load import ingest

        ingest(conn, "sportm",
               [self._offer("Adidas HANDBALL SPEZIAL", "footwear")],
               requests=1)
        assert self._category(conn) == "footwear"

    def test_title_beats_the_hint(self, conn):
        """A sock found through a footwear facet is still a sock."""
        from mkagg.load import ingest

        ingest(conn, "sportm",
               [self._offer("Чорапи Adidas 3P", "footwear")], requests=1)
        assert self._category(conn) == "socks"

    def test_no_hint_and_no_title_stays_null(self, conn):
        """Still refusing to guess when nothing says anything."""
        from mkagg.load import ingest

        ingest(conn, "sportm",
               [self._offer("Adidas HANDBALL SPEZIAL", None)], requests=1)
        assert self._category(conn) is None

    def test_hint_persists_through_staging(self, conn):
        """It has to survive the stage table to reach promotion at all."""
        from mkagg.load import ingest

        outcome = ingest(conn, "sportm",
                         [self._offer("Adidas HANDBALL SPEZIAL", "footwear")],
                         requests=1, keep_stage=True)
        with conn.cursor() as cur:
            cur.execute("SELECT category_hint FROM stage_offer WHERE ingest_run_id = %s",
                        (outcome.run_id,))
            assert cur.fetchone()[0] == "footwear"


def apparel_offer(sku, title, sizes, *, hint, gender, merchant="sportvision"):
    """An offer whose variants carry only a label, as apparel ones do.

    The footwear `offer()` helper sets size_eu from the label, which is right
    for shoes and impossible for "S" or "7-8г." -- the distinction this whole
    class is about.
    """
    o = RawOffer(
        merchant_slug=merchant, merchant_sku=sku, raw_mpn=sku,
        raw_title=title, raw_brand="Nike",
        product_url=f"https://www.{merchant}.mk/mk/tekstil/{sku}",
        currency_code="MKD",
        variants=[RawVariant(size_label=s, price_minor=1999,
                             currency_code="MKD", in_stock=True,
                             merchant_variant_id=f"{sku}-{s}")
                  for s in sizes],
        extractors={"mpn": "jsonld", "price": "jsonld", "sizes": "css"})
    o.category_hint = hint
    o.gender_hint = gender
    return o


class TestApparelSizesReachTheDatabase:
    """V18's size columns, filled from the facet the offer was found in.

    The parser is unit-tested in test_sizing.py; what matters here is that
    the context reaches it. `category_hint` and `gender_hint` travel from
    discovery through staging to promotion, and they are the only thing that
    can tell a dress size 38 from a shoe size 38 -- so a break anywhere along
    that path turns apparel sizes back into the silent mess V18 cleared up.
    """

    def _sizes(self, conn, merchant="sportvision"):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ov.size_label, ov.size_system::text, ov.size_alpha,
                       ov.size_height_cm, ov.size_age_min_months,
                       ov.size_age_max_months, ov.size_eu
                  FROM offer_variant ov
                  JOIN merchant_offer mo ON mo.id = ov.offer_id
                  JOIN merchant m ON m.id = mo.merchant_id
                 WHERE m.slug = %s
                 ORDER BY ov.size_label""", (merchant,))
            return cur.fetchall()

    def test_adult_letter_sizes_are_normalised(self, clean_db):
        from mkagg.load import ingest
        conn = clean_db

        offer_in = apparel_offer("APP-1", "Nike Дуксер Club", ("S", "2XL"),
                                 hint="hoodies", gender="men")
        outcome = ingest(conn, "sportvision", [offer_in], requests=1)
        assert outcome.decision is Decision.OK, outcome

        rows = self._sizes(conn)
        assert ("2XL", "alpha", "XXL", None, None, None, None) in rows
        assert ("S", "alpha", "S", None, None, None, None) in rows

    def test_kids_age_labels_become_months(self, clean_db):
        from mkagg.load import ingest
        conn = clean_db

        offer_in = apparel_offer("APP-2", "Nike Дуксер B NSW",
                                 ("7-8г.", "14-15г."),
                                 hint="hoodies", gender="kids")
        outcome = ingest(conn, "sportvision", [offer_in], requests=1)
        assert outcome.decision is Decision.OK, outcome

        rows = dict((r[0], r[1:]) for r in self._sizes(conn))
        assert rows["7-8г."][:1] == ("age",)
        assert rows["7-8г."][3:5] == (84, 96)
        assert rows["14-15г."][3:5] == (168, 180)

    def test_a_clothing_number_never_becomes_a_shoe_size(self, clean_db):
        """The defect V18 repaired, prevented at the point of writing.

        '38' on a jumper is a clothing size. Before the facet context
        reached this code it was stored as size_eu = 38 and a shopper
        filtering footwear by EU 38 got jumpers.
        """
        from mkagg.load import ingest
        conn = clean_db

        offer_in = apparel_offer("APP-3", "Nike Маица", ("38", "40"),
                                 hint="tshirts", gender="women")
        outcome = ingest(conn, "sportvision", [offer_in], requests=1)
        assert outcome.decision is Decision.OK, outcome

        for label, system, _alpha, _h, _lo, _hi, size_eu in self._sizes(conn):
            assert system == "numeric", label
            assert size_eu is None, label

    def test_the_same_number_on_footwear_is_still_a_shoe_size(self, clean_db):
        """The other half of the rule, so the fix cannot be a blanket null."""
        from mkagg.load import ingest
        conn = clean_db

        offer_in = offer(sku="SHOE-1", title="Nike Патики Pegasus",
                         sizes=("38", "40"))
        offer_in.category_hint = "sneakers"
        offer_in.gender_hint = "women"
        outcome = ingest(conn, "sportvision", [offer_in], requests=1)
        assert outcome.decision is Decision.OK, outcome

        rows = self._sizes(conn)
        assert all(r[1] == "eu_shoe" for r in rows), rows
        assert all(r[6] is not None for r in rows), rows


@pytest.mark.usefixtures("clean_db")
class TestThePageShelfIsStored:
    """`merchant_category_path` from the product page, not just the walk.

    The facet walk was the column's only writer, so a product reachable
    only through a department umbrella could be filed no more precisely
    than "clothing" -- while its own Спецификации table named the shelf.
    These check the storing half of that fix.
    """

    def test_the_shelf_lands_on_the_offer(self, conn):
        from mkagg.load import ingest

        ingest(conn, "sportvision",
               [offer(category_path="Градник")], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT merchant_category_path FROM merchant_offer")
            assert cur.fetchone()[0] == "Градник"

    def test_a_silent_adapter_never_wipes_the_walk(self, conn):
        """The COALESCE, and why it is not decoration.

        Four of six shops state no shelf on the page. If their NULL were
        written as an assignment, every sweep would erase what the facet
        walk had established -- and the walk only runs when asked.
        """
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer(category_path="Маици")],
               requests=1)
        with conn.cursor() as cur:
            cur.execute("""UPDATE merchant_offer
                              SET merchant_category_path = 'Дресови'""")
        ingest(conn, "sportvision", [offer(category_path=None)], requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT merchant_category_path FROM merchant_offer")
            assert cur.fetchone()[0] == "Дресови"

    def test_a_later_sweep_follows_the_shop(self, conn):
        """A shop that re-shelves a product is believed, not argued with."""
        from mkagg.load import ingest

        ingest(conn, "sportvision", [offer(category_path="Маици")],
               requests=1)
        ingest(conn, "sportvision", [offer(category_path="Дресови-фудбал")],
               requests=1)
        with conn.cursor() as cur:
            cur.execute("SELECT merchant_category_path FROM merchant_offer")
            assert cur.fetchone()[0] == "Дресови-фудбал"
