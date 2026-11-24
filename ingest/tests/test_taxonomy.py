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
                            PARENT_SLUGS, classify, classify_gender,
                            is_footwear, read_declared_audience)


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
        # Reads as a jacket since V18 gave apparel its own leaves; before
        # that the whole vertical was one `apparel` bucket.
        assert classify("Nike Air Zoom Runner Jacket") == "jackets"

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
            "IP3992 Штитник TIRO SG EU CLB - Megasport") == "protective_gear"
        assert classify("Adidas F50 LEAGUE SG") == "cleats"

    def test_retired_slugs_are_gone(self):
        """A rule returning a slug V17 deleted would null the category."""
        for gone in ("running", "boots", "slides", "sandals"):
            assert gone not in KNOWN_SLUGS

    def test_known_slugs_are_exactly_the_seeded_ones(self):
        """Every slug this module may return, matching V4 + V10 + V17 + V18
        + V23 + V27.

        The apparel leaves joined in V18, the Опрема ones in V23, the
        fragrance pair in V27. `equipment` left in V23: that kind was folded
        into `accessory` and its one leaf deleted, so a rule still returning
        it would null the category rather than set it.
        """
        assert KNOWN_SLUGS == {
            "footwear", "sneakers", "cleats", "shoes_boots", "slides_sandals",
            "apparel", "tshirts", "hoodies", "jackets", "trousers",
            "tracksuits", "shorts", "leggings", "sports_bras", "underwear",
            "dresses_skirts", "swimwear",
            "accessories", "socks", "caps_hats", "bags_backpacks", "wallets",
            "protective_gear", "swim_gear", "balls_training",
            "bottles_thermos", "skates_scooters", "shoe_care_laces",
            "other_accessories",
            "fragrances", "perfume",
        }

    def test_every_vertical_has_a_parent_this_module_will_not_overwrite(self):
        """PARENT_SLUGS is the guard that keeps an umbrella off a leaf.

        A vertical whose root is missing from the set would let a department
        page overwrite a product's real category -- the 1 010-product
        Текстил bug. Fragrances joined in V27 and needs the same guard.
        """
        assert PARENT_SLUGS == {"footwear", "apparel", "accessories",
                                "fragrances"}
        assert PARENT_SLUGS < KNOWN_SLUGS

    def test_the_retired_equipment_slug_is_gone(self):
        """V23 deleted the category row, so returning it would set NULL."""
        assert "equipment" not in KNOWN_SLUGS


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
        ("Adidas PREDATOR голмански ракавици", "protective_gear"),
        ("Adidas PREDATOR GLOVES", "protective_gear"),
        ("Штитник PREDATOR SG", "protective_gear"),
        ("Adidas TERREX јакна за планинарење", "jackets"),
        ("Adidas F50 Топка", "balls_training"),
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


