"""shop.schatze.mk, the second perfumery and the sixth platform.

Every case here is a live page captured from the shop. The findings they
pin each cost a recon pass to discover, and three of them produced wrong
data the first time they were met.
"""
from __future__ import annotations

import re

import pytest
from conftest import load_bytes

from mkagg.adapters import get_adapter
from mkagg.adapters.nopcommerce import attribute_change_request
from mkagg.discover import (PRODUCT_URL_PATTERNS, as_facets, extract_links,
                            sweep_plan)
from mkagg.fragrance import read_gender
from mkagg.taxonomy import classify


@pytest.fixture
def adapter():
    return get_adapter("nopcommerce")


def parse(adapter, fixture, url):
    return adapter.parse_product(load_bytes(fixture), url, "schatze")


class TestReadingAProductPage:
    def test_the_brand_is_not_in_the_title(self, adapter):
        """"Pour Homme - edt" is Versace's, and the title never says so.

        This is the whole reason `mkagg.fragrance.line_name` takes a brand
        rather than finding one: comparing these titles to e-elixir's
        "Versace Pour Homme Eau de toilette" as strings joins nothing.
        """
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert offer.raw_title == "Pour Homme - edt"
        assert offer.raw_brand == "Versace"

    def test_the_shop_id_is_the_sku(self, adapter):
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert offer.merchant_sku == "46"

    def test_the_breadcrumb_gives_the_shelf(self, adapter):
        """Without the home link and without the product's own name."""
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert offer.category_path == "Fragrances / Women"

    def test_the_shelf_resolves_whichever_language_it_arrives_in(self):
        """The shop serves Macedonian or English depending on the client.

        A first request got "Производител:" and "Почетна / Парфеми /
        Женски"; curl got "Manufacturer:" and "Home / Fragrances / Women"
        from the same URL minutes later. Pinning one spelling would make
        the catalogue's category and gender depend on which one answered.
        """
        for shelf, gender in [("Fragrances / Women", "women"),
                              ("Парфеми / Женски", "women"),
                              ("Fragrances / Men", "men"),
                              ("Парфеми / Машки", "men"),
                              ("Парфеми / Унисекс", "unisex")]:
            assert classify(shelf) == "perfume", shelf
            assert read_gender(shelf) == gender, shelf


class TestThePriceShapes:
    """Two of them, and reading the first number on the page gets neither."""

    def test_a_plain_price(self, adapter):
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert offer.min_price_minor == 4490

    def test_a_discounted_price_is_not_read_as_a_label(self, adapter):
        """A discounted product renders "Цена:" above "Вашата цена:".

        The first recon pass recorded 212 Heroes as unpriced, having
        matched the `<label for="price-value-512">Цена:</label>` instead
        of the number beside it.
        """
        offer = parse(adapter, "schatze_212_heroes.html",
                      "https://shop.schatze.mk/men/212-heroes-edt-2")
        assert offer.min_price_minor == 4030

    def test_an_equal_old_price_is_not_a_discount(self, adapter):
        """This shop renders the two-price layout even at full price, and
        a badge reading "save nothing" is worse than no badge."""
        offer = parse(adapter, "schatze_212_heroes.html",
                      "https://shop.schatze.mk/men/212-heroes-edt-2")
        assert all(v.list_price_minor is None for v in offer.variants)


class TestVolumes:
    def test_one_volume_takes_the_page_price(self, adapter):
        offer = parse(adapter, "schatze_212_heroes.html",
                      "https://shop.schatze.mk/men/212-heroes-edt-2")
        assert [(v.size_label, v.price_minor) for v in offer.variants] == [
            ("90ml", 4030)]

    def test_several_volumes_claim_none(self, adapter):
        """The page offers 30ml, 50ml and 100ml and prices one of them.

        Which one is not stated beyond a `checked` attribute, and the
        others cost more. Spreading this figure across all three would be
        three wrong prices; attributing it to the checked one would be a
        guess about which. So the offer carries a price and no volume
        until the per-volume endpoint is permitted.
        """
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert [v.size_label for v in offer.variants] == [""]
        assert offer.min_price_minor == 4490

    def test_stock_is_unknown_unless_the_merchant_publishes_it(self, adapter):
        """The microdata says InStock for the *product*, never for a
        bottle. schatze is seeded `publishes_stock = false` for exactly
        that reason, and unknown must not be coerced to true."""
        offer = parse(adapter, "schatze_pour_homme.html",
                      "https://shop.schatze.mk/women/pour-homme-edt-2")
        assert all(v.in_stock is None for v in offer.variants)

    def test_the_per_volume_request_is_recorded_not_sent(self):
        """The one piece of recon that would otherwise have to be redone.

        It is not called: the path is under /shoppingcart/, which this
        shop's robots.txt disallows, and the merchant row says so.
        """
        url, body, headers = attribute_change_request(
            "https://shop.schatze.mk", "46", "46", "121")
        assert url.endswith("/shoppingcart/productdetails_attributechange")
        assert b"product_attribute_46=121" in body
        assert headers["X-Requested-With"] == "XMLHttpRequest"


