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
from mkagg.taxonomy import (FOOTWEAR_SLUGS, KNOWN_GENDERS, KNOWN_SLUGS,
                            classify, classify_gender, is_footwear)


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

        Nothing in these titles names a category, so nothing is claimed.
        Defaulting to a plausible value is exactly how the socks got in.

        This case used to be "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ",
        which the Terrex model-line rule now reads as outdoor footwear. That
        is the rule doing its job, not this test weakening: the title really
        did say something, and we could not read it. The examples left here
        say nothing at all -- a silhouette name and a colourway.
        """
        assert classify("Adidas HANDBALL SPEZIAL") is None
        assert classify("adidas Supernova Rise") is None
        assert classify("Hoka Clifton UTL") is None
        assert classify(None) is None
        assert classify("") is None

    def test_url_is_a_second_source(self):
        """dsport's path carries the category when its title does not."""
        assert classify(
            "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ",
            url="https://www.dsport.mk/muskarci/obuca/cizme/adidas-terrex-kj8942",
        ) == "shoes_boots"

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
        assert is_footwear("shoes_boots")
        # The parent row is a legitimate value, not a missing one: "a shoe,
        # kind unspecified" is what 2,767 products honestly are.
        assert is_footwear("footwear")
        assert not is_footwear("socks")
        assert not is_footwear("leggings")
        assert not is_footwear(None)
        assert FOOTWEAR_SLUGS < KNOWN_SLUGS


class TestFourCanonicalBuckets:
    """V17 consolidated footwear to the four buckets MK retail navigates by.

    The shops themselves disagree about granularity -- sportm and sizeer split
    sneakers into low-top and high-top, megasport splits shoes from boots --
    and the canonical tree deliberately takes the coarser reading. These tests
    pin the merges, because a merge that silently stops working looks like a
    classifier gap rather than a taxonomy change.
    """

    @pytest.mark.parametrize("title,expected", [
        # Cleats: a category the tree had no room for until V17, although
        # every one of the four big shops publishes a Копачки facet.
        ("10421 КОПАЦКИ АДИДАС ББ1032 - Megasport", "cleats"),
        ("Adidas PREDATOR CLUB FG", "cleats"),
        ("Nike MERCURIAL FUTSAL IC", "cleats"),
        ("Патики за вештачка трева Adidas X", "cleats"),
        # Shoes and boots are one bucket now.
        ("Megasport Чизми Timberland", "shoes_boots"),
        ("11850 Кондури ADIDAS - Megasport", "shoes_boots"),
        ("SIZEER Балетанки VANS", "shoes_boots"),
        ("Мокасини Tommy Hilfiger", "shoes_boots"),
        # So are slides and sandals.
        ("JQ1234 Папучи ADILETTE - Megasport", "slides_sandals"),
        ("Сандали Teva Hurricane", "slides_sandals"),
        ("Apostolki Havaianas", "slides_sandals"),
        ("Обувки за вода Speedo", "slides_sandals"),
        # Running merged into sneakers, so the shop's own word decides and
        # both readings land in the same bucket.
        ("KJ1737 Патики Adidas RESPONSE RUNNER 2 - Megasport", "sneakers"),
        ("Nike Pegasus 41 running shoe", "sneakers"),
    ])
    def test_classifies(self, title, expected):
        assert classify(title) == expected

    def test_running_is_no_longer_its_own_bucket(self):
        """The merge retired the rule, not just the row.

        The old ``running`` rule was the only one that read the *model name*
        rather than a category word, which is how "RESPONSE RUNNER 2" became
        a running shoe while the shop selling it filed it under Патики. With
        the bucket gone, a bare model name earns nothing.
        """
        assert classify("Adidas Supernova Runner") is None
        assert classify("Nike Air Zoom Runner Jacket") == "apparel"

    def test_cleats_beat_the_generic_sneaker_word(self):
        """Rule order, same lesson as the socks.

        sportm lists turf boots as "Патики за вештачка трева" -- the generic
        sneaker word is right there in a title that means something narrower.
        """
        assert classify("Патики за вештачка трева Nike") == "cleats"

    def test_water_shoes_are_not_generic_footwear(self):
        """"Обувки за вода" contains the generic shoe noun too."""
        assert classify("Обувки за вода Adidas Altaventure") == "slides_sandals"

    def test_a_tennis_shoe_named_slide_is_not_a_slide(self):
        """Found by running the rules over all 10,731 real titles.

        Asics sells the "Court Slide", a tennis shoe. It was the only false
        positive among 44 live titles containing the word "slide" -- the rest
        are genuine slides, so the fix names the product line rather than
        weakening the rule.
        """
        assert classify("Asics COURT SLIDE 4") == "sneakers"
        assert classify("Nike Victori One Slide") == "slides_sandals"
        assert classify("Ipanema Street Slide Fem") == "slides_sandals"

    def test_a_shin_guard_is_not_a_football_boot(self):
        """Also found by running over real titles.

        "Штитник TIRO SG EU CLB" is a shin guard, and SG means soft-ground
        studs. The accessory rule has to see it first, or the footwear rules
        turn protective gear into a pair of cleats.
        """
        assert classify(
            "IP3992 Штитник TIRO SG EU CLB - Megasport") == "accessories"
        assert classify("Adidas F50 LEAGUE SG") == "cleats"

    def test_retired_slugs_are_gone(self):
        """A rule returning a slug V17 deleted would null the category."""
        for gone in ("running", "boots", "slides", "sandals"):
            assert gone not in KNOWN_SLUGS

    def test_known_slugs_are_exactly_the_seeded_ones(self):
        assert KNOWN_SLUGS == {
            "footwear", "sneakers", "cleats", "shoes_boots", "slides_sandals",
            "apparel", "leggings", "accessories", "socks", "equipment",
        }