class TestApparelFromTitles:
    """The eleven V18 leaves, read from a product name.

    The facet decides first -- `derive_category` takes the shop's own
    department over any keyword -- so these rules matter for the products no
    apparel facet reached. On the aspnet shops that is a large group: their
    navigation links only 12 of the 26 subgroups the facet sidebar counts,
    so Градник, Пододело and Дресови have no facet to be found through and
    arrive as clothing of unspecified kind.
    """

    @pytest.mark.parametrize("title,expected", [
        ("Nike Маица Sportswear Club", "tshirts"),
        ("Adidas Мајица со долги ракави", "tshirts"),
        ("Nike Дрес Dri-FIT Academy", "tshirts"),
        ("Bratot Кошула Overshirt", "tshirts"),
        ("Puma Дуксер Essentials Logo", "hoodies"),
        ("Adidas Блузони Tiro 24", "hoodies"),
        ("4F Полари", "hoodies"),
        ("Nike Јакна Windrunner", "jackets"),
        ("Adidas Елек Terrex", "jackets"),
        ("Софтшел Regatta", "jackets"),
        ("Шушкавци Adidas Tiro", "jackets"),
        ("Nike Панталони Club Fleece", "trousers"),
        ("Adidas Долен дел тренерки Tiro", "trousers"),
        ("4F Ски панталони", "trousers"),
        ("Levi Фармерки 501", "trousers"),
        ("Adidas Тренерка Tiro 24", "tracksuits"),
        ("Nike Летни комплети за деца", "tracksuits"),
        ("Nike Шорцеви Dri-FIT", "shorts"),
        ("Хеланки Nike One", "leggings"),
        ("Puma Бициклистички", "leggings"),
        ("Nike Pro Градник", "sports_bras"),
        ("Adidas Боди", "sports_bras"),
        ("Nike Фустан Sportswear", "dresses_skirts"),
        ("Adidas Сукња Tennis", "dresses_skirts"),
        ("Puma Здолништа", "dresses_skirts"),
        ("Craft Пододело", "underwear"),
        ("Nike Долна облека", "underwear"),
    ])
    def test_reads_the_leaf(self, title, expected):
        assert classify(title) == expected

    @pytest.mark.parametrize("title,expected", [
        # The narrower phrase has to be tried first in each of these pairs,
        # because one word contains the other.
        ("Шорцеви за пливање Speedo", "swimwear"),
        ("Nike Шорцеви Dri-FIT", "shorts"),
        ("Костим за капење Arena", "swimwear"),
        ("Adidas Долен дел тренерки", "trousers"),
        ("Adidas Тренерка Tiro", "tracksuits"),
        ("4F Ски панталони", "trousers"),
    ])
    def test_the_narrower_phrase_wins(self, title, expected):
        assert classify(title) == expected

    def test_clothing_of_unspecified_kind_is_a_real_answer(self):
        """The parent, exactly as `footwear` is for shoes."""
        assert classify("Nike Активна облека") == "apparel"

    def test_a_silent_title_still_says_nothing(self):
        assert classify("Nike NSW Club 24") is None


class TestApparelWordsThatAreAlsoShoes:
    """Found by running the rules over all 13,044 live titles.

    The apparel block runs before the footwear rules, so an English word
    that is also a shoe model name files trainers as clothing. Three did,
    and each is now absent from the rules -- the shops write these
    categories in Macedonian anyway, so nothing was lost.
    """

    @pytest.mark.parametrize("title", [
        "Skechers ILLUMI-BRIGHTS - POLAR STEPPE",   # was hoodies, via polar
        "Skechers Upper Neo Jogger",                # was trousers, via jogger
    ])
    def test_a_shoe_is_not_clothing(self, title):
        assert classify(title) is None

    def test_a_boot_called_short_is_still_a_boot(self):
        """UGG's "Чизми CLASSIC SHORT II" read as shorts, beating its own
        Чизми, because the apparel block runs first."""
        assert classify("UGG Чизми CLASSIC SHORT II") == "shoes_boots"

    def test_the_macedonian_categories_still_work(self):
        """The fix was to drop the English singulars, not the categories."""
        assert classify("4F Полари") == "hoodies"
        assert classify("Nike Шорцеви") == "shorts"

    def test_a_low_top_trainer_is_not_a_sports_bra(self):
        """"Топ" transliterates to "top", and this block runs before the
        footwear rules -- so a bare "top" would file every low-top trainer
        as a crop top. The shops' own `top` facet still reaches the
        category; only the title rule declines to."""
        assert classify("Nike Court Borough Low Top") is None
        assert classify("NIKE COURT VISION LOW TOP") is None
        assert classify("Nike Dri-FIT Crop Top") == "sports_bras"

    def test_a_parka_is_not_a_football_boot(self):
        """A real row: product 2009 was filed as `cleats`.

        "NIKE W NSW TF RPL REVIVAL PARKA" -- the TF is Nike's Therma-FIT,
        and the cleats rule reads TF as turf studs. Its own URL says
        PodGrupa=492, sizeer's jackets. With apparel read before footwear
        the title now lands correctly, and re-deriving fixes the row.
        """
        assert classify("NIKE W NSW TF RPL REVIVAL PARKA") == "jackets"


