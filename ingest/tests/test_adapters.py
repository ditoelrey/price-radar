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


class TestSportVisionUnmappedSizes:
    """Sport Vision's own EU column has holes on some articles.

    Taken from the live page for the Under Armour Hovr Turbulence 2
    (sportvision.mk/mk/patiki/8580211), where the shop's conversion table runs
    out: the first rows echo the brand size into the EU column and leave
    centimetres blank, and the mapping only starts at US 5 -> EU 35.5.

    Storing "EU 4.5" for a men's running shoe is worse than storing nothing --
    it drops the shoe out of the EU size filter and prints a nonsense number
    beside a real price. `normalize_size` refuses it on the bound, so the row
    keeps its label and makes no EU claim.
    """

    @staticmethod
    def _page(rows: str) -> str:
        return (
            '<div class="product-size-tabs-new">'
            '<ul class="product-attributes list-inline">' + rows + "</ul></div>"
        )

    @staticmethod
    def _row(combid: str, orig: str, eur: str, cm: str) -> str:
        return (
            f'<li data-productsize-combid="{combid}">'
            f'<span class="original-size">{orig}</span>'
            f'<span class="eur-size">{eur}</span>'
            f'<span class="cm-size">{cm}</span></li>'
        )

    def _parse(self, rows):
        from mkagg.adapters.sportvision import SportVisionAdapter
        return SportVisionAdapter._parse_sizes(
            self._page("".join(self._row(*r) for r in rows)), 1000, "MKD")

    def test_unconverted_rows_lose_their_eu_size(self):
        variants = self._parse([
            ("1", "4.5", "4.5", ""),      # shop never converted this one
            ("2", "5", "35.5", "22"),     # mapping starts here
        ])
        assert len(variants) == 2
        unmapped, mapped = variants

        # The row survives -- it is a real, buyable size with a real price.
        assert unmapped.size_label == "4.5"
        assert unmapped.price_minor == 1000
        # ... but it makes no EU claim.
        assert unmapped.size_eu is None

        assert mapped.size_eu == Decimal("35.5")
        assert mapped.size_cm == Decimal("22")

    def test_genuine_childrens_sizes_are_kept(self):
        """A converted children's run is well inside the bound and survives."""
        variants = self._parse([
            ("1", "11C", "28", "17"),
            ("2", "1Y", "32", "20"),
        ])
        assert [v.size_eu for v in variants] == [Decimal("28"), Decimal("32")]

    def test_adult_sizes_are_never_touched(self):
        variants = self._parse([("1", "42", "42", "")])
        assert variants[0].size_eu == Decimal("42")


class TestSportVisionListPrice:
    """The pre-discount price, so the UI can show what the saving is.

    Attribute values are taken verbatim from two live pages for the same
    article, adidas SL 72 Pro (MPN KK3077): sportvision had it at 50% off,
    buzz at full price on the same day. That pair is the whole test -- the
    shop fills `oldprice` either way, and only `show-oldprice` distinguishes
    a real discount from a copy of the current price.
    """

    DISCOUNTED = (
        'data-productsize-price="3.394" data-productsize-dicount="50" '
        'data-productsize-price-without-discount="3.394" '
        'data-productsize-show-oldprice="1" data-productsize-oldprice="6.788" '
        'data-productsize-combid="6415999"')
    FULL_PRICE = (
        'data-productsize-price="6.788" data-productsize-dicount="0" '
        'data-productsize-price-without-discount="6.788" '
        'data-productsize-show-oldprice="-1" data-productsize-oldprice="6.788" '
        'data-productsize-combid="6325544"')

    def _parse(self, attrs, price_minor=3394):
        from mkagg.adapters.sportvision import SportVisionAdapter
        html = ('<div class="product-size-tabs-new">'
                '<ul class="product-attributes list-inline">'
                f'<li {attrs}><span class="original-size">9</span>'
                '<span class="eur-size">43</span>'
                '<span class="cm-size">27.5</span></li></ul></div>')
        return SportVisionAdapter._parse_sizes(html, price_minor, "MKD")

    def test_discounted_size_carries_its_old_price(self):
        v = self._parse(self.DISCOUNTED, price_minor=3394)[0]
        assert v.price_minor == 3394
        assert v.list_price_minor == 6788

    def test_full_price_size_has_no_list_price(self):
        """The case that makes the flag necessary.

        buzz fills `oldprice` with 6.788 while selling at 6.788. Reading the
        value without the flag would give every variant in the catalogue a
        list price equal to its price, and the UI would draw a "-0%" badge on
        all of them.
        """
        v = self._parse(self.FULL_PRICE, price_minor=6788)[0]
        assert v.price_minor == 6788
        assert v.list_price_minor is None

    def test_a_list_price_that_is_not_higher_is_refused(self):
        """A "discount" that is not cheaper is not a discount."""
        attrs = ('data-productsize-show-oldprice="1" '
                 'data-productsize-oldprice="3.394" '
                 'data-productsize-combid="1">')
        assert self._parse(attrs.rstrip(">"), price_minor=3394)[0].list_price_minor is None

    def test_sold_out_sizes_carry_no_pricing_at_all(self):
        """Sport Vision strips pricing attributes from sold-out sizes.

        Those rows keep only a combid and `class="disabled"`, which is why a
        discounted product commonly yields a list price on just one or two of
        its sizes -- the ones still buyable.
        """
        v = self._parse('class="ease disabled" data-productsize-combid="6415978"')[0]
        assert v.in_stock is False
        assert v.list_price_minor is None


