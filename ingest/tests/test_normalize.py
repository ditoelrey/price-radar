"""Normalisation tests.

Every case here is a real string observed on a target store during recon, not
an invented edge case. That is why they are worth keeping.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from mkagg.normalize import (clean_model_name, normalize_size, normalize_sku,
                             parse_price_minor, sku_base, slugify, translit_mk)


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
        ("UK 8.5", "8.5"),
        ("41-42", "41"),         # range -> lower bound
    ])
    def test_parses(self, raw, expected):
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