class TestModelLines:
    """Rules that name a product line rather than a category word.

    Found by reading the "kind unspecified" bucket on the filters page: shoes
    whose titles are a brand and a model and nothing else, which no keyword
    could reach. A model line is a legitimate thing to know -- Predator has
    been a football boot for twenty-five years -- but it is also the kind of
    rule that rots, so each one is pinned here with the evidence that
    justified it.
    """

    @pytest.mark.parametrize("title", [
        "Adidas Predator Club",
        "Adidas PREDATOR CLUB IN SALA J",
        "Adidas Predator League",
        "adidas PREDATOR ELITE FT FG",
        "Adidas F50 Club",
        "Adidas F50 HYPERFAST CLUB TF",
        "Adidas F50 LEAGUE SG",
        "Adidas F50 CLUB IN SALA",
    ])
    def test_predator_and_f50_are_always_football(self, title):
        assert classify(title) == "cleats"

    @pytest.mark.parametrize("title", [
        "Adidas TERREX HYPERHIKER LOW K",
        "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ",
        "Adidas TERREX AX4 GTX W",
        "Adidas TERREX EASTRAIL 3",
        "Adidas TERREX TRAILMAKER W",
        "IF7636 Кондури за планинарење TERREX SWIFT R2 MID GTX - Megasport",
        "Grisport Calz. Dakkar Trekking Nero",
    ])
    def test_outdoor_lines_are_shoes_and_boots(self, title):
        assert classify(title) == "shoes_boots"

    def test_terrex_outranks_the_shops_own_sneaker_word(self):
        """megasport prefixes these with Патики, and they are still hikers.

        Within the title, the more specific reading wins. Across sources it
        does not: of 261 Terrex offers the shops file 228 under a sneakers
        facet, and `derive_category` takes the facet over the title, so this
        rule decides only the products no facet reached.
        """
        assert classify("HQ5823 Патики TERREX HYPERHIKER LOW K - Megasport")             == "shoes_boots"
        assert classify("BB1935 Патики ADIDAS TERREX AX2R K - Megasport")             == "shoes_boots"

    @pytest.mark.parametrize("title,expected", [
        # adidas sells Predator goalkeeper gloves and Predator shin guards.
        # Neither is in the catalogue today -- checked across all 13,049
        # offers, not one Predator, F50 or Terrex title carries a glove,
        # guard, ball or garment word -- so this is the rule order holding a
        # door shut rather than a bug being fixed.
        ("Adidas PREDATOR голмански ракавици", "accessories"),
        ("Adidas PREDATOR GLOVES", "accessories"),
        ("Штитник PREDATOR SG", "accessories"),
        ("Adidas TERREX јакна за планинарење", "apparel"),
        ("Adidas F50 Топка", "equipment"),
    ])
    def test_a_model_line_never_outranks_a_non_footwear_word(self, title,
                                                             expected):
        assert classify(title) == expected

    def test_adilette_gets_no_blanket_rule(self):
        """Deliberately absent, and the measurement is the reason.

        227 Adilette offers, of which the shops themselves file 223 under a
        Папучи or Сандали facet -- so the facet already answers it and a
        title rule would only add a way to be wrong about the handful of
        Adilette shoes and clogs that are not slides.
        """
        assert classify("Adidas Adilette Comfort") is None
        assert classify("JQ1234 Папучи ADILETTE - Megasport") ==             "slides_sandals"