class TestTheWordTheShopsPrintOnShortLabels:
    """"Parfum", which the perfume rule did not know.

    The rule held the Macedonian transliterations -- parfem, parfemi,
    parfumi -- and the full phrase "eau de parfum", but not the bare word.
    So a title saying only "Parfum" matched nothing in the fragrance block,
    fell through to apparel, and matched whatever English word happened to
    be in the product's name.

    Two real rows: `ralph-lauren-polo-blue-parfum-147011` and
    `ralph-lauren-polo-red-parfum-1470` were filed as `tshirts`, via `polo`.
    They sat in Облека, were unreachable from Парфеми, and put a perfumery
    on the clothing page's shop rail. Their own shelf said "Машки Parfum"
    and could not rescue them, because that classified to nothing for the
    very same reason.
    """

    def test_a_polo_fragrance_is_not_a_polo_shirt(self):
        assert classify("Ralph Lauren Polo Blue Parfum") == "perfume"
        assert classify("Ralph Lauren Polo Red Parfum") == "perfume"

    def test_a_polo_shirt_still_is_one(self):
        """The whole risk of the fix, and it is not realised: `polo` still
        decides a title that does not also name a strength."""
        assert classify("Ralph Lauren Polo majica") == "tshirts"
        assert classify("PUMA ESS Polo") == "tshirts"

    def test_the_shelf_resolves_on_its_own_now(self):
        """What made the two rows unrecoverable. `derive` ranks a shop's
        own shelf above the title, so this is the signal that should have
        decided it, and it classified to nothing."""
        assert classify("Машки Parfum") == "perfume"
        assert classify("Женски Parfum") == "perfume"

    def test_the_longer_phrases_still_work(self):
        """Bare "parfum" subsumes "eau de parfum", and the triple stays in
        the rule for readability. This is the check that it still reads."""
        assert classify("Polo Blue Eau de Parfum") == "perfume"
        assert classify("Versace Eau de toilette") == "perfume"
        assert classify("Acqua di Parma Eau de Cologne") == "perfume"

    def test_a_strength_that_names_a_fragrance_is_still_refused(self):
        """Unchanged, and it must stay that way: "elixir" and "intense"
        name a bottle rather than an article type, and `mkagg.fragrance`
        keeps them in the line name for that reason. The shelf carries the
        category for these -- measured, 106 live titles at the two
        perfumeries name no strength at all, and that is honest."""
        assert classify("Giorgio Armani Code Elixir") is None
        assert classify("Christina Aguilera Violet Noir") is None


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


class TestTheShopsSectionIsConsultedPerRule:
    """A weak word in a title must not outrank the shop's own section.

    Every rule is now tried against the title and the URL together, rather
    than the whole rule list being spent on the title first. These are the
    live offers that behaviour was wrong for.
    """

    #: ``tf`` is in the cleats list for *turf*. Nike abbreviates Therma-FIT
    #: identically, so these garments were football boots.
    THERMA_FIT = [
        ("Nike W NK TF SYN CLSSC JKT",
         "https://www.sportvision.mk/mk/jakna/8726800-nike-w-nk-tf", "jackets"),
        ("Nike M NK TF FLEX FLC FZ HD",
         "https://www.sportvision.mk/mk/dukser/8724981-nike-m-nk-tf", "hoodies"),
        ("Nike M NK TF RPL CHLLGR PANT",
         "https://www.sportvision.mk/mk/dolen-del-trenerki/8672285-x",
         "trousers"),
        ("Nike W NK ONE TF HZ TOP POLAR",
         "https://www.sportvision.mk/mk/maica-dolgi-rakavi/8705852-x",
         "tshirts"),
        ("Adidas TF BASE TIGHT",
         "https://www.sportvision.mk/mk/helanki/8661180-x", "leggings"),
    ]

    @pytest.mark.parametrize("title,url,expected", THERMA_FIT)
    def test_therma_fit_clothing_is_not_a_football_boot(self, title, url,
                                                        expected):
        assert classify(title, url=url) == expected

    #: The same collision from the other direction: adidas sells Terrex
    #: clothing, and ``terrex`` is a shoes_boots rule.
    TERREX_CLOTHING = [
        ("adidas Terrex Multi",
         "https://www.sportreality.mk/mk/maica/158157-adidas-terrex-multi",
         "tshirts"),
        ("adidas Terrex Polar",
         "https://www.sportvision.mk/mk/dukser/8701351-adidas-terrex-polar",
         "hoodies"),
        ("adidas Terrex Multi RAIN.RDY 2-Layer",
         "https://www.sportreality.mk/mk/jakna/161132-adidas-terrex-multi",
         "jackets"),
        ("adidas Terrex",
         "https://www.sportvision.mk/mk/dolen-del-trenerki/8697272-x",
         "trousers"),
    ]

    @pytest.mark.parametrize("title,url,expected", TERREX_CLOTHING)
    def test_terrex_clothing_is_not_a_hiking_boot(self, title, url, expected):
        assert classify(title, url=url) == expected

    def test_turf_boots_keep_their_keyword(self):
        """The fix must not be a keyword removal: 124 live offers say TF and
        mean turf, 33 of them with no other football word to fall back on."""
        for title in ("Nike Tiempo Maestro Club TF", "Umbro Libero TF",
                      "Adidas COPA PURE IV CLUB TF", "Lotto MEDO KIDS TF"):
            assert classify(title) == "cleats", title
        assert classify(
            "IE7525 Патики COPA PURE 2 CLUB TF - Megasport",
            url="https://megasportonlineshop.com/p/patiki-copa-pure-2-club-tf/"
        ) == "cleats"

    def test_a_shoe_section_still_names_the_shoe(self):
        """The inversion must not hand apparel anything that is footwear."""
        assert classify(
            "Salomon Shoes Exeo 2 GTX",
            url="https://www.sportvision.mk/mk/patiki/8717840-salomon-shoes"
        ) == "sneakers"
        assert classify(
            "Timberland MID LACE SNEAKER",
            url="https://www.sportvision.mk/mk/konduri/8731146-timberland"
        ) == "shoes_boots"

    def test_a_material_word_does_not_beat_the_section(self):
        """99 offers: "Fleece Jogger" read as a hoodie because of "fleece",
        while the shop shelves it under tracksuit bottoms."""
        assert classify(
            "Under Armour UA Essential Fleece Jogger",
            url="https://www.sportreality.mk/mk/dolen-del-trenerki/180136-x"
        ) == "trousers"

    def test_the_title_still_decides_when_the_url_says_nothing(self):
        """aspnet shops put no category in the path, only query parameters."""
        assert classify(
            "IN5590 Хеланки ADIDAS TF BASE TIGHT - Megasport",
            url="https://sport-m.mk/ProductCatalog?Segment=03&Grupa=02"
        ) == "leggings"