class TestGiftSets:
    """152 of this shop's 1 234 fragrance pages are a set, not a bottle.

    They sit on the same shelf as the bottles and the first crawl brought
    every one of them in, because the exclusion was wired into the
    WooCommerce adapter and not this one.
    """

    def _as_set(self, fixture, title):
        body = load_bytes(fixture)
        return re.sub(rb"<h1([^>]*)>.*?</h1>",
                      b"<h1\1>" + title.encode() + b"</h1>",
                      body, count=1, flags=re.S)

    def test_a_set_is_not_a_bottle(self, adapter):
        page = self._as_set("schatze_pour_homme.html",
                            "212 Vip Black 100ml EDP + Shower Gel 100ml")
        assert adapter.parse_product(page, "u", "schatze",
                                     vertical="fragrance") is None

    def test_the_rule_is_about_perfume_not_the_platform(self, adapter):
        """Gated on the vertical, exactly as the WooCommerce adapter is.

        nopCommerce is shop software, not a fragrance shop: another store
        on it could sell something whose title legitimately contains a
        plus.
        """
        page = self._as_set("schatze_pour_homme.html",
                            "212 Vip Black 100ml EDP + Shower Gel 100ml")
        assert adapter.parse_product(page, "u", "schatze") is not None

    def test_a_bottle_still_passes(self, adapter):
        offer = adapter.parse_product(
            load_bytes("schatze_pour_homme.html"), "u", "schatze",
            vertical="fragrance")
        assert offer is not None and offer.raw_title == "Pour Homme - edt"


class TestFindingTheProducts:
    def test_the_pattern_takes_products_and_nothing_else(self):
        """Measured on a real listing: 27 two-segment links, 24 of them
        products and the rest /customer/ and /order/ pages."""
        pattern = PRODUCT_URL_PATTERNS["nopcommerce"]
        base = "https://shop.schatze.mk"
        html = ('<a href="/men/1-million-edt">x</a>'
                '<a href="/women/212-vip-ros-edp-2">x</a>'
                '<a href="/niche-fragrances/la-fenice-pour-homme-edp-2">x</a>'
                '<a href="/customer/addresses">x</a>'
                '<a href="/order/history">x</a>'
                '<a href="/manufacturer/all">x</a>'
                '<a href="/parfemi">x</a>')
        assert extract_links(html, pattern, base) == [
            f"{base}/men/1-million-edt",
            f"{base}/women/212-vip-ros-edp-2",
            f"{base}/niche-fragrances/la-fenice-pour-homme-edp-2"]

    def test_one_shelf_is_walked_not_four(self):
        """/parfemi is the only listing guaranteed to hold fragrances only.

        The gendered shelves look like better facets and are not: /men-2
        renders Clinique lotions under a heading that says "men". Walking
        those files cosmetics as perfume.
        """
        plan = sweep_plan("schatze", "nopcommerce", vertical="fragrance")
        facets = as_facets(plan.categories)
        assert [f.path for f in facets] == ["/parfemi"]
        assert facets[0].category == "perfume"
        # No gender on the facet: each product's own breadcrumb states it,
        # including Унисекс, which e-elixir can only infer.
        assert facets[0].gender is None

    def test_the_shelf_is_walked_to_exhaustion(self):
        """`parse_last_page_link` reads /page/N and this shop writes
        ?pagenumber=N, so an advertised total is not available to believe.
        Crawling page 1 and stopping would lose 52 pages silently."""
        plan = sweep_plan("schatze", "nopcommerce", vertical="fragrance")
        assert plan.walk_until_empty
        assert plan.page_suffix == "?pagenumber={page}"

    def test_another_vertical_does_not_reach_this_plan(self):
        assert sweep_plan("schatze", "nopcommerce", vertical="footwear") is None
