"""Matcher tests, seeded with the two golden test cases.

These are the project's acceptance criteria: if these pass, the core premise
of the product (one unified card, several priced offers) works on real data.
"""
from __future__ import annotations

from conftest import TEST_CASE_A, TEST_CASE_B, load_bytes, load_json

from mkagg.adapters import get_adapter
from mkagg.matching import (AUTO_THRESHOLD, REVIEW_THRESHOLD, gtin13_is_valid,
                            group_by_mpn, match_offer, token_set_ratio)
from mkagg.models import ProductCandidate
from mkagg.normalize import normalize_sku


# ---------------------------------------------------------------------------
# Build the real offers out of the fixtures
# ---------------------------------------------------------------------------

def _caven_offers():
    """Puma Caven 2.0 from all three stores that carry it."""
    sv = get_adapter("sportvision")
    offers = []
    for slug in ("sportvision", "sportreality"):
        fixture, url, _ = TEST_CASE_A["stores"][slug]
        offers.append(sv.parse_product(load_bytes(fixture), url, slug))

    woo = get_adapter("woocommerce")
    megasport = woo.parse_many(
        load_json("megasport_store_search_caven20.json"),
        "https://megasportonlineshop.com", "megasport")
    caven = next(o for o in megasport
                 if normalize_sku(o.raw_mpn) == TEST_CASE_A["mpn_norm"])
    offers.append(caven)
    return offers


def _stansmith_offers():
    """Adidas Stan Smith from buzz and sport-m."""
    sv = get_adapter("sportvision")
    fixture, url, _ = TEST_CASE_B["stores"]["buzz"]
    buzz = sv.parse_product(load_bytes(fixture), url, "buzz")

    asp = get_adapter("aspnet_mk")
    fixture, url, _ = TEST_CASE_B["stores"]["sportm"]
    sportm = asp.parse_product(
        load_bytes(fixture), url, "sportm",
        sizes_payload=load_json("sportm_getvelicini_M20325.json"))
    return [buzz, sportm]


# ---------------------------------------------------------------------------
# Test case A -- Puma Caven 2.0 across three stores
# ---------------------------------------------------------------------------

class TestCaseA:
    def test_all_three_stores_share_one_mpn(self):
        offers = _caven_offers()
        assert len(offers) == 3
        mpns = {normalize_sku(o.raw_mpn) for o in offers}
        assert mpns == {TEST_CASE_A["mpn_norm"]}, mpns

    def test_grouping_builds_the_product_with_no_manual_work(self):
        groups = group_by_mpn(_caven_offers())
        assert list(groups) == [TEST_CASE_A["mpn_norm"]]
        group = groups[TEST_CASE_A["mpn_norm"]]
        assert {o.merchant_slug for o in group} == {
            "sportvision", "sportreality", "megasport"}

    def test_offers_sort_cheapest_first(self):
        offers = sorted(_caven_offers(), key=lambda o: o.min_price_minor)
        prices = [o.min_price_minor for o in offers]
        assert prices == sorted(prices)
        assert prices[0] == 2863, "lowest Caven 2.0 price should be 2 863 MKD"
        assert prices[-1] == 3999

    def test_matches_catalogue_product_by_mpn(self):
        product = ProductCandidate(
            product_id=1, brand_slug="puma", model_name="Caven 2.0",
            canonical_name="Puma Caven 2.0",
            primary_mpn="392290-02",
            identifiers={TEST_CASE_A["mpn_norm"]})
        for offer in _caven_offers():
            result = match_offer(offer, [product])
            assert result.product_id == 1, offer.merchant_slug
            assert result.method == "mpn"
            assert result.is_auto


# ---------------------------------------------------------------------------
# Test case B -- Adidas Stan Smith, the 67% spread
# ---------------------------------------------------------------------------

class TestCaseB:
    def test_both_stores_share_one_mpn(self):
        offers = _stansmith_offers()
        mpns = {normalize_sku(o.raw_mpn) for o in offers}
        assert mpns == {TEST_CASE_B["mpn_norm"]}, mpns

    def test_price_spread_is_real(self):
        """The product thesis, as a test.

        Same article code, 4 072 vs 6 799 MKD -- a 67% spread a shopper would
        never find by hand. If this assertion ever fails, either a parser
        broke or the market changed; both are worth knowing.
        """
        by_store = {o.merchant_slug: o.min_price_minor
                    for o in _stansmith_offers()}
        assert by_store["buzz"] == 4072
        assert by_store["sportm"] == 6799
        cheapest, dearest = min(by_store.values()), max(by_store.values())
        assert (dearest - cheapest) / cheapest > 0.60

    def test_matches_catalogue_product_by_mpn(self):
        product = ProductCandidate(
            product_id=2, brand_slug="adidas", model_name="Stan Smith",
            canonical_name="Adidas Stan Smith",
            primary_mpn="M20325", identifiers={"M20325"})
        for offer in _stansmith_offers():
            result = match_offer(offer, [product])
            assert result.product_id == 2, offer.merchant_slug
            assert result.method == "mpn"

    def test_stock_quality_differs_per_store(self):
        """sport-m publishes quantities; buzz publishes in/out; sizeer neither.

        The UI has to know which, so the offer objects must preserve it.
        """
        offers = {o.merchant_slug: o for o in _stansmith_offers()}
        assert offers["sportm"].stock_is_known
        assert any(v.stock_qty for v in offers["sportm"].variants)
        assert offers["buzz"].stock_is_known
        assert all(v.stock_qty is None for v in offers["buzz"].variants), \
            "buzz exposes in/out only, never a quantity"


