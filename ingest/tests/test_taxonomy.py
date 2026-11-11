"""Category classification, and the catalogue names it goes with.

Every title here is a real one from the live catalogue. The bug these guard
against was found by the serving API, not by the pipeline: a pack of socks was
filed under ``sneakers`` and named "Adidas Gh0331 Chorapi Act Core Mid Crew
Sock 3p Megasport". Matching had worked perfectly; the product page simply
read as nonsense.
"""
from __future__ import annotations

import pytest

from mkagg.normalize import clean_model_name
from mkagg.taxonomy import (FOOTWEAR_SLUGS, KNOWN_SLUGS, classify,
                            is_footwear)


class TestClassifyRealTitles:
    @pytest.mark.parametrize("title,expected", [
        # megasport prefixes every title with the article code and its own
        # category word, which is where the mislabelling came from.
        ("GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport", "socks"),
        ("7312-200 Чорапи PUMA SPORT 3P - Megasport", "socks"),
        ("JQ2626 Патики GALAXY 7 M - Megasport", "sneakers"),
        ("KJ1737 Патики Adidas RESPONSE RUNNER 2 - Megasport", "sneakers"),
        ("857797631I-990 ICEPEAK IRWINTON SKI HELANKI/CR", "leggings"),
        ("392290-02 Патики Puma Caven 2.0 - Megasport", "sneakers"),
        ("Nike Патики Vomero 18", "sneakers"),
        ("adidas Патики Stan Smith", "sneakers"),
    ])
    def test_classifies(self, title, expected):
        assert classify(title) == expected

    def test_socks_beat_sneakers_when_both_words_appear(self):
        """Rule order matters: this title contains BOTH category words.

        megasport writes "Чорапи" as the category but the model name itself
        says "SOCK", and a sneaker-shaped tree would happily take the first
        footwear-looking match.
        """
        title = "GH0331 Чорапи ACT CORE MID CREW SOCK 3P Патики - Megasport"
        assert classify(title) == "socks"

    def test_unknown_title_returns_none(self):
        """The honest case, and the whole point of the fix.

        Nothing in this title names a category, so nothing is claimed.
        Defaulting to a plausible value is exactly how the socks got in.
        """
        assert classify("ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ") is None
        assert classify("Adidas HANDBALL SPEZIAL") is None
        assert classify(None) is None
        assert classify("") is None

    def test_url_is_a_second_source(self):
        """dsport's path carries the category when its title does not."""
        assert classify(
            "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ",
            url="https://www.dsport.mk/muskarci/obuca/cizme/adidas-terrex-kj8942",
        ) == "boots"

    def test_both_scripts_match(self):
        assert classify("Патики Nike Air Max") == "sneakers"
        assert classify("Patiki Nike Air Max") == "sneakers"
        assert classify("Чорапи Nike") == "socks"
        assert classify("Chorapi Nike") == "socks"

    def test_every_returned_slug_is_one_we_seeded(self):
        """A typo in the rules must fail here, not silently null a category."""
        titles = ["Патики x", "Чорапи x", "Хеланки x", "Чизми x", "Папучи x",
                  "Обувки x", "Тренерки x", "Капа x", "Топка x", "Runner x"]
        for title in titles:
            slug = classify(title)
            assert slug is None or slug in KNOWN_SLUGS, (title, slug)

    def test_footwear_predicate(self):
        assert is_footwear("sneakers")
        assert is_footwear("boots")
        assert not is_footwear("socks")
        assert not is_footwear("leggings")
        assert not is_footwear(None)
        assert FOOTWEAR_SLUGS < KNOWN_SLUGS


class TestCatalogueNames:
    """clean_model_name with the mpn and merchant arguments."""

    @pytest.mark.parametrize("title,brand,mpn,merchant,expected", [
        ("GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport",
         "Adidas", "GH0331", "Megasport", "act core mid crew sock 3p"),
        ("7312-200 Чорапи PUMA SPORT 3P - Megasport",
         "Puma", "7312-200", "Megasport", "sport 3p"),
        ("JQ2626 Патики GALAXY 7 M - Megasport",
         "Adidas", "JQ2626", "Megasport", "galaxy 7 m"),
        ("392290-02 Патики Puma Caven 2.0 - Megasport",
         "Puma", "392290-02", "Megasport", "caven 2.0"),
        ("Nike Патики Vomero 18", "Nike", "IR1812-012", "Buzz Sneakers",
         "vomero 18"),
    ])
    def test_strips_code_category_and_shop(self, title, brand, mpn, merchant,
                                            expected):
        assert clean_model_name(title, brand, mpn=mpn,
                                merchant=merchant) == expected

    def test_model_numbers_survive(self):
        """The reason the code is matched exactly rather than by pattern.

        A regex loose enough to catch "7312-200" would also eat "2.0",
        "7" and "90".
        """
        assert clean_model_name("392290-02 Патики Puma Caven 2.0 - Megasport",
                                "Puma", mpn="392290-02",
                                merchant="Megasport") == "caven 2.0"
        assert clean_model_name("Nike Патики Air Max 90", "Nike",
                                mpn="DH2987-001") == "air max 90"
        assert clean_model_name("JQ2626 Патики GALAXY 7 M - Megasport",
                                "Adidas", mpn="JQ2626",
                                merchant="Megasport") == "galaxy 7 m"

    def test_the_word_sock_is_kept(self):
        """It is part of the real model name, unlike the shop's category word."""
        name = clean_model_name("GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport",
                                "Adidas", mpn="GH0331", merchant="Megasport")
        assert "sock" in name
        assert "chorapi" not in name

    def test_code_spelling_variants_are_removed(self):
        """Shops write the same code with and without its separator."""
        for written in ("7312-200", "7312 200", "7312200"):
            title = f"{written} Чорапи PUMA SPORT 3P - Megasport"
            assert clean_model_name(title, "Puma", mpn="7312-200",
                                    merchant="Megasport") == "sport 3p"

    def test_shop_suffix_only_stripped_at_the_end(self):
        """A model that contains the shop's word must survive.

        Contrived, but the end-anchor is what makes the rule safe to apply at
        all: an unanchored strip would mangle any title mentioning the shop.
        """
        assert clean_model_name("Megasport Edition Runner", "Nike",
                                merchant="Megasport") == "megasport edition runner"

    def test_still_works_without_the_new_arguments(self):
        """The fuzzy matcher's original two-argument call is unchanged."""
        assert clean_model_name("Патики Puma Caven 2.0", "Puma") == "caven 2.0"

    def test_empty_title(self):
        assert clean_model_name("", "Puma", mpn="X", merchant="Y") == ""
        assert clean_model_name(None, None) == ""