class TestMegasportSoldOut:
    """A shop that takes the price down with the stock.

    megasport publishes no price at all once every size is gone: no `offers`
    node in its JSON-LD, nothing on the page, and `data-product_variations`
    set to an empty array. Dropping those offers told shoppers the shop never
    carried the item; recording them says it is sold out there, which is true
    and useful.
    """

    PAGE = ('<div class="product type-product product-type-variable">'
            '<form data-product_id="43787" data-product_variations="[]">'
            '</form>{stock}<span class="sku">H01551</span></div>')
    OOS = '<p class="stock out-of-stock">Нема залиха</p>'

    def _offer(self, stock):
        from mkagg.adapters import get_adapter
        return get_adapter("woocommerce_html").parse_product(
            self.PAGE.format(stock=stock).encode(),
            "https://megasportonlineshop.com/p/patiki-hoops-2-0-cmf-i-3/",
            "megasport")

    def test_sold_out_product_is_recorded_without_a_price(self):
        offer = self._offer(self.OOS)
        assert offer is not None
        assert len(offer.variants) == 1
        v = offer.variants[0]
        assert v.price_minor is None, "0 would render as 'free'"
        assert v.in_stock is False
        assert offer.is_sold_out_unpriced
        # Complete as it stands: the gate must not reject the run over it.
        assert offer.quality_issues() == []

    def test_no_price_and_no_sold_out_marker_invents_nothing(self):
        """The guard that keeps a parser failure from looking like a sell-out.

        An empty variations list on its own could just as easily mean the
        markup changed. Without the shop's own out-of-stock marker there is no
        positive evidence of anything, so no variant is produced.
        """
        offer = self._offer("")
        assert offer is None or offer.variants == []


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

    def test_a_second_shop_on_the_same_platform_counts_in_cents(self):
        """e-elixir runs the same Store API and scales its prices by 100.

        Captured live: Valentino Donna Eau de parfum, 30ml at 4 240 den
        reduced from 5 650. The payload says ``currency_minor_unit: 2`` and
        sends ``"424000"``. The adapter was written against megasport, which
        says 0 -- so until the declared unit was actually read, this product
        would have been stored, listed and sorted at 424 000 den.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_product(
            load_json("eelixir_store_valentino_donna_edp.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")

        assert offer is not None
        assert offer.min_price_minor == 4240
        assert offer.currency_code == "MKD"
        assert all(v.list_price_minor == 5650 for v in offer.variants)

    def test_a_perfume_is_priced_like_a_perfume(self):
        """The shape of the bug, independent of the exact number.

        A 100x error does not look like a typo in a listing -- it looks like
        a plausible price for something else. This is the bound that would
        have caught it.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_product(
            load_json("eelixir_store_valentino_donna_edp.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")
        assert 100 < offer.min_price_minor < 100_000, offer.min_price_minor

    def test_a_bottle_is_sized_by_volume(self):
        """The fragrance axis, captured live from e-elixir.

        A parent payload carries one price and a range, never a price per
        volume -- so the volumes themselves come from the variation
        endpoint, which is the only place each bottle is priced.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_stock(
            load_json("eelixir_store_valentino_variations.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")

        priced = {v.size_label: v.price_minor for v in offer.variants}
        assert priced == {"30ml": 4240, "50ml": 6040}
        assert all(v.list_price_minor for v in offer.variants), (
            "the reduced-from price is on each variation and is what the "
            "discount badge reads")

    def test_a_sold_out_volume_is_not_offered(self):
        """Presence in the payload does not mean buyable.

        It did on megasport, and the adapter said so in a comment as though
        it were a fact about WooCommerce. e-elixir returns sold-out
        variations too: Ralph Lauren Polo 67 comes back with three volumes
        and the 75ml out of stock. Marking it buyable would quote a price
        for a bottle nobody can put in a basket.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_stock(
            load_json("eelixir_store_polo67_variations.json"),
            "https://e-elixir.mk/shop/ralph-lauren-polo-67/", "eelixir")

        stock = {v.size_label: v.in_stock for v in offer.variants}
        assert stock == {"40ml": True, "75ml": False, "125ml": True}

    def test_the_brand_and_the_shelf_travel_with_the_offer(self):
        """Neither is in the title, and both decide the product's identity.

        The shelf states the gender and the concentration; the brand
        taxonomy is populated on 969 of e-elixir's 987 fragrances, while
        megasport leaves it empty and keeps a manufacturer code in `sku`.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_product(
            load_json("eelixir_store_valentino_donna_edp.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")

        assert offer.raw_brand == "Valentino"
        assert offer.category_path == "Женски Eau de parfum"

    def test_a_multi_volume_listing_claims_no_volume(self):
        """`prices.price` is the cheapest bottle, and which one is unstated.

        Usually the smallest -- but "usually" would print a 30ml price on a
        100ml listing every time it is not, so the listing contributes a
        price and no volume. The rail arrives with the variation fetch.
        """
        adapter = get_adapter("woocommerce")
        offer = adapter.parse_product(
            load_json("eelixir_store_valentino_donna_edp.json"),
            "https://e-elixir.mk/shop/valentino-donna-edp/", "eelixir")

        assert [v.size_label for v in offer.variants] == [""]
        assert offer.min_price_minor == 4240

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

    def test_an_eu_only_row_is_read_as_eu_not_uk(self):
        """The storefront bug: Sport-M's EU 34 vanished from the size filter.

        `Velicina` is the platform's primary label, and what it means depends
        on the row. Beside an `EvropskaVelicina` it is the UK size; alone, as
        this shop serves a child's shoe, it is the EU size and the only size
        there is::

            {"Velicina": "34", "Zaliha": 2, "EvropskaVelicina": null}

        Reading it as UK lost the size completely -- `normalize_size` bounds
        sizes to EU 16-60 and UK sizes stop around 15 -- so the offer kept
        its label, lost its EU size, and disappeared from every size-filtered
        page. 3,873 variants across 846 products, all on sport-m and sizeer.
        """
        offer_sizes = parse_sizes(
            [{"Velicina": "34", "Zaliha": 2, "EvropskaVelicina": None,
              "VelicinaCM": 0.00},
             {"Velicina": "35", "Zaliha": 1, "EvropskaVelicina": None,
              "VelicinaCM": 0.00}],
            price_minor=1195, publishes_stock=True)

        assert [v.size_label for v in offer_sizes] == ["34", "35"]
        assert [str(v.size_eu) for v in offer_sizes] == ["34.000", "35.000"]
        assert all(v.in_stock is True for v in offer_sizes)

    def test_a_uk_and_eu_row_still_reads_the_eu_one(self):
        """The other shape, which must not regress: a real UK size beside a
        real EU one, where the EU label is the one that counts."""
        offer_sizes = parse_sizes(
            [{"Velicina": "7.5", "Zaliha": 3,
              "EvropskaVelicina": "41\u2153", "VelicinaCM": 26.5}],
            price_minor=5000, publishes_stock=True)

        assert len(offer_sizes) == 1
        assert offer_sizes[0].size_label == "41\u2153"
        assert str(offer_sizes[0].size_eu) == "41.333"

    def test_no_variant_ever_claims_a_uk_size(self):
        """`size_uk` is unreachable honestly and is left empty.

        The only `Velicina` values that survive the EU bound are the ones
        that are not UK sizes, so anything this column could hold would be
        an EU size in the wrong place -- which is exactly how 3,211 rows
        came to claim a UK 34, a size that does not exist.
        """
        payloads = [
            [{"Velicina": "34", "Zaliha": 1, "EvropskaVelicina": None}],
            [{"Velicina": "7.5", "Zaliha": 1,
              "EvropskaVelicina": "41\u2153"}],
            [{"Velicina": "86", "Zaliha": 1,
              "EvropskaVelicina": "12-18 \u043c\u0435\u0441."}],
        ]
        for payload in payloads:
            for variant in parse_sizes(payload, price_minor=1,
                                       publishes_stock=True):
                assert variant.size_uk is None, payload

    def test_an_apparel_row_keeps_height_and_claims_no_shoe_size(self):
        """The same two fields, a third meaning: height beside an age."""
        offer_sizes = parse_sizes(
            [{"Velicina": "86", "Zaliha": 1,
              "EvropskaVelicina": "12-18 \u043c\u0435\u0441.",
              "VelicinaCM": 0.00}],
            price_minor=999, publishes_stock=True)

        assert offer_sizes[0].size_label == "12-18 \u043c\u0435\u0441."
        assert offer_sizes[0].size_eu is None
        assert offer_sizes[0].size_height_cm == 86

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
        """Woo writes "44-5" for 44.5 in the variation attributes.

        That slug is an internal term name, and the <select> carries the text
        the shop actually shows for it. Reading the label from there gives the
        shopper "44.5" rather than "44-5" -- and, more importantly, is what
        keeps Woo's placeholder option (slug "387", displayed as a dash) from
        being mistaken for a size.
        """
        offer = self._offer()
        by_label = {v.size_label: v.size_eu for v in offer.variants}
        assert "44.5" in by_label, by_label
        assert by_label["44.5"] == Decimal("44.5")

    def test_passes_quality_validation(self):
        assert self._offer().quality_issues() == []


def test_seven_adapters_cover_nine_stores():
    """Fewer adapters than shops, because several share a platform.

    Two of them exist twice over -- an API adapter and an HTML one for the
    same software -- because the API is the better read and the shop's
    robots.txt decides whether we may use it. magento and woocommerce are
    the permitted-route pairs; dsport and megasport run on the HTML halves
    for that reason, while e-elixir runs on the woocommerce API half
    because its robots.txt allows /wp-json/.
    """
    from mkagg.adapters import all_adapters
    assert set(all_adapters()) == {
        "sportvision", "aspnet_mk",                  # crawlable as found
        "magento", "woocommerce",                    # API: need permission
        "magento_html", "woocommerce_html",          # robots-permitted route
        "nopcommerce",                               # schatze, V27 fragrances
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


class TestProductImages:
    """Every platform must yield a product photo, and never site chrome.

    The storefront exposed this: 27 of 32 products rendered a grey
    placeholder. Three separate causes, one per platform family.
    """

    CASES = [
        # (merchant, adapter, fixture, url, sizes fixture, expected substring)
        ("sportvision", "sportvision", "sportvision_caven20.html",
         "https://www.sportvision.mk/mk/patiki/8550245-x", None, "392290-02"),
        ("buzz", "sportvision", "buzz_stansmith.html",
         "https://www.buzzsneakers.mk/mk/patiki/2011-x", None, "M20325"),
        ("megasport", "woocommerce_html", "megasport_product_caven20.html",
         "https://megasportonlineshop.com/p/x/", None, "392290-02"),
        ("dsport", "magento_html", "dsport_product_kj8942.html",
         "https://www.dsport.mk/muskarci/obuca/cizme/adidas-terrex-kj8942",
         None, "KJ8942"),
        ("sportm", "aspnet_mk", "sportm_stansmith.html",
         "https://www.sport-m.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
         "sportm_getvelicini_M20325.json", "/ProductImages/M20325"),
        ("sizeer", "aspnet_mk", "sizeer_stansmith.html",
         "https://sizeer.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
         "sizeer_getvelicini_M20325.json", "/ProductImages/M20325"),
    ]

    def _offer(self, merchant, adapter_slug, fixture, url, sizes):
        adapter = get_adapter(adapter_slug)
        if adapter_slug == "aspnet_mk":
            return adapter.parse_product(
                load_bytes(fixture), url, merchant,
                sizes_payload=load_json(sizes),
                publishes_stock=(merchant == "sportm"))
        return adapter.parse_product(load_bytes(fixture), url, merchant)

    @pytest.mark.parametrize(
        "merchant,adapter_slug,fixture,url,sizes,expected",
        CASES, ids=[c[0] for c in CASES])
    def test_every_platform_yields_an_image(self, merchant, adapter_slug,
                                            fixture, url, sizes, expected):
        offer = self._offer(merchant, adapter_slug, fixture, url, sizes)
        assert offer.image_url, f"{merchant} produced no image"
        assert offer.image_url.startswith("http")
        assert expected.lower() in offer.image_url.lower()

    def test_site_logos_are_never_used_as_product_images(self):
        """sport-m and sizeer advertise their own logo as og:image.

        `Content/FacebookLogo.png` and `Content/Logo.png`. Trusting that tag
        would put a logo on every card — code that looks like it works.
        """
        for merchant, sizes in (("sportm", "sportm_getvelicini_M20325.json"),
                                ("sizeer", "sizeer_getvelicini_M20325.json")):
            fixture = f"{merchant}_stansmith.html"
            host = ("www.sport-m.com.mk" if merchant == "sportm"
                    else "sizeer.com.mk")
            offer = self._offer(
                merchant, "aspnet_mk", fixture,
                f"https://{host}/ProductCatalog/ProductDetails?ProductID=M20325",
                sizes)
            lowered = offer.image_url.lower()
            assert "logo" not in lowered
            assert "/content/" not in lowered

    def test_chrome_guard_rejects_known_furniture(self):
        from mkagg.adapters.base import looks_like_product_image

        for bad in ("https://www.sport-m.com.mk/Content/FacebookLogo.png",
                    "https://sizeer.com.mk/Content/Logo.png",
                    "https://x.mk/BrandsImages/Adidas.png",
                    "https://x.mk/MenuImages/banner.jpg",
                    "https://x.mk/img/placeholder.png",
                    "https://x.mk/no-image.jpg", "", None):
            assert not looks_like_product_image(bad), bad
        for good in ("https://x.mk/ProductImages/M20325.webp",
                     "https://x.mk/media/catalog/product/cache/a/1790606725KJ8942.jpg"):
            assert looks_like_product_image(good), good

    def test_jsonld_image_handles_every_shape(self):
        """schema.org allows four shapes; these stores use three of them."""
        from mkagg.adapters.base import ld_image

        assert ld_image({"image": "https://x.mk/a.jpg"}) == "https://x.mk/a.jpg"
        # sportvision: a list of strings — the shape a scalar helper dropped.
        assert ld_image({"image": ["https://x.mk/a.jpg", "https://x.mk/b.jpg"]}) \
            == "https://x.mk/a.jpg"
        # megasport: a list of ImageObjects.
        assert ld_image({"image": [{"@type": "ImageObject",
                                    "url": "https://x.mk/c.jpg"}]}) \
            == "https://x.mk/c.jpg"
        assert ld_image({"image": {"url": "https://x.mk/d.jpg"}}) == "https://x.mk/d.jpg"
        # A logo in the list is skipped in favour of the next candidate.
        assert ld_image({"image": ["https://x.mk/Content/Logo.png",
                                   "https://x.mk/real.jpg"]}) == "https://x.mk/real.jpg"
        assert ld_image({"image": []}) is None
        assert ld_image(None) is None

    def test_aspnet_image_belongs_to_this_product(self):
        """The page also carries the carousel's images and brand logos."""
        from mkagg.adapters.aspnet_mk import product_image

        html = load_bytes("sportm_stansmith.html").decode("utf-8", "replace")
        url = product_image(html, "M20325", "https://www.sport-m.com.mk")
        assert url == "https://www.sport-m.com.mk/ProductImages/M20325.webp"
        # A neighbour's id must not borrow this product's photo.
        assert "M20325" not in (product_image(html, "GX6394",
                                              "https://www.sport-m.com.mk") or "")
        assert product_image(html, "", "https://x.mk") is None


class TestSportMSpecifications:
    """The table every Sport-M product page carries, and why it is parsed.

    Their Опрема lives at `/ProductCatalog?Segment=06` with no gender in any
    URL -- 758 articles the facet walk can categorise and cannot gender --
    while each page states both outright. Copied verbatim from
    `ProductID=090238-03`: the stray spaces and the `<b> — </b>` sitting
    between the two spans are what the regex has to survive.
    """

    SPECS = """<div id="Opis"><button><h2>Спецификации</h2></button>
<div id="collapseOpis" class="collapse" style="padding:0"><ul>
    <li><span class="opis">Возраст</span><b> — </b> <span style="margin-left:30px">За возрасни </span></li>
    <li><span class="opis">Пол</span><b> — </b> <span style="margin-left:30px">Унисекс </span></li>
    <li><span class="opis">Боја</span><b> — </b> <span style="margin-left:30px"> Црна </span></li>
    <li><span class="opis">Подгрупа</span><b> — </b> <span style="margin-left:30px"> Ранци </span> </li>
    <li><span class="opis">Бренд</span> <b> — </b> <span style="margin-left:30px"> Puma</span> </li>
</ul></div></div>"""

    def _with(self, age=None, sex=None, subgroup=None):
        html = self.SPECS
        if age:
            html = html.replace("За возрасни", age)
        if sex:
            html = html.replace("Унисекс", sex)
        if subgroup:
            html = html.replace("Ранци", subgroup)
        return html

    def test_reads_the_table(self):
        from mkagg.adapters.aspnet_mk import parse_specifications
        specs = parse_specifications(self.SPECS)
        assert specs["Пол"] == "Унисекс"
        assert specs["Подгрупа"] == "Ранци"
        assert specs["Бренд"] == "Puma"

    def test_an_explicit_unisex_reaches_the_offer(self):
        """The 758 articles this exists for."""
        from mkagg.adapters.aspnet_mk import parse_specifications, spec_gender
        assert spec_gender(parse_specifications(self.SPECS)) == "unisex"

    def test_a_childs_age_outranks_its_sex(self):
        """The disagreement that makes the order matter.

        A Speedo swim cap reads "За бебиња (до 3 год.)" and "Пол — Машки".
        Reading Пол alone files an infant's cap in the men's department, and
        kids mixed with an adult department resolves to no gender at all
        further down the pipeline.
        """
        from mkagg.adapters.aspnet_mk import parse_specifications, spec_gender
        baby = self._with(age="За бебиња (до 3 год.)", sex="Машки")
        teen = self._with(age="За тинејџери (од 8-16 год.)", sex="Женски")
        assert spec_gender(parse_specifications(baby)) == "kids"
        assert spec_gender(parse_specifications(teen)) == "kids"

    def test_an_adult_keeps_its_sex(self):
        from mkagg.adapters.aspnet_mk import parse_specifications, spec_gender
        assert spec_gender(parse_specifications(self._with(sex="Машки"))) == "men"
        assert spec_gender(parse_specifications(self._with(sex="Женски"))) == "women"

    def test_the_subgroup_becomes_a_leaf(self):
        from mkagg.adapters.aspnet_mk import (parse_specifications,
                                              spec_category)
        for subgroup, expected in (("Ранци", "bags_backpacks"),
                                   ("Капи за пливање", "swim_gear"),
                                   ("Тротинети", "skates_scooters"),
                                   ("Чорапи", "socks")):
            specs = parse_specifications(self._with(subgroup=subgroup))
            assert spec_category(specs) == expected, subgroup

    def test_a_page_without_the_table_says_nothing(self):
        """Silence is not a gender."""
        from mkagg.adapters.aspnet_mk import (parse_specifications,
                                              spec_category, spec_gender)
        assert parse_specifications("<html><body>x</body></html>") == {}
        assert spec_gender({}) is None
        assert spec_category({}) is None

    def test_an_unmappable_subgroup_is_not_forced(self):
        """A leaf we do not carry stays unclaimed rather than guessed."""
        from mkagg.adapters.aspnet_mk import (parse_specifications,
                                              spec_category)
        specs = parse_specifications(self._with(subgroup="Функо фигури"))
        assert spec_category(specs) is None

    def test_the_subgroup_is_kept_verbatim_on_the_offer(self):
        """The shelf in the shop's words, not just the slug it maps to.

        `spec_category` throws away everything `classify` cannot place, and
        for a while that was the only thing read off this row. Keeping the
        raw value means a subgroup we have no rule for yet -- "Заштитен сет
        за дожд" is a real one -- is recorded against the offer instead of
        vanishing, and a later rule can pick it up without a re-crawl.
        """
        from mkagg.adapters.aspnet_mk import parse_specifications
        specs = parse_specifications(self._with(subgroup="Заштитен сет за дожд"))
        assert specs["Подгрупа"] == "Заштитен сет за дожд"


class TestTheClothingUmbrella:
    """Why 1,010 products sat in the parent bucket, in four parts.

    sport-m and sizeer publish a department umbrella, `?Segment=NN&Grupa=02`,
    that names no garment. Products reachable only through it were labelled
    "Текстил" and could be called nothing more precise than clothing -- while
    their own pages said "Градник", "Дресови-фудбал", "Костим за капење".
    Each assertion below is one link in that chain.
    """

    def test_the_umbrella_label_means_clothing(self):
        """It classified to None, so the label read as no evidence at all."""
        from mkagg.taxonomy import PARENT_SLUGS, classify
        assert classify("Текстил") == "apparel"
        assert classify("Текстил") in PARENT_SLUGS

    def test_the_subgroups_the_navigation_never_links(self):
        """The nav exposes 18 codes; the sidebar counts 27 subgroups.

        These nine have no `PodGrupa` code to address them by, which is why
        extending the code map could not have reached them. Read off the
        product pages instead, they all place.
        """
        from mkagg.taxonomy import classify
        assert classify("Градник") == "sports_bras"
        assert classify("Пододело") == "underwear"
        assert classify("Долна облека") == "underwear"
        assert classify("Дресови") == "tshirts"
        assert classify("Дресови-фудбал") == "tshirts"
        assert classify("Дресови-кошарка") == "tshirts"
        assert classify("Шорцеви-кошарка") == "shorts"
        assert classify("Ски Панталони") == "trousers"
        assert classify("Летни комплети") == "tracksuits"

    def test_a_parent_hint_does_not_overwrite_a_stated_leaf(self):
        """The bug itself: the umbrella's "apparel" over the page's leaf."""
        from mkagg.worker import resolve_category_hint
        assert resolve_category_hint("apparel", "sports_bras") == "sports_bras"
        assert resolve_category_hint("accessories", "socks") == "socks"
        assert resolve_category_hint("footwear", "sneakers") == "sneakers"

    def test_a_specific_listing_still_wins(self):
        """What the overwrite exists for, and must keep doing.

        Discovery knows the department a title omits. A men's t-shirt facet
        outranks whatever the page's own table happens to say, because the
        shelf the shopper clicked is the stronger claim.
        """
        from mkagg.worker import resolve_category_hint
        assert resolve_category_hint("tshirts", "hoodies") == "tshirts"
        assert resolve_category_hint("cleats", None) == "cleats"

    def test_a_parent_still_beats_silence(self):
        """"Clothing, kind unspecified" is a real answer when nothing else is."""
        from mkagg.worker import resolve_category_hint
        assert resolve_category_hint("apparel", None) == "apparel"
        assert resolve_category_hint(None, "sports_bras") == "sports_bras"
        assert resolve_category_hint(None, None) is None

    def test_the_page_shelf_reaches_the_offer(self):
        """End to end on the real fixture: parsed, carried, ready to store."""
        from mkagg.adapters import get_adapter
        adapter = get_adapter("aspnet_mk")
        offer = adapter.parse_product(
            load_bytes("sportm_stansmith.html"),
            "https://www.sport-m.com.mk/ProductCatalog/"
            "ProductDetails?ProductID=M20325",
            "sportm")
        assert offer is not None
        # Whatever this fixture's own table says, it must arrive verbatim
        # and agree with what the spec parser read.
        from mkagg.adapters.aspnet_mk import parse_specifications
        specs = parse_specifications(
            load_bytes("sportm_stansmith.html").decode("utf-8", "replace"))
        assert offer.category_path == specs.get("Подгрупа")
        assert offer.category_path


class TestAUniversalSizeThatIsInStock:
    """The Slazenger silicone cap, and the dedupe that called it sold out.

    Taken from the live sportreality page. These shops print one ``<li>``
    per size *code* and several codes can carry the same displayed label:
    this cap offers ONE, 1 and NS, all three shown as "Унив.", and only NS
    -- the last of the three -- is in stock. Dedupe was first-wins, so the
    catalogue kept a disabled twin and the storefront said "Sold out" about
    a cap the shop was selling.

    The page is also why the storefront showed crossed-out S / M / L: of the
    twenty codes, only those three read as a letter size, and every other
    one was typed `numeric`, which the size picker deliberately hides.
    """

    FIXTURE = "sportreality_slazenger_cap.html"
    URL = ("https://www.sportreality.mk/mk/kapa-za-plivanje/"
           "3431-slazenger-silicone-cap")

    def variants(self):
        adapter = get_adapter("sportvision")
        offer = adapter.parse_product(
            load_bytes(self.FIXTURE), self.URL, "sportreality")
        return offer.variants

    def test_the_universal_size_survives_as_in_stock(self):
        univ = [v for v in self.variants() if v.size_label == "Унив."]
        assert len(univ) == 1, [v.size_label for v in self.variants()]
        assert univ[0].in_stock is True

    def test_it_is_the_only_size_in_stock(self):
        live = [v.size_label for v in self.variants() if v.in_stock]
        assert live == ["Унив."]

    def test_the_sold_out_codes_are_still_recorded(self):
        """Dropping them would hide that the shop lists them at all."""
        labels = {v.size_label for v in self.variants()}
        assert {"S", "M", "L", "OS", "OSFA", "YTH"} <= labels

    def test_the_in_stock_twin_wins_whichever_order_it_arrives_in(self):
        """The rule is "in stock wins", not "last wins"."""
        from mkagg.adapters.sportvision import SportVisionAdapter
        html = (
            '<div class="product-size-tabs-new"><ul class="product-attributes">'
            '<li data-productsize-combid="1" class="disabled">'
            '<span class="eur-size">Унив.</span></li>'
            '<li data-productsize-combid="2">'
            '<span class="eur-size">Унив.</span></li>'
            '</ul></div>')
        out = SportVisionAdapter._parse_sizes(html, 1000, "MKD")
        assert [(v.size_label, v.in_stock, v.merchant_variant_id)
                for v in out] == [("Унив.", True, "2")]

        flipped = (
            '<div class="product-size-tabs-new"><ul class="product-attributes">'
            '<li data-productsize-combid="2">'
            '<span class="eur-size">Унив.</span></li>'
            '<li data-productsize-combid="1" class="disabled">'
            '<span class="eur-size">Унив.</span></li>'
            '</ul></div>')
        out = SportVisionAdapter._parse_sizes(flipped, 1000, "MKD")
        assert [(v.size_label, v.in_stock, v.merchant_variant_id)
                for v in out] == [("Унив.", True, "2")]

    def test_a_sold_out_duplicate_never_replaces_another(self):
        """Two sold-out twins stay one row, and keep the first id."""
        from mkagg.adapters.sportvision import SportVisionAdapter
        html = (
            '<div class="product-size-tabs-new"><ul class="product-attributes">'
            '<li data-productsize-combid="7" class="disabled">'
            '<span class="eur-size">Унив.</span></li>'
            '<li data-productsize-combid="8" class="disabled">'
            '<span class="eur-size">Унив.</span></li>'
            '</ul></div>')
        out = SportVisionAdapter._parse_sizes(html, 1000, "MKD")
        assert [(v.in_stock, v.merchant_variant_id) for v in out] == [
            (False, "7")]


class TestTheSpecTableSportVisionPublishes:
    """`Пол` and `Возраст`, which nothing read until this audit.

    The fixture is a live page: Nike BASIC kids' socks, where the two rows
    disagree in the way that matters.

        Пол      Унисекс
        Возраст  За мали деца (4-10 год.)

    Reading Пол first calls that an adult unisex sock. It is a child's, and
    151 of the 712 products under Опрема -> Чорапи are in the same position.
    """

    def test_the_shops_own_audience_is_read(self):
        adapter = get_adapter("sportvision")
        offer = adapter.parse_product(
            load_bytes("sportvision_kids_socks.html"),
            "https://www.sportvision.mk/mk/corapi/8428184-nike-basic",
            "sportvision")
        assert offer is not None
        assert offer.gender_hint == "kids"
        assert offer.extractors["gender"] == "css"

    def test_the_rows_are_found_by_class_not_by_label(self):
        """Every page's navigation links a "Поло блуза" shelf, and "Поло"
        contains "Пол". Searching for the label text reads that link as the
        product's gender -- which is what the first pass of this audit did,
        reporting `Пол=о блуза`."""
        from mkagg.adapters.sportvision import spec_attr

        html = load_bytes("sportvision_kids_socks.html").decode("utf-8",
                                                                "replace")
        assert spec_attr(html, "pol") == "Унисекс"
        assert spec_attr(html, "vozrast") == "За мали деца (4-10 год.)"

    def test_the_table_is_not_an_accessory_thing(self):
        """It is on every product page, footwear included.

        The Caven 2.0 fixture was captured for an entirely different test
        and states `Пол: Машки` -- so this evidence is available across the
        whole catalogue, not only in the vertical that made us look.
        """
        from mkagg.adapters.sportvision import spec_attr

        html = load_bytes("sportvision_caven20.html").decode("utf-8",
                                                             "replace")
        assert spec_attr(html, "pol") == "Машки"

    def test_a_row_that_is_not_there_claims_nothing(self):
        """A missing row is silence, not a default."""
        from mkagg.adapters.sportvision import spec_attr

        assert spec_attr("<html><body>no table</body></html>", "pol") is None
        assert spec_attr("", "vozrast") is None
