"""Reading a fragrance's identity out of two shops' different words.

Every case here is a live title from shop.schatze.mk or e-elixir.mk. The
module exists because these two shops describe one fragrance so differently
that comparing their titles directly would join almost nothing -- and
because the near-misses they stock side by side would fool anything fuzzy
enough to bridge the gap.
"""
from __future__ import annotations

import pytest

from mkagg.fragrance import (CONCENTRATIONS, NOT_CONCENTRATION, is_single_bottle,
                             line_name, read_concentration, read_gender)


def key(title, brand, shelf=None):
    """The exact-identity triple, as the matcher will build it."""
    concentration, _ = read_concentration(title)
    return (brand.lower(), line_name(title, brand), concentration)


class TestTheSameFragranceInTwoShops:
    """The join the whole vertical rests on."""

    def test_versace_pour_homme_merges(self):
        """Schatze omits the brand; e-elixir leads with it.

        Schatze keeps Versace in a separate Manufacturer field and titles
        the product "Pour Homme - edt". Comparing raw titles, these two
        share not one word in the same position.
        """
        schatze = key("Pour Homme - edt", "Versace")
        elixir = key("Versace Pour Homme Eau de toilette", "Versace")
        assert schatze == elixir == ("versace", "pour homme", "EDT")

    def test_a_full_spelling_and_an_abbreviation_are_one_strength(self):
        assert read_concentration("Eau de Parfum")[0] == "EDP"
        assert read_concentration("- edp")[0] == "EDP"
        assert read_concentration("EAU DE TOILETTE")[0] == "EDT"
        assert read_concentration("edt")[0] == "EDT"

    def test_a_macedonian_spelling_is_the_same_strength(self):
        """e-elixir writes 98 of its titles in Macedonian."""
        assert read_concentration("Gucci Guilty тоалетна вода за мажи")[0] == "EDT"
        assert read_concentration("Chanel колонска вода")[0] == "EDC"

    def test_an_escaped_apostrophe_does_not_split_a_fragrance(self):
        """154 of e-elixir's 987 names carry one.

        WooCommerce serves the curly apostrophe escaped. Left alone the
        digits survive as a word -- "la nuit de l 8217 homme" -- and the
        same fragrance at Schatze could never match it.
        """
        escaped = line_name("Yves Saint Laurent La Nuit de L&#8217;Homme "
                            "Eau de parfum", "Yves Saint Laurent")
        plain = line_name("La Nuit de L'Homme - edp", "Yves Saint Laurent")
        assert escaped == plain == "la nuit de lhomme"

    def test_an_accent_does_not_split_a_fragrance(self):
        """e-elixir writes Lancôme, Schatze writes Lancome."""
        assert line_name("Lancôme Idole Eau de parfum", "Lancôme") == "idole"
        assert line_name("Lancome Idole - Edp", "Lancome") == "idole"

    def test_a_missing_space_does_not_split_a_fragrance(self):
        """Live on Schatze: "Lattafa Fakhar For Woman -Eau de Parfum"."""
        assert (line_name("Lattafa Fakhar For Woman -Eau de Parfum", "Lattafa")
                == line_name("Lattafa Fakhar For Woman - Eau de Parfum",
                             "Lattafa"))


class TestTheFragrancesThatMustStayApart:
    """Each of these pairs is stocked side by side, at different prices."""

    def test_a_flanker_is_a_different_fragrance(self):
        assert (key("Valentino Donna Born In Roma Extradose - Parfum",
                    "Valentino")
                != key("Valentino Donna Eau de parfum", "Valentino"))

    def test_a_different_strength_is_a_different_product(self):
        assert (key("Versace Pour Homme Eau de toilette", "Versace")
                != key("Versace Pour Homme Eau de parfum", "Versace"))

    def test_pour_homme_is_not_pour_femme(self):
        assert (key("Dylan Blue Pour Femme - edp", "Versace")
                != key("Dylan Blue Pour Homme - edp", "Versace"))

    @pytest.mark.parametrize("word", ["elixir", "intense", "intensement"])
    def test_the_words_that_look_like_a_strength_and_are_not(self, word):
        assert word in NOT_CONCENTRATION
        assert word not in CONCENTRATIONS

    def test_elixir_stays_in_the_name(self):
        """"Le Male ELIXIR - Eau de Parfum" is an EDP called Le Male Elixir.

        Read Elixir as a strength and it merges with plain Le Male EDP,
        which is a different bottle at a different price.
        """
        concentration, _ = read_concentration("Le Male ELIXIR - Eau de Parfum")
        assert concentration == "EDP"
        assert line_name("Le Male ELIXIR - Eau de Parfum",
                         "Jean Paul Gaultier") == "le male elixir"
        assert (key("Le Male ELIXIR - Eau de Parfum", "Jean Paul Gaultier")
                != key("Le Male Eau de parfum", "Jean Paul Gaultier"))

    def test_intense_stays_in_the_name(self):
        assert (key("La Vie Est Belle Intensement - edp", "Lancome")
                != key("La vie est belle - edp", "Lancome"))

    def test_a_strength_nobody_stated_is_not_guessed(self):
        """"Giorgio Armani Code Elixir" names no strength, and 8 live
        e-elixir products are like it. Defaulting to EDP -- the most common
        answer, right 65 percent of the time -- would silently merge an EDT
        into an EDP one time in three."""
        assert read_concentration("Giorgio Armani Code Elixir") == (None, None)


