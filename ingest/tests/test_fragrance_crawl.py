"""Wiring the fragrance vertical: discovery, run kind, and the volume rail.

Four verticals now share one driver, one worker and one loader, and the
differences between them are all configuration. These tests pin the
configuration, because every one of the facts below was learned by running
the crawl and watching it get something wrong.
"""
from __future__ import annotations

import json

import pytest
from conftest import load_json

from mkagg.adapters import get_adapter
from mkagg.discover import (FRAGRANCE_FACET_PLANS, PRODUCT_URL_PATTERNS,
                            as_facets, extract_links, facet_plan, store_api_url,
                            sweep_plan)
from mkagg.load.run import FRAGRANCE_KIND, run_kind_for
from mkagg.models import RawOffer
from mkagg.taxonomy import FRAGRANCE_SLUGS


def offer(category_hint=None):
    return RawOffer(merchant_slug="eelixir", merchant_sku="1",
                    raw_title="t", product_url="u",
                    category_hint=category_hint)


class TestFindingTheProducts:
    def test_a_json_listing_yields_product_urls(self):
        """The Store API states each product's page in `permalink`, with the
        slashes escaped. Nothing else in this codebase reads a JSON listing,
        so without this the API shop has no discovery at all."""
        body = json.dumps([
            {"id": 1, "permalink": "https://e-elixir.mk/shop/valentino-donna-edp/"},
            {"id": 2, "permalink": "https://e-elixir.mk/kategorija/mirisi/"},
        ]).replace("/", r"\/")
        found = extract_links(body, PRODUCT_URL_PATTERNS["woocommerce"],
                              "https://e-elixir.mk")
        assert found == ["https://e-elixir.mk/shop/valentino-donna-edp/"]

    def test_an_html_listing_still_works(self):
        """The same function serves both; the JSON branch must not cost the
        four shops that are read as HTML anything."""
        html = '<a href="/p/patiki-puma-caven-2-0-2/">Caven</a>'
        assert extract_links(html, PRODUCT_URL_PATTERNS["woocommerce_html"],
                             "https://megasportonlineshop.com") == [
            "https://megasportonlineshop.com/p/patiki-puma-caven-2-0-2/"]

    def test_the_fetched_url_is_not_the_stored_one(self):
        """Fetching the shop page would hand HTML to a JSON parser.

        The product is addressed by its page -- that is what a shopper
        clicks -- and read through the API. The adapter closes the loop by
        reading `permalink` back out, so the offer keeps the clickable URL.
        """
        assert (store_api_url("https://e-elixir.mk/shop/valentino-donna-edp/")
                == "https://e-elixir.mk/wp-json/wc/store/v1/"
                   "products?slug=valentino-donna-edp")

    def test_both_gender_departments_are_walked(self):
        """661 women's plus 516 men's against a root of 987.

        The 190 counted twice are the unisex ones, and membership of both
        departments is the only evidence any of these shops publishes for
        unisex. Walking the root instead would be cheaper and would lose it.
        """
        plan = sweep_plan("eelixir", "woocommerce", vertical="fragrance")
        assert plan is not None
        facets = as_facets(plan.categories)
        assert {f.gender for f in facets} == {"men", "women"}
        assert all(f.category == "perfume" for f in facets)

    def test_the_plan_walks_until_a_page_comes_back_empty(self):
        """The Store API puts its total in a header the driver never sees,
        so an advertised page count is not available to believe."""
        plan = FRAGRANCE_FACET_PLANS["eelixir"]
        assert plan.walk_until_empty
        assert plan.page_suffix == "&page={page}"

    def test_a_sweep_and_a_labelling_walk_read_the_same_plan(self):
        assert (sweep_plan("eelixir", "woocommerce", vertical="fragrance")
                is facet_plan("eelixir", vertical="fragrance"))

    def test_another_vertical_does_not_reach_this_plan(self):
        assert sweep_plan("eelixir", "woocommerce", vertical="footwear") is None
        assert sweep_plan("megasport", "woocommerce_html",
                          vertical="fragrance") is None


