"""Adapter tests, run against golden files captured from the live stores.

No network, no database. If one of these fails after a store redesign, the
failure names the exact field that moved.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import TEST_CASE_A, TEST_CASE_B, load_bytes, load_json

from mkagg.adapters import get_adapter
from mkagg.adapters.aspnet_mk import parse_sizes, product_id_from_url, sizes_request
from mkagg.adapters.magento import catalog_query
from mkagg.normalize import normalize_sku


# ---------------------------------------------------------------------------
# Adapter 1: Sport Vision group (3 merchants)
# ---------------------------------------------------------------------------

class TestSportVisionAdapter:
    def test_sportvision_caven20(self):
        adapter = get_adapter("sportvision")
        fixture, url, price = TEST_CASE_A["stores"]["sportvision"]
        offer = adapter.parse_product(load_bytes(fixture), url, "sportvision")

        assert offer is not None
        assert normalize_sku(offer.raw_mpn) == TEST_CASE_A["mpn_norm"]
        assert offer.merchant_sku == "8550245"          # JSON-LD productID
        assert offer.raw_brand == "Puma"
        assert offer.min_price_minor == price
        assert offer.extractors["mpn"] == "jsonld"

    def test_sportreality_caven20_same_mpn(self):
        adapter = get_adapter("sportvision")
        fixture, url, price = TEST_CASE_A["stores"]["sportreality"]
        offer = adapter.parse_product(load_bytes(fixture), url, "sportreality")

        assert offer is not None
        assert normalize_sku(offer.raw_mpn) == TEST_CASE_A["mpn_norm"]
        assert offer.merchant_sku == "51378"            # different store id
        assert offer.min_price_minor == price

    def test_buzz_survives_broken_jsonld(self):
        """buzzsneakers.mk leaks HTML comments into its JSON-LD.

        A strict parser gets nothing here; the rescue path must still recover
        the manufacturer code, or we lose a whole store.
        """
        adapter = get_adapter("sportvision")
        fixture, url, price = TEST_CASE_B["stores"]["buzz"]
        offer = adapter.parse_product(load_bytes(fixture), url, "buzz")

        assert offer is not None
        assert normalize_sku(offer.raw_mpn) == TEST_CASE_B["mpn_norm"]
        assert offer.extractors["mpn"] == "regex"       # rescue path, as expected
        assert offer.min_price_minor == price
        assert offer.merchant_sku == "2011"             # from the URL

    def test_per_size_stock_is_decoded(self):
        adapter = get_adapter("sportvision")
        fixture, url, _ = TEST_CASE_B["stores"]["buzz"]
        offer = adapter.parse_product(load_bytes(fixture), url, "buzz")

        assert len(offer.variants) >= 5
        # Every size carries a stable per-size variant id we can probe alone.
        assert all(v.merchant_variant_id for v in offer.variants)
        # Stock is a real signal on this platform: a mix of in and out.
        assert offer.stock_is_known
        # buzz uses fractional EU labels; they must parse to distinct numbers.
        labels = [v.size_label for v in offer.variants]
        assert any("/" in label for label in labels), labels
        sizes = [v.size_eu for v in offer.variants if v.size_eu is not None]
        assert len(sizes) == len(set(sizes)), "duplicate normalised sizes"

    def test_duplicate_size_labels_collapse(self):
        """sportvision.mk lists the same physical size as "35,5" and "35.5"."""
        adapter = get_adapter("sportvision")
        fixture, url, _ = TEST_CASE_A["stores"]["sportvision"]
        offer = adapter.parse_product(load_bytes(fixture), url, "sportvision")
        sizes = [v.size_eu for v in offer.variants if v.size_eu is not None]
        assert len(sizes) == len(set(sizes)), sizes


# ---------------------------------------------------------------------------
# Adapter 2: Magento (dsport.mk)
# ---------------------------------------------------------------------------

class TestMagentoAdapter:
    def test_parses_graphql_catalogue(self):
        adapter = get_adapter("magento")
        payload = load_json("dsport_graphql_terrex.json")
        offers = adapter.parse_many(payload, "https://www.dsport.mk", "dsport")

        assert offers, "no offers parsed from the GraphQL fixture"
        offer = offers[0]
        assert offer.raw_mpn, "Magento sku is the manufacturer code on dsport"
        assert offer.merchant_sku == offer.raw_mpn
        assert offer.min_price_minor and offer.min_price_minor > 0
        assert offer.currency_code == "MKD"
        assert offer.extractors["sizes"] == "graphql"
        assert offer.product_url.startswith("https://www.dsport.mk/")

    def test_variants_carry_stock(self):
        adapter = get_adapter("magento")
        offers = adapter.parse_many(
            load_json("dsport_graphql_terrex.json"),
            "https://www.dsport.mk", "dsport")
        with_sizes = [o for o in offers if len(o.variants) > 1]
        assert with_sizes, "expected at least one configurable product"
        offer = with_sizes[0]
        assert all(v.in_stock is not None for v in offer.variants)
        assert all(v.merchant_variant_id for v in offer.variants)

    def test_catalog_query_prefers_category_over_search(self):
        q = catalog_query(category_id="3", page=2, page_size=50)["query"]
        assert 'category_id:{eq:"3"}' in q
        assert "currentPage:2" in q
        assert "search:" not in q


# ---------------------------------------------------------------------------
# Adapter 3: WooCommerce (megasport)
# ---------------------------------------------------------------------------

class TestWooCommerceAdapter:
    def test_caven20_matches_test_case_a(self):
        adapter = get_adapter("woocommerce")
        payload = load_json("megasport_store_search_caven20.json")
        offers = adapter.parse_many(
            payload, "https://megasportonlineshop.com", "megasport")

        assert offers
        caven = next(
            (o for o in offers
             if normalize_sku(o.raw_mpn) == TEST_CASE_A["mpn_norm"]), None)
        assert caven is not None, (
            "Caven 2.0 SKU 392290-02 not found; got "
            f"{[o.raw_mpn for o in offers]}")
        assert caven.min_price_minor == TEST_CASE_A["stores"]["megasport"][2]
        assert caven.currency_code == "MKD"

    def test_price_is_whole_denars_not_cents(self):
        """currency_minor_unit is 0 on this store -- never assume 100."""
        adapter = get_adapter("woocommerce")
        offers = adapter.parse_many(
            load_json("megasport_store_search_caven20.json"),
            "https://megasportonlineshop.com", "megasport")
        for offer in offers:
            if offer.min_price_minor:
                # A sneaker is hundreds or thousands of denars, never 10^5+.
                assert 100 < offer.min_price_minor < 100_000, offer.min_price_minor

    def test_size_spellings_reconcile(self):
        """terms say "37.5", variations say "37-5"; both must normalise equal.

        If they did not, every half size would read as sold out.
        """
        adapter = get_adapter("woocommerce")
        offers = adapter.parse_many(
            load_json("megasport_store_search_caven20.json"),
            "https://megasportonlineshop.com", "megasport")
        sized = [o for o in offers if len(o.variants) > 1]
        if sized:
            offer = sized[0]
            assert any(v.in_stock is not None for v in offer.variants), (
                "no size resolved to a stock state -- the "
                "'37.5' vs '37-5' reconciliation is broken")


# ---------------------------------------------------------------------------
# Adapter 4: ASP.NET MVC (sport-m + sizeer)
# ---------------------------------------------------------------------------

class TestAspNetMkAdapter:
    def test_product_id_from_url(self):
        url = TEST_CASE_B["stores"]["sportm"][1]
        assert product_id_from_url(url) == "M20325"
        assert product_id_from_url(
            "https://sizeer.com.mk/ProductCatalog/ProductDetails"
            "?ProductID=M20325&Grupa=01&PodGrupa=503") == "M20325"
        assert product_id_from_url("https://example.mk/nothing") is None

    def test_sportm_price_and_mpn(self):
        adapter = get_adapter("aspnet_mk")
        fixture, url, price = TEST_CASE_B["stores"]["sportm"]
        offer = adapter.parse_product(
            load_bytes(fixture), url, "sportm",
            sizes_payload=load_json("sportm_getvelicini_M20325.json"))

        assert offer is not None
        assert offer.raw_mpn == "M20325"
        assert offer.min_price_minor == price
        assert offer.extractors["mpn"] == "url"

    def test_sportm_reports_real_quantities(self):
        offer_sizes = parse_sizes(
            load_json("sportm_getvelicini_M20325.json"),
            price_minor=6799, publishes_stock=True)
        assert len(offer_sizes) == 8
        assert all(v.in_stock is True for v in offer_sizes)
        assert all(isinstance(v.stock_qty, int) and v.stock_qty > 0
                   for v in offer_sizes)
        # EU labels arrive with Unicode fractions and must parse distinctly.
        eu = [v.size_eu for v in offer_sizes if v.size_eu is not None]
        assert len(eu) == len(set(eu)) == 8, eu

    def test_sizeer_stock_stays_unknown(self):
        """sizeer returns Zaliha = null for every size.

        Unknown must never become False -- rendering "sold out" for stock we
        simply cannot see would be as wrong as claiming it is in stock.
        """
        offer_sizes = parse_sizes(
            load_json("sizeer_getvelicini_M20325.json"),
            price_minor=6799, publishes_stock=False)
        assert offer_sizes
        assert all(v.in_stock is None for v in offer_sizes)
        assert all(v.stock_qty is None for v in offer_sizes)
        # Sizes themselves are still usable, which is the point.
        assert all(v.size_eu is not None for v in offer_sizes)

    def test_sizes_request_is_a_post(self):
        url, body, headers = sizes_request("https://www.sport-m.com.mk", "M20325")
        assert url.endswith("/ProductCatalog/GetVelicini/")
        assert body == b"ProductID=M20325"
        assert headers["X-Requested-With"] == "XMLHttpRequest"
        assert "Referer" in headers


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------



class TestSizeBlockBoundary:
    """Regression guard for the size-container boundary.

    The first implementation read a fixed 20 KB window after the size-tabs
    marker. That is wrong in both directions and the two failures look
    identical from the outside:

    * **truncation** -- sportvision's own size run spans ~20.6 KB, so 5 of its
      23 size elements were silently dropped;
    * **bleed** -- reading further picks up the recommendation tiles lower on
      the page, which carry size widgets of their own (160+ combids on
      sportreality, 249 on buzz).

    Bounding on the size list's own ``</ul>`` fixes both. These exact counts
    lock that boundary: a change in either direction breaks a number here.
    """

    EXPECTED = {
        "sportvision": ("sportvision_caven20.html", 20, "35,5", "48.5"),
        "sportreality": ("sportreality_caven20.html", 20, "35.5", "48.5"),
        "buzz": ("buzz_stansmith.html", 30, "35.5", "57"),
    }

    @pytest.mark.parametrize("slug", sorted(EXPECTED))
    def test_full_size_run_no_truncation_no_bleed(self, slug):
        fixture, count, smallest, largest = self.EXPECTED[slug]
        adapter = get_adapter("sportvision")
        url = f"https://www.{slug}.mk/mk/patiki/1-x"
        offer = adapter.parse_product(load_bytes(fixture), url, slug)

        assert len(offer.variants) == count, (
            f"{slug}: expected {count} sizes, got {len(offer.variants)} -- "
            "the size-list boundary moved (truncation or bleed)")
        labels = {v.size_label for v in offer.variants}
        assert smallest in labels, f"{slug}: smallest size missing -> truncated"
        assert largest in labels, f"{slug}: largest size missing -> truncated"

    def test_sizes_are_one_contiguous_list(self):
        """Every size must come from the product's own list.

        Bleed shows up as an implausible count, since each recommendation tile
        contributes a whole size run of its own.
        """
        adapter = get_adapter("sportvision")
        offer = adapter.parse_product(
            load_bytes("sportreality_caven20.html"),
            "https://www.sportreality.mk/mk/patiki/51378-puma-caven-2-0",
            "sportreality")
        # One shoe never has 40+ sizes; the raw page holds 160 combids.
        assert len(offer.variants) < 40


# ---------------------------------------------------------------------------
# The robots-permitted HTML routes
# ---------------------------------------------------------------------------

class TestMagentoHtmlAdapter:
    """dsport.mk via its product page, because /graphql is disallowed."""

    URL = ("https://www.dsport.mk/muskarci/obuca/cizme/"
           "adidas-terrex-skychaser-ax5-mid-gtx-za-mazhi-kj8942")

    def _offer(self):
        return get_adapter("magento_html").parse_product(
            load_bytes("dsport_product_kj8942.html"), self.URL, "dsport")

    def test_extracts_mpn_title_and_price(self):
        offer = self._offer()
        assert offer is not None
        assert offer.raw_mpn == "KJ8942"
        assert offer.raw_brand == "Adidas"
        assert "TERREX" in offer.raw_title.upper()
        assert offer.min_price_minor == 8599

    def test_merchant_sku_matches_the_api_adapter(self):
        """Switching routes must update the offer, not duplicate it.

        The GraphQL adapter uses the Magento sku as merchant_sku, so the HTML
        adapter has to agree or V7 would fork every dsport offer in two.
        """
        offer = self._offer()
        assert offer.merchant_sku == offer.raw_mpn == "KJ8942"

    def test_reads_the_full_size_matrix_from_spconfig(self):
        offer = self._offer()
        assert len(offer.variants) == 12
        assert all(v.merchant_variant_id for v in offer.variants)
        assert all(v.price_minor == 8599 for v in offer.variants)

    def test_dash_fractions_normalise(self):
        """dsport writes "41-1/3" where buzz writes "44 2/3"."""
        offer = self._offer()
        labels = {v.size_label for v in offer.variants}
        assert "41-1/3" in labels
        by_label = {v.size_label: v.size_eu for v in offer.variants}
        assert by_label["41-1/3"] == Decimal("41.333")
        assert by_label["42-2/3"] == Decimal("42.667")
        assert by_label["40"] == Decimal("40")

    def test_sizes_are_distinct(self):
        offer = self._offer()
        sizes = [v.size_eu for v in offer.variants if v.size_eu is not None]
        assert len(sizes) == len(set(sizes)) == 12

    def test_listed_options_are_in_stock(self):
        """Magento omits non-purchasable children.

        Verified against this store's own GraphQL capture, where every
        returned variant was IN_STOCK: both routes list only buyable sizes.
        """
        offer = self._offer()
        assert all(v.in_stock is True for v in offer.variants)

    def test_passes_quality_validation(self):
        assert self._offer().quality_issues() == []


class TestWooCommerceHtmlAdapter:
    """megasport via its product page, because /wp-json/ is disallowed."""

    URL = "https://megasportonlineshop.com/p/patiki-puma-caven-2-0-2/"

    def _offer(self):
        return get_adapter("woocommerce_html").parse_product(
            load_bytes("megasport_product_caven20.html"), self.URL, "megasport")

    def test_finds_the_product_node_inside_graph(self):
        """The Product node is nested in JSON-LD @graph, not at the top level."""
        offer = self._offer()
        assert offer is not None
        assert normalize_sku(offer.raw_mpn) == TEST_CASE_A["mpn_norm"]
        assert offer.raw_brand
        assert "Caven" in offer.raw_title

    def test_merchant_sku_matches_the_store_api(self):
        offer = self._offer()
        assert offer.merchant_sku == "31527", \
            "must equal the Store API's product id or V7 duplicates the offer"

    def test_per_size_prices_and_quantities(self):
        offer = self._offer()
        assert len(offer.variants) == 7
        assert all(v.in_stock is True for v in offer.variants)
        assert all(isinstance(v.stock_qty, int) and v.stock_qty > 0
                   for v in offer.variants)
        assert all(v.merchant_variant_id for v in offer.variants)

    def test_page_price_beats_the_api_parent_price(self):
        """The finding that makes this route preferable even with permission.

        The Store API reported prices.price = 3999 for this product while every
        variation on the page is 3199.2 -- the parent price missed a 20%
        reduction that applies to all sizes.
        """
        offer = self._offer()
        assert offer.min_price_minor == 3199
        api_parent = TEST_CASE_A["stores"]["megasport"][2]   # 3999
        assert offer.min_price_minor < api_parent

    def test_dash_decimal_sizes_normalise(self):
        """Woo writes "44-5" for 44.5 in variation attributes."""
        offer = self._offer()
        by_label = {v.size_label: v.size_eu for v in offer.variants}
        assert "44-5" in by_label
        assert by_label["44-5"] == Decimal("44.5")

    def test_passes_quality_validation(self):
        assert self._offer().quality_issues() == []


def test_six_adapters_cover_seven_stores_on_two_routes():
    from mkagg.adapters import all_adapters
    assert set(all_adapters()) == {
        "sportvision", "aspnet_mk",                  # crawlable as found
        "magento", "woocommerce",                    # API: need permission
        "magento_html", "woocommerce_html",          # robots-permitted route
    }


class TestProductTitleSource:
    """The title must come from the page, never from a bare JSON "name".

    buzzsneakers.mk ships broken JSON-LD, and the first `"name"` in that
    document belongs to the Organization node. Rescuing it produced the
    catalogue product "Adidas buzz online shop" -- which every test still
    passed, because they only checked the SKU and the price.
    """

    def test_buzz_title_is_the_product_not_the_site(self):
        adapter = get_adapter("sportvision")
        fixture, url, _ = TEST_CASE_B["stores"]["buzz"]
        offer = adapter.parse_product(load_bytes(fixture), url, "buzz")
        title = offer.raw_title.lower()
        assert "stan smith" in title
        assert "online shop" not in title
        assert "buzz" not in title
        assert offer.extractors["title"] == "css"

    def test_jsonld_title_still_wins_where_it_parses(self):
        adapter = get_adapter("sportvision")
        fixture, url, _ = TEST_CASE_A["stores"]["sportvision"]
        offer = adapter.parse_product(load_bytes(fixture), url, "sportvision")
        assert offer.raw_title == "Puma Caven 2.0"
        assert offer.extractors["title"] == "jsonld"