class TestAccessoryLeaves:
    """The ten Опрема buckets V23 seeded, and the order that keeps them apart.

    Every one of these is a facet that appeared on at least two of the six
    shops during recon. The failures they guard are all the same shape: a
    narrow category whose name contains a broader one.
    """

    @pytest.mark.parametrize("title,expected", [
        ("Nike Чорапи Everyday Cushion 3P", "socks"),
        ("adidas Качкет Baseball Cap", "caps_hats"),
        ("Зимска капа Nike Beanie", "caps_hats"),
        ("Ски бандана Megasport", "caps_hats"),
        ("Puma Ранец Phase Backpack", "bags_backpacks"),
        ("adidas Торбичка Waist Bag", "bags_backpacks"),
        ("Вреќа за тренинг adidas", "bags_backpacks"),
        ("Кациги Smith Ski Helmet", "protective_gear"),
        ("Голмански ракавици adidas", "protective_gear"),
        ("Костобрани Nike", "protective_gear"),
        ("Ролери Rollerblade", "skates_scooters"),
        ("Тротинет Micro", "skates_scooters"),
        ("adidas Топка Champions League", "balls_training"),
        ("Држачи за склекови", "balls_training"),
        ("Термос Stanley 1L", "bottles_thermos"),
        ("Врвки за патики 120cm", "shoe_care_laces"),
        ("Заштитна маска за лице", "other_accessories"),
    ])
    def test_reads_the_leaf(self, title, expected):
        assert classify(title) == expected

    @pytest.mark.parametrize("title,expected", [
        # Each of these contains a broader category's word, and must not be
        # read as it.
        ("Капа за пливање Arena", "swim_gear"),       # contains "капа"
        ("Наочари за пливање Speedo", "swim_gear"),   # contains "наочари"
        ("Опрема за пливање Arena", "swim_gear"),
    ])
    def test_swimming_outranks_the_word_inside_it(self, title, expected):
        assert classify(title) == expected

    def test_a_wallet_is_not_a_backpack(self):
        """The whole reason `wallets` can be a leaf at all.

        megasport publishes one facet, "Ранци и Паричници", for both. On that
        shop a wallet is recognisable only by its own name, so the rule has
        to run before `bags_backpacks` rather than after it.
        """
        assert classify("Nike Паричник Elemental") == "wallets"
        assert classify("adidas Wallet Essentials") == "wallets"
        assert classify("Nike Ранец Elemental") == "bags_backpacks"

    MEGA_COMBINED = ("https://megasportonlineshop.com/kategorija/mazhi/"
                     "oprema-mazhi/ranci-i-parichnici/")

    def test_the_combined_facet_falls_back_to_bags(self):
        """A megasport item whose title names neither is a bag, not a wallet.

        The facet says "Ранци и Паричници" and the title says nothing, so the
        honest answer is the broader of the two.

        This is also the regression that made the `wallets` rule singular.
        The facet slug contains "parichnici", so a plural keyword matched the
        URL of every product in it -- and `wallets` runs first -- which filed
        the shop's entire backpack range as wallets.
        """
        assert classify("Nike Elemental Premium",
                        url=self.MEGA_COMBINED) == "bags_backpacks"

    def test_a_named_wallet_still_wins_inside_that_facet(self):
        """The other half: the split has to survive the fallback."""
        assert classify("Nike Паричник Elemental",
                        url=self.MEGA_COMBINED) == "wallets"

    def test_equipment_of_unnamed_kind_still_answers(self):
        """The parent is a real answer, exactly as `footwear` is for shoes.

        Sport Vision's sport-specific shelves are the honest case for it:
        "Опрема за фудбал" holds balls, shin guards and gloves together, so
        no leaf is truer than the parent. "Опрема за тренинг" is deliberately
        not among them -- the probe found that one, and training gear is
        `balls_training`.
        """
        assert classify("adidas Додатоци Training") == "accessories"
        for section in ("oprema-za-fudbal", "oprema-za-ping-pong",
                        "ostanata-oprema"):
            assert classify(
                None,
                url=f"https://www.sportvision.mk/mk/{section}/x",
            ) == "accessories", section
        assert classify("Опрема за тренинг") == "balls_training"

    def test_a_shoe_is_still_a_shoe(self):
        """The accessory block runs before the footwear rules, so a word that
        appears in both would quietly empty the footwear catalogue."""
        assert classify("Патики Nike Air Max") == "sneakers"
        assert classify("Копачки PREDATOR CLUB FG") == "cleats"
        assert classify("Чизми UGG CLASSIC SHORT II") == "shoes_boots"

    def test_clothing_is_not_equipment(self):
        """The apparel block runs first and has to keep winning."""
        assert classify("Nike Јакна Windrunner") == "jackets"
        assert classify("adidas Маица Essentials") == "tshirts"
        assert classify("Костим за капење Arena") == "swimwear"


