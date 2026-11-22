"""Normalisation tests.

Every case here is a real string observed on a target store during recon, not
an invented edge case. That is why they are worth keeping.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from mkagg.normalize import (clean_model_name, normalize_size, normalize_sku,
                             parse_api_price_minor, parse_price_minor,
                             sku_base, slugify, translit_mk)


class TestNormalizeSku:
    @pytest.mark.parametrize("raw,expected", [
        ("392290-02", "39229002"),       # Puma, sportvision + megasport
        ("392290 02", "39229002"),
        ("M20325", "M20325"),            # Adidas, sport-m URL + buzz
        ("m20325", "M20325"),
        ("dh2987-001", "DH2987001"),     # Nike
        ("CZ9556", "CZ9556"),            # dsport GraphQL
        ("KJ8942", "KJ8942"),
        ("IM7588-002", "IM7588002"),
        ("  408280-02  ", "40828002"),
    ])
    def test_normalises(self, raw, expected):
        assert normalize_sku(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "---", "//"])
    def test_empty_is_none(self, raw):
        assert normalize_sku(raw) is None


class TestSkuBase:
    def test_nike_style_drops_colourway(self):
        assert sku_base("DH2987-001") == "DH2987"
        assert sku_base("DH2987-100") == "DH2987"

    def test_puma_style_drops_colourway(self):
        assert sku_base("392290-02") == "392290"

    def test_unknown_pattern_is_none(self):
        # "Same model, other colour" must not be guessed for codes whose
        # structure we do not recognise -- a false base merges two shoes.
        assert sku_base("M20325") is None


class TestNormalizeSize:
    @pytest.mark.parametrize("raw,expected", [
        ("35,5", "35.5"),        # sportvision.mk, comma decimal
        ("35.5", "35.5"),        # sportvision.mk, dot -- SAME PAGE
        ("36", "36"),
        ("44 2/3", "44.667"),    # buzzsneakers.mk, ASCII fraction
        ("45 1/3", "45.333"),
        ("41⅓", "41.333"),  # sport-m / sizeer, U+2153 VULGAR ONE THIRD
        ("42⅔", "42.667"),  # U+2154 VULGAR TWO THIRDS
        ("46½", "46.5"),    # U+00BD one half
        ("37-5", "37.5"),        # megasport variation value
        ("EU 42", "42"),
        ("41-42", "41"),         # range -> lower bound
    ])
    def test_parses(self, raw, expected):
        assert normalize_size(raw) == Decimal(expected)

    @pytest.mark.parametrize("raw", [
        "UK 8.5", "US 10", "uk 7",   # another system's number, not an EU size
        "387",                       # WooCommerce placeholder term id
        "116", "152", "176",         # children's clothing, sized in cm
        "1", "4.5", "13.5",          # a shop's unconverted US/UK column
        "61", "100",
    ])
    def test_refuses_numbers_that_are_not_eu_shoe_sizes(self, raw):
        """`size_eu` means one thing, so a number that cannot be it is dropped.

        Every one of these reached the database at some point. The 387 is the
        expensive one: it is a Woo term id whose displayed text is a dash, and
        taken as a size it overflowed `numeric(5,3)` and killed a 500-product
        megasport run outright. The label always survives on the variant; it
        is only the EU claim that is refused.
        """
        assert normalize_size(raw) is None

    @pytest.mark.parametrize("raw,expected", [
        ("16", "16"),      # the floor -- roughly a 9-month-old
        ("17", "17"),      # the real low end of the catalogue
        ("60", "60"),      # the ceiling
        ("52.5", "52.5"),  # Sport Vision's own label for US 18; odd, but theirs
    ])
    def test_keeps_sizes_at_the_edges_of_the_range(self, raw, expected):
        assert normalize_size(raw) == Decimal(expected)

    @pytest.mark.parametrize("raw", [
        None, "", "   ",
        "BEZ VELICINA",          # dsport.mk one-size articles
        "bez velicina",
        "ONE SIZE", "UNI", "-",
        "nonsense",
    ])
    def test_no_size_is_none(self, raw):
        assert normalize_size(raw) is None

    def test_thirds_do_not_collapse(self):
        """The whole point of fraction handling.

        If 42 1/3 and 42 2/3 both parsed as 42, two different sizes would be
        merged and a shopper would be sent to buy the wrong one.
        """
        assert normalize_size("42⅓") != normalize_size("42⅔")
        assert normalize_size("44 2/3") != normalize_size("44 1/3")


class TestParsePriceMinor:
    @pytest.mark.parametrize("raw,expected", [
        ("6.799,00 ден.", 6799),   # sport-m + sizeer HTML (EU format)
        ("2.266,00", 2266),
        ("8.599,00", 8599),        # dsport product page
        ("2863.00", 2863),         # sportvision JSON-LD (US format)
        ("4072.00", 4072),         # buzz rescued JSON-LD
        ("3199", 3199),            # megasport Store API, bare integer
        ("559.2", 559),            # dsport GraphQL float
        (8599.0, 8599),
        (3999, 3999),
        ("1.234.567,89", 1234568),
    ])
    def test_mkd_zero_decimals(self, raw, expected):
        assert parse_price_minor(raw, minor_unit=0) == expected

    def test_eur_two_decimals(self):
        # Needed the moment we add HR/SI, where EUR has minor_unit = 2.
        assert parse_price_minor("84,98", minor_unit=2) == 8498
        assert parse_price_minor("1.234,50", minor_unit=2) == 123450

    @pytest.mark.parametrize("raw", [None, "", "   ", "ден.", "n/a"])
    def test_unparseable_is_none(self, raw):
        assert parse_price_minor(raw) is None

    def test_never_returns_float(self):
        value = parse_price_minor("2.863,00", minor_unit=0)
        assert isinstance(value, int)


class TestText:
    def test_translit_cyrillic_brand(self):
        assert translit_mk("Најк") == "najk"
        assert translit_mk("Адидас") == "adidas"
        assert translit_mk("Пума") == "puma"

    @pytest.mark.parametrize("title,brand,expected", [
        ("Патики Puma Caven 2.0", "Puma", "caven 2.0"),
        ("Puma Caven 2.0 за мажи", "Puma", "caven 2.0"),
        ("Adidas patiki Stan Smith", "Adidas", "stan smith"),
        ("ADIDAS PUMPA PUMP UNISEX", "Adidas", "pumpa pump"),
    ])
    def test_strips_noise_and_brand(self, title, brand, expected):
        assert clean_model_name(title, brand) == expected

    def test_slugify_cyrillic(self):
        assert slugify("Патики Puma Caven 2.0") == "patiki-puma-caven-2-0"


class TestApiPricesCarryTheirOwnScale:
    """Two WooCommerce shops, one currency, two different scales.

    megasport configures MKD with 0 decimals and sends "3199" for 3 199 den.
    e-elixir configures the same currency with 2 and sends "424000" for
    4 240 den. The raw strings are not comparable; only the pair
    (value, currency_minor_unit) is. Reading one shop's numbers with the
    other's setting is a factor of 100 on every price in the catalogue.
    """

    def test_a_shop_that_counts_whole_denars(self):
        assert parse_api_price_minor("3199", source_minor_unit=0) == 3199

    def test_a_shop_that_counts_cents(self):
        assert parse_api_price_minor("424000", source_minor_unit=2) == 4240
        assert parse_api_price_minor("565000", source_minor_unit=2) == 5650
        assert parse_api_price_minor("604000", source_minor_unit=2) == 6040

    def test_the_scales_are_not_interchangeable(self):
        """The regression this function exists for.

        Read with the wrong shop's setting, a 4 240 den perfume becomes the
        most expensive thing in the catalogue -- and it sorts that way.
        """
        wrong = parse_api_price_minor("424000", source_minor_unit=0)
        right = parse_api_price_minor("424000", source_minor_unit=2)
        assert wrong == 424_000
        assert right == 4_240
        assert wrong == right * 100

    def test_a_half_denar_rounds_rather_than_truncates(self):
        # MKD has no subunit in our model, so something has to give. Rounding
        # matches parse_price_minor; truncation would under-report a price.
        assert parse_api_price_minor("424050", source_minor_unit=2) == 4241
        assert parse_api_price_minor("424049", source_minor_unit=2) == 4240

    def test_a_target_scale_other_than_zero(self):
        # EUR at minor_unit 2, the moment we add HR/SI: no rescale at all.
        assert parse_api_price_minor(
            "8498", source_minor_unit=2, target_minor_unit=2) == 8498

    @pytest.mark.parametrize("raw", [None, "", "   ", "n/a"])
    def test_unparseable_is_none(self, raw):
        assert parse_api_price_minor(raw, source_minor_unit=2) is None

    def test_a_displayed_price_is_refused_not_guessed(self):
        """Never quietly fall back to the other parser.

        If a payload ever carries "4.240,00 den." here, the honest answer is
        "unknown". Re-reading it as a displayed price is the exact confusion
        this function was added to prevent, and a wrong price is far harder
        to notice than a missing one.
        """
        assert parse_api_price_minor(
            "4.240,00 ден.", source_minor_unit=2) is None

    def test_numeric_input_works_too(self):
        assert parse_api_price_minor(424000, source_minor_unit=2) == 4240
        assert parse_api_price_minor(3199.0, source_minor_unit=0) == 3199

    def test_a_negative_scale_is_a_bug_not_a_price(self):
        with pytest.raises(ValueError):
            parse_api_price_minor("1", source_minor_unit=-1)

    def test_never_returns_float(self):
        assert isinstance(
            parse_api_price_minor("424000", source_minor_unit=2), int)