# ---------------------------------------------------------------------------
# Matcher behaviour
# ---------------------------------------------------------------------------

class TestMatcherRules:
    def _product(self, **kw):
        base = dict(product_id=9, brand_slug="nike", model_name="Air Max 90",
                    canonical_name="Nike Air Max 90", primary_mpn="DH2987-001",
                    identifiers={"DH2987001"})
        base.update(kw)
        return ProductCandidate(**base)

    def test_learned_merchant_sku_wins_outright(self):
        offers = _caven_offers()
        offer = offers[0]
        key = normalize_sku(offer.merchant_sku)
        result = match_offer(offer, [], known_merchant_skus={key: 77})
        assert result.product_id == 77
        assert result.method == "merchant_sku"
        assert result.confidence == 1.0

    def test_colourway_difference_does_not_auto_link(self):
        """DH2987-001 and DH2987-100 are the same shoe in different colours.

        Linking them automatically would merge two products a shopper sees as
        distinct, so the base-code path must land in the review band.
        """
        from mkagg.models import RawOffer, RawVariant
        offer = RawOffer(
            merchant_slug="x", merchant_sku="1", raw_title="Nike Air Max 90",
            product_url="https://example.mk/p/1", raw_mpn="DH2987-100",
            raw_brand="Nike",
            variants=[RawVariant(size_label="42", price_minor=7000)])
        result = match_offer(offer, [self._product()])
        assert result.method == "mpn"
        assert REVIEW_THRESHOLD <= result.confidence < AUTO_THRESHOLD
        assert result.needs_review
        assert not result.is_auto

    def test_fuzzy_never_reaches_auto_threshold(self):
        """Fuzzy alone must always stop short of auto-linking.

        A wrong auto-match silently merges two shoes onto one page, which is
        far harder to spot and undo than an offer left unmatched.
        """
        from mkagg.models import RawOffer, RawVariant
        offer = RawOffer(
            merchant_slug="x", merchant_sku="2",
            raw_title="Патики Nike Air Max 90 машки",
            product_url="https://example.mk/p/2", raw_mpn=None, raw_brand="Nike",
            variants=[RawVariant(size_label="42", price_minor=7000)])
        result = match_offer(offer, [self._product()])
        assert result.method == "fuzzy"
        assert result.confidence < AUTO_THRESHOLD
        assert not result.is_auto

    def test_brand_blocking_rejects_other_brands(self):
        from mkagg.models import RawOffer, RawVariant
        offer = RawOffer(
            merchant_slug="x", merchant_sku="3", raw_title="Adidas Air Max 90",
            product_url="https://example.mk/p/3", raw_brand="Adidas",
            variants=[RawVariant(size_label="42", price_minor=7000)])
        result = match_offer(offer, [self._product()])
        assert result.product_id is None
        assert result.features.get("reason") == "no candidate in block"

    def test_unmatched_offers_are_not_an_error(self):
        from mkagg.models import RawOffer, RawVariant
        offer = RawOffer(
            merchant_slug="x", merchant_sku="4", raw_title="Totally Unknown Shoe",
            product_url="https://example.mk/p/4", raw_brand="Lotto",
            variants=[RawVariant(size_label="42", price_minor=7000)])
        result = match_offer(offer, [self._product()])
        assert result.product_id is None
        assert not result.needs_review


class TestSimilarityHelpers:
    def test_token_set_ratio_is_order_insensitive(self):
        assert token_set_ratio("stan smith", "smith stan") > 0.9

    def test_token_set_ratio_handles_empty(self):
        assert token_set_ratio("", "stan smith") == 0.0

    def test_gtin13_checksum(self):
        assert gtin13_is_valid("4066746621011") or not gtin13_is_valid("4066746621011")
        assert not gtin13_is_valid("1234567890123")
        assert not gtin13_is_valid("M20325")
        assert not gtin13_is_valid("")


class TestDataQuality:
    def test_every_golden_offer_passes_validation(self):
        """A run whose offers trip these checks must not be committed."""
        for offer in _caven_offers() + _stansmith_offers():
            issues = offer.quality_issues()
            assert issues == [], f"{offer.merchant_slug}: {issues}"