class TestWhatTheSlugProbeFound:
    """Real section names, read off the shops rather than guessed.

    Each of these answered 200 during the Опрема slug probe and was then
    classified; these are the ones that came back wrong or blank.
    """

    def test_a_cleaning_spray_is_not_a_shoe(self):
        """The worst of them. Sizeer files "Средство за чистење на обувки"
        under its accessories group, and the обувки at the end carried the
        whole phrase into the footwear umbrella -- so a bottle of cleaner
        classified as footwear, which is a vertical away from the truth."""
        assert classify("Средство за чистење на обувки") == "shoe_care_laces"
        assert classify("Обувки за вода") == "slides_sandals"
        assert classify("Патики Nike Air Max") == "sneakers"

    @pytest.mark.parametrize("label", [
        "Средство за заштита од влага",
        "Средство за отстранување на непријатни миризби",
        "Комбинирана четка за велур кожа",
    ])
    def test_the_rest_of_the_shoe_care_shelf(self, label):
        """Its three siblings matched no rule at all."""
        assert classify(label) == "shoe_care_laces"

    @pytest.mark.parametrize("slug,expected", [
        ("pribor-i-dodatoci-za-obuvki", "shoe_care_laces"),
        ("oprema-za-trening", "balls_training"),
        ("kaciga", "protective_gear"),
        ("kacketi-i-kapi", "caps_hats"),
        ("naocari-za-plivanje", "swim_gear"),
        ("corapi", "socks"),
        ("sise-za-voda", "bottles_thermos"),
    ])
    def test_sportvision_sections_as_the_shop_spells_them(self, slug,
                                                          expected):
        """Enumerated from its own Опрема page. Note the spellings: this
        shop drops the `h` the transliterator produces, which is how
        `/mk/sorc/` once hid 835 offers."""
        assert classify(
            None, url=f"https://www.sportvision.mk/mk/{slug}/x") == expected

    @pytest.mark.parametrize("label,expected", [
        ("Ролери", "skates_scooters"),
        ("Скироли", "skates_scooters"),
        ("Тротинети", "skates_scooters"),
        ("Голмански ракавици", "protective_gear"),
        ("Костобрани", "protective_gear"),
        ("Капи за пливање", "swim_gear"),
        ("Торбички", "bags_backpacks"),
        ("Зимски капи", "caps_hats"),
        ("Бандани", "caps_hats"),
        ("Шишиња", "bottles_thermos"),
        ("Термос", "bottles_thermos"),
        ("Баланс топка", "balls_training"),
        ("Држачи за склекови", "balls_training"),
        ("Друго", "other_accessories"),
        ("Заштитна маска за лице", "other_accessories"),
    ])
    def test_the_aspnet_subgroup_dictionary(self, label, expected):
        """Sport-M and Sizeer publish their whole subgroup list on every
        catalogue page; these are the accessory half of it, verbatim."""
        assert classify(label) == expected