class TestWhichRunItBelongsTo:
    def test_a_fragrance_opens_its_own_run(self):
        """e-elixir sells nothing but perfume, so its fragrance run is its
        whole catalogue -- roughly 723 bottles. Judged against a footwear
        median built from shops selling thousands of shoes, the gate would
        reject it on the count alone."""
        assert run_kind_for(offer("perfume")) == FRAGRANCE_KIND
        assert run_kind_for(offer("fragrances")) == FRAGRANCE_KIND

    @pytest.mark.parametrize("hint,expected", [
        ("sneakers", "catalog_parse"),
        ("tshirts", "apparel_parse"),
        ("socks", "accessory_parse"),
        (None, "catalog_parse"),
    ])
    def test_the_other_verticals_are_unmoved(self, hint, expected):
        assert run_kind_for(offer(hint)) == expected

    def test_the_run_kind_matches_the_taxonomy(self):
        """A slug in one and not the other files a whole vertical wrong."""
        assert {"fragrances", "perfume"} == set(FRAGRANCE_SLUGS)


class TestTheVolumeRail:
    """Where a fragrance's sizes actually come from."""

    def test_a_simple_product_takes_its_volume_from_its_name(self):
        """WooCommerce calls a one-size product `simple`: no variation to
        carry a volume, so the shop writes it into the title. 214 of
        e-elixir's 279 simple products state one."""
        adapter = get_adapter("woocommerce")
        payload = {
            "id": 1, "type": "simple", "name": "Annayake POUR ELLE "
                                               "Eau de Parfum 100ml",
            "permalink": "https://e-elixir.mk/shop/x/",
            "prices": {"price": "583000", "regular_price": "583000",
                       "currency_code": "MKD", "currency_minor_unit": 2},
            "categories": [{"name": "Женски Eau de parfum"}],
        }
        got = adapter.parse_product(payload, "u", "eelixir",
                                    vertical="fragrance")
        assert [(v.size_label, v.price_minor) for v in got.variants] == [
            ("100ml", 5830)]

    def test_a_simple_products_attribute_is_not_its_volumes(self):
        """The regression the first crawl produced.

        A simple Annayake 100ml still carries "Достапни големини: 15ml,
        30ml, 60ml" -- the sizes the *line* comes in, not the ones this
        listing sells. Read as this product's volumes it looks like a
        three-volume bottle, and a three-volume bottle reports no volume at
        all. Eight Annayake products landed unsized that way.
        """
        adapter = get_adapter("woocommerce")
        payload = {
            "id": 1, "type": "simple",
            "name": "Annayake MIYABI Woman Eau de parfum 100ml",
            "permalink": "https://e-elixir.mk/shop/x/",
            "prices": {"price": "621000", "currency_code": "MKD",
                       "currency_minor_unit": 2},
            "attributes": [{"name": "Достапни големини", "terms": [
                {"name": "15ml"}, {"name": "30ml"}, {"name": "60ml"}]}],
            "categories": [{"name": "Женски Eau de parfum"}],
        }
        got = adapter.parse_product(payload, "u", "eelixir",
                                    vertical="fragrance")
        assert [v.size_label for v in got.variants] == ["100ml"]

    def test_an_escaped_name_does_not_reach_the_catalogue(self):
        """The first crawl filed a product as "Annayake An 8217 Na Eau De
        Parfum" -- the entity's digits surviving into canonical_name as a
        word, because raw_title becomes the product's name."""
        adapter = get_adapter("woocommerce")
        payload = {
            "id": 1, "type": "simple",
            "name": "Annayake AN&#8217;NA ANNAYAKE Eau de parfum 100ml",
            "permalink": "https://e-elixir.mk/shop/x/",
            "prices": {"price": "621000", "currency_code": "MKD",
                       "currency_minor_unit": 2},
        }
        got = adapter.parse_product(payload, "u", "eelixir",
                                    vertical="fragrance")
        assert "8217" not in got.raw_title
        assert got.raw_title == "Annayake AN’NA ANNAYAKE Eau de parfum 100ml"

    def test_a_set_never_reaches_the_loader(self):
        adapter = get_adapter("woocommerce")
        payload = {
            "id": 1, "type": "simple",
            "name": "212 Vip Black 100ml EDP + Shower Gel 100ml",
            "permalink": "https://e-elixir.mk/shop/x/",
            "prices": {"price": "500000", "currency_code": "MKD",
                       "currency_minor_unit": 2},
            "categories": [{"name": "Машки сетови"}],
        }
        assert adapter.parse_product(payload, "u", "eelixir",
                                     vertical="fragrance") is None

    def test_the_same_payload_survives_another_vertical(self):
        """The exclusion is gated on the vertical because this adapter also
        serves a shop that sells shoes, and a sneaker whose title contains a
        plus is not a gift set."""
        adapter = get_adapter("woocommerce")
        payload = {
            "id": 1, "type": "simple", "name": "Patiki A + B",
            "permalink": "https://megasportonlineshop.com/p/x/",
            "prices": {"price": "3199", "currency_code": "MKD",
                       "currency_minor_unit": 0},
        }
        got = adapter.parse_product(payload, "u", "megasport")
        assert got is not None and got.min_price_minor == 3199

    def test_an_escaped_brand_does_not_orphan_the_offer(self):
        """21 of the first full crawl's 32 unmatched offers, diagnosed.

        e-elixir serves "Dolce &amp; Gabbana" in its brand taxonomy. The
        matcher blocks on brand, and `ensure_brand` will only create a name
        that passes `_BRAND_NAME` -- which the escaped form fails on its
        semicolon. So the brand was never created, the offer joined no
        product, and it sat with status 'unmatched' while the clean name
        "Dolce & Gabbana" would have resolved immediately.

        A mangled title is visible in the catalogue. A mangled brand is
        worse: the offer disappears from it.
        """
        from mkagg.load.promote import _BRAND_NAME

        adapter = get_adapter("woocommerce")
        got = adapter.parse_product({
            "id": 1, "type": "simple",
            "name": "Dolce &amp; Gabbana Devotion Eau de parfum",
            "permalink": "https://e-elixir.mk/shop/x/",
            "brands": [{"name": "Dolce &amp; Gabbana"}],
            "prices": {"price": "500000", "currency_code": "MKD",
                       "currency_minor_unit": 2},
        }, "u", "eelixir", vertical="fragrance")

        assert got.raw_brand == "Dolce & Gabbana"
        assert _BRAND_NAME.match(got.raw_brand), (
            "a brand this adapter emits must be one ensure_brand will accept")

    @pytest.mark.parametrize("escaped,clean", [
        ("Dolce &amp; Gabbana", "Dolce & Gabbana"),
        ("Victoria&#8217;s Secret", "Victoria’s Secret"),
        ("Viktor&amp;Rolf", "Viktor&Rolf"),
    ])
    def test_every_escaped_brand_e_elixir_serves(self, escaped, clean):
        adapter = get_adapter("woocommerce")
        got = adapter.parse_product({
            "id": 1, "type": "simple", "name": "X Eau de parfum 50ml",
            "permalink": "https://e-elixir.mk/shop/x/",
            "brands": [{"name": escaped}],
            "prices": {"price": "500000", "currency_code": "MKD",
                       "currency_minor_unit": 2},
        }, "u", "eelixir", vertical="fragrance")
        assert got.raw_brand == clean

    def test_the_variation_endpoint_is_what_prices_each_bottle(self):
        adapter = get_adapter("woocommerce")
        rail = adapter.parse_stock(
            load_json("eelixir_store_valentino_variations.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")
        assert {v.size_label: v.price_minor for v in rail.variants} == {
            "30ml": 4240, "50ml": 6040}