class TestTheShelfResolvesToACategory:
    """Without this, `derive` cannot affirm a fragrance's category at all.

    Both shops shelve by gender and strength together, and that shelf is
    what lands in `merchant_category_path`. Simulated over all 34 094 live
    title/shelf pairs in the other three verticals, the rule claims none of
    them -- these words only ever mean perfume.
    """

    @pytest.mark.parametrize("shelf", [
        "Женски Eau de parfum",
        "Машки Eau de toilette",
        "Fragrances / Women",
        "Мириси",
    ])
    def test_a_fragrance_shelf_is_perfume(self, shelf):
        from mkagg.taxonomy import classify
        assert classify(shelf) == "perfume"

    @pytest.mark.parametrize("other", [
        "Патики Puma Caven 2.0",
        "Маица Nike",
        "Чорапи 3 пара",
        "Шорцеви за пливање",
    ])
    def test_the_other_verticals_are_untouched(self, other):
        from mkagg.taxonomy import classify
        assert classify(other) != "perfume"


class TestWhoItIsSoldTo:
    def test_a_shelf_states_the_gender(self):
        assert read_gender("Машки мириси") == "men"
        assert read_gender("Женски Eau de parfum") == "women"
        assert read_gender("Унисекс") == "unisex"
        assert read_gender("Fragrances / Women") == "women"

    def test_an_explicit_title_marker_overrides_a_wrong_shelf(self):
        """Measured: 2 products in 672 on Schatze's gendered shelves.

        Versace's "Pour Homme - edt" sits on Fragrances / Women. e-elixir
        shelves the same fragrance under Машки, so we can see which shop is
        wrong -- and the title said so all along.
        """
        assert read_gender("Fragrances / Women", "Pour Homme - edt") == "men"

    def test_the_shelf_wins_when_the_title_is_silent(self):
        """Which is 88 percent of Schatze's titles."""
        assert read_gender("Fragrances / Women", "Idole - edp") == "women"

    def test_a_title_naming_both_is_no_evidence(self):
        assert read_gender(None, "Pour Homme Pour Femme") is None

    def test_nothing_known_is_none_not_unisex(self):
        """unisex is a claim a shelf makes, not the absence of one."""
        assert read_gender(None, "Idole") is None


class TestWhatIsNotABottleOfPerfume:
    """All of these live inside both shops' fragrance shelves."""

    def test_a_bottle_is_a_bottle(self):
        assert is_single_bottle("Valentino Donna Eau de parfum",
                                ["Женски Eau de parfum"], ["30ml", "50ml"])

    def test_a_gift_set_is_not_a_volume_of_the_bottle_in_it(self):
        """The merge this prevents would be the worst kind: plausible.

        "212 Vip Black 100ml EDP + Shower Gel 100ml" would arrive as a
        100ml of 212 Vip Black, at a set's price, and sit on the volume
        rail beside the real 100ml.
        """
        assert not is_single_bottle(
            "212 Vip Black 100ml EDP + Shower Gel 100ml")
        assert not is_single_bottle(
            "Shiseido Zen Essence Holiday сет: Zen Eau de parfum 50ml "
            "+ travel size 10ml")

    def test_a_set_shelf_is_enough_on_its_own(self):
        assert not is_single_bottle("Boss Bottled Eau de toilette",
                                    ["Машки сетови"])

    def test_a_candle_is_sold_by_weight(self):
        assert not is_single_bottle("Acqua Dell'Elba миризлива свеќа Fiori",
                                    [], ["180g", "425g"])

    def test_grams_alone_are_not_a_volume(self):
        assert not is_single_bottle("Something Scented", [], ["425g"])

    def test_millilitres_beside_grams_still_count(self):
        # A shop offering both a 100ml bottle and a 425g candle under one
        # listing is still selling a bottle.
        assert is_single_bottle("Something Eau de parfum", [], ["100ml", "425g"])

    def test_a_body_mist_is_a_different_article(self):
        assert not is_single_bottle("Victoria's Secret Sweet Fig "
                                    "парфимиран спреј за тело 250мл")

    def test_a_room_fragrance_is_not_worn(self):
        assert not is_single_bottle(
            "Acqua Dell&#8217;Elba Refill мирис за просторија "
            "Cala del Fico 500ml")

    def test_a_perfumed_deodorant_is_not_the_bottle(self):
        assert not is_single_bottle("Moschino I Love Love парфимиран "
                                    "деодорант за жени 50ml")

    def test_an_empty_title_decides_nothing(self):
        assert not is_single_bottle("")
        assert not is_single_bottle(None)