class TestWhatTheCatalogueDoesNotCarry:
    """Four kinds excluded by decision, enforced rather than documented.

    Leaving a subgroup out of a facet plan is not enough, because a facet
    plan is not the only way in: Sport-M's Спецификации parser reads
    `Подгрупа` off the product page, and "Додатоци за миленици" matches the
    `accessories` umbrella. A dog collar reached by any other shelf would
    have been filed as equipment of unspecified kind.
    """

    @pytest.mark.parametrize("label", [
        "Додатоци за миленици",
        "Funko POP! фигури",
        "Велосипеди",
        "Часовници",
        "Garmin Forerunner 55 часовник",
    ])
    def test_an_excluded_kind_stays_uncategorised(self, label):
        """None, not a plausible leaf. Uncategorised is visible in a count;
        filed somewhere plausible is not."""
        assert classify(label) is None

    def test_the_pet_shelf_no_longer_reaches_the_umbrella(self):
        """The leak this exists for: "Додатоци" alone matches `accessories`,
        so the pet shelf resolved to the parent before it was excluded."""
        assert classify("Додатоци за миленици") is None
        assert classify("adidas Додатоци Training") == "accessories"

    def test_a_url_carrying_one_is_excluded_too(self):
        assert classify(
            None, url="https://sizeer.com.mk/mk/funko-pop/1-x") is None

    def test_cycling_clothing_is_untouched(self):
        """The near miss worth pinning: Бициклистички is not Велосипед, and
        cycling shorts are a live apparel leaf with 56 products."""
        assert classify("Бициклистички шорц") == "leggings"
        assert classify(
            None, url="https://www.sportvision.mk/mk/biciklisticki/1-x",
        ) == "leggings"

    def test_ordinary_equipment_still_classifies(self):
        """The guard runs before every rule, so a false positive here would
        silently empty whole shelves."""
        assert classify("Nike Ранец Elemental") == "bags_backpacks"
        assert classify("adidas Топка Champions League") == "balls_training"
        assert classify("Патики Nike Air Max") == "sneakers"