class TestGenderFromTitle:
    """The weak half of gender derivation.

    Measured across the live catalogue, gender words appear in 0.4 to 4.9
    percent of men's titles and 3.9 to 32.7 percent of kids' ones, and EU
    sizes cannot separate men from women at all because 36-46 is shared. So
    this is a fallback for products no facet covered, and most of the time it
    correctly says nothing.
    """

    @pytest.mark.parametrize("title,expected", [
        ("ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ", "men"),
        ("Patiki za mazhi Nike Revolution", "men"),
        ("Патики за жени Puma Caven", "women"),
        ("Zhenski patiki Nike Court", "women"),
        ("NIKE WMNS AIR MAX 90", "women"),
        ("Патики за деца Adidas Tensaur", "kids"),
        ("Detski patiki Nike Star Runner", "kids"),
        ("Adidas Junior Predator", "kids"),
    ])
    def test_classifies(self, title, expected):
        assert classify_gender(title) == expected

    def test_silence_is_none(self):
        assert classify_gender("adidas Supernova Rise") is None
        assert classify_gender("Nike Court Vision Low Next Nature") is None
        assert classify_gender(None) is None
        assert classify_gender("") is None

    def test_never_claims_unisex(self):
        """``unisex`` is a two-facet finding, not a title reading.

        It means the shop lists this article in both an adult men's and an
        adult women's department. One title cannot show that, so this module
        must not be able to say it -- otherwise "unisex" quietly becomes the
        same fallback that NOT NULL DEFAULT 'unisex' was before V17.
        """
        assert "unisex" not in KNOWN_GENDERS
        for title in ("Patiki unisex Nike", "Adidas Stan Smith UNISEX",
                      "adidas Samba OG", "za mazhi i zheni"):
            assert classify_gender(title) != "unisex"

    def test_the_single_letter_conventions_are_not_evidence(self):
        """sportm writes "SUPERNOVA RISE W" and "TENSAUR RUN EL C".

        Those really do mean women's and children's, and we still do not read
        them: a bare "W" or "C" matches far too much to be evidence, and the
        facet that listed the product knows its department anyway.
        """
        assert classify_gender("Adidas SUPERNOVA RISE W") is None
        assert classify_gender("Adidas Tensaur Run 3.0 EL C") is None
        assert classify_gender("NIKE COURT VISION LOW NN M") is None

    def test_url_is_a_second_source(self):
        assert classify_gender(
            "ADIDAS TERREX SKYCHASER AX5",
            url="https://www.dsport.mk/muskarci/obuca/cizme/adidas-kj8942",
        ) is None
        assert classify_gender(
            "Adidas Tensaur",
            url="https://megasportonlineshop.com/kategorija/deca/obuvki/x/",
        ) == "kids"

    def test_every_returned_gender_is_in_the_enum(self):
        titles = ["za mazhi x", "za zheni x", "za deca x", "x", "unisex x"]
        for title in titles:
            got = classify_gender(title)
            assert got is None or got in KNOWN_GENDERS, (title, got)


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