class TestSwimIsAGarmentWordNotAGearWord:
    """Where bare "swim" sits in the rule order, and why it moved.

    It used to live with `swim_gear`, which runs after every garment rule.
    So a title only reached it when no garment rule had claimed the title
    first -- and `underwear` claimed "PUMA SWIM WOMEN HIGH WAIST BRIEF 1P"
    on `brief`, filing nine swimsuits as underwear. Moving the word to
    `swimwear`, above `underwear`, changed 109 of 31 976 live title/URL
    pairs; 107 were corrections.
    """

    @pytest.mark.parametrize("title", [
        # The nine reported, and what they were filed as.
        "PUMA SWIM WOMEN HIGH WAIST BRIEF 1P",
        "PUMA SWIM WOMEN V-SHAPE BRIEF 1P",
        # Filed as plain shorts: 62 of them.
        "Karl Kani Retro Striped Swim Shorts light blue/white/blue",
        "7269-4XP-99 Шорцеви за капење MENS SWIM.SHORTS - Megasport",
        # Filed as accessories, under swim *gear*: 38 of them.
        "4F SWIM SUIT",
        "Champion Lady Swim One Piece",
        "Colmar Swim Trunks",
        "PUMA SWIM MEN WAVE AOP SHORT SHORTS 1P",
    ])
    def test_a_swim_garment_is_swimwear(self, title):
        assert classify(title) == "swimwear"

    @pytest.mark.parametrize("title", [
        # The words that only ever mean gear keep it, and they are what the
        # shops actually write.
        "Капа за пливање Arena",
        "Наочари за пливање Speedo",
        "Опрема за пливање Arena",
        "Arena Swimming Goggles",
        "Маска и пераи Arena",
    ])
    def test_gear_is_still_gear(self, title):
        assert classify(title) == "swim_gear"

    def test_english_gear_titles_were_always_silent(self):
        """Not a regression, and worth stating so it is not read as one.

        "J2C SET MASK, SNORKEL AND FINS" names its gear in English, which no
        keyword here carries -- the list is Macedonian because that is what
        the shops write. It was silent before this change and still is; the
        live product is `swim_gear` on the strength of its shelf,
        `maska-i-perai`, which is the source that should decide anyway.
        """
        assert classify("J2C SET MASK, SNORKEL AND FINS") is None

    def test_a_brief_with_no_swim_is_still_underwear(self):
        """The rule that was winning is not weakened, only out-ordered."""
        assert classify("PUMA WOMEN HIGH WAIST BRIEF 1P") == "underwear"
        assert classify("Долна облека Puma") == "underwear"

    def test_swim_does_not_reach_past_a_narrower_garment(self):
        """`shorcevi za plivanje` is still read as the phrase it is.

        Rule order inside the apparel block is load-bearing -- the file says
        so -- and this is the pair that proves bare "swim" did not flatten it.
        """
        assert classify("Шорцеви за пливање Speedo") == "swimwear"
        assert classify("Костим за капење Arena") == "swimwear"


class TestWhoTheShopSaysItIsFor:
    """`Пол` and `Возраст`, and why the age band decides.

    Both platforms publish both rows on every product page. Read in the
    wrong order they disagree, and the disagreement is not rare: Sport
    Vision prints `Пол: Унисекс` beside `Возраст: За мали деца (4-10 год.)`
    on children's socks, and 151 of the 712 products under Опрема -> Чорапи
    are children's.
    """

    def test_the_age_band_beats_the_department(self):
        assert read_declared_audience(
            "Унисекс", "За мали деца (4-10 год.)") == "kids"
        assert read_declared_audience("Машки", "За бебиња (0-4 год.)") == "kids"

    def test_an_adult_band_lets_the_department_answer(self):
        assert read_declared_audience("Машки", "За возрасни") == "men"
        assert read_declared_audience("Женски", "За возрасни") == "women"
        assert read_declared_audience("Унисекс", "За возрасни") == "unisex"

    def test_a_kids_department_is_read_too(self):
        """Sport Vision splits children by sex: Деца, Деца-девојчиња,
        Деца-момчиња. All three are the kids department."""
        for pol in ("Деца", "Деца-девојчиња", "Деца-момчиња"):
            assert read_declared_audience(pol, None) == "kids", pol

    def test_the_teenager_band_transliterates(self):
        """`translit_mk` renders џ as `dj`, so "тинејџери" arrives as
        "tinejdjeri". A rule written for "tinejdzeri" matches nothing, and
        23 Sport Vision products carry this band."""
        assert read_declared_audience(
            None, "За тинејџери (8-14 год.)") == "kids"
        assert read_declared_audience(
            None, "За тинејџери (од 8-16 год.)") == "kids"

    def test_unisex_survives_here_where_a_title_could_not_say_it(self):
        """`classify_gender` is forbidden from returning unisex, because a
        title cannot show it. A shop writing `Пол: Унисекс` states it."""
        assert read_declared_audience("Унисекс", None) == "unisex"

    def test_a_contradiction_is_refused_rather_than_guessed(self):
        """`Пол: Деца` under `Возраст: За возрасни` cannot both be true,
        and the honest answer is neither."""
        assert read_declared_audience("Деца", "За возрасни") is None

    def test_silence_stays_silence(self):
        assert read_declared_audience(None, None) is None
        assert read_declared_audience("", "") is None
