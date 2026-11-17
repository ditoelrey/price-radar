"""Reading apparel size labels.

Every label in this file is one a shop actually serves, collected by fetching
apparel products through the real adapters during the Phase 2 recon. The
spread is the point: four sizing systems across six shops, two spellings of
the same letter size inside one shop, and one shop using four systems at
once.

The bug these guard against is already in the database's history. 148 apparel
variants and 28 accessory variants carried an EU *shoe* size taken from
labels like '38' and '44' -- EU clothing sizes stored where shoe sizes live,
because a numeric bound was asked to do a job only context can do. V18
cleared them; `read_size` is what stops them coming back.
"""
from __future__ import annotations

import pytest

from mkagg.sizing import ALPHA_LADDER, read_pair, read_size


class TestLetterSizes:
    @pytest.mark.parametrize("label,expected", [
        ("XS", "XS"), ("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"),
        # sportvision writes 2XL, sport-m writes XXL, for the same size.
        ("2XL", "XXL"), ("XXL", "XXL"),
        ("3XL", "3XL"), ("XXXL", "3XL"),
        # sportreality writes both of these, on adult apparel, in one shop.
        ("SM", "S"), ("MD", "M"), ("LG", "L"),
        ("small", "S"), ("medium", "M"), ("large", "L"),
        ("s", "S"), ("  xl  ", "XL"),
    ])
    def test_spellings_collapse(self, label, expected):
        reading = read_size(label)
        assert reading.system == "alpha"
        assert reading.alpha == expected

    def test_every_canonical_value_is_on_the_ladder(self):
        """The ladder is what a storefront sorts by, so nothing may fall off."""
        for label in ("XXS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"):
            reading = read_size(label)
            assert reading.alpha in ALPHA_LADDER, label

    def test_the_ladder_is_ordered_smallest_first(self):
        assert ALPHA_LADDER.index("S") < ALPHA_LADDER.index("M")
        assert ALPHA_LADDER.index("M") < ALPHA_LADDER.index("L")
        assert ALPHA_LADDER.index("XL") < ALPHA_LADDER.index("XXL")
        assert ALPHA_LADDER.index("XXL") < ALPHA_LADDER.index("3XL")


class TestAges:
    @pytest.mark.parametrize("label,lo,hi", [
        # sport-m and sizeer, months.
        ("12-18 мес.", 12, 18),
        ("12-18 mes.", 12, 18),
        # sport-m and sizeer, years written out.
        ("1-2 год.", 12, 24),
        ("2-3 год.", 24, 36),
        # sportvision, sportreality and buzz, years abbreviated.
        ("7-8г.", 84, 96),
        ("9-10г.", 108, 120),
        ("14-15г.", 168, 180),
        # sportreality again, English suffix, on the same shelf.
        ("6Y", 72, 84),
        ("12Y", 144, 156),
    ])
    def test_every_spelling_lands_in_months(self, label, lo, hi):
        reading = read_size(label)
        assert reading.system == "age"
        assert (reading.age_min_months, reading.age_max_months) == (lo, hi)

    def test_months_are_the_unit_because_years_do_not_fit(self):
        """"12-18 мес." cannot be said in whole years; "7-8г." divides exactly.

        Storing years would have to round the first or refuse it, and these
        two labels sit in the same shop.
        """
        months = read_size("12-18 мес.")
        years = read_size("7-8г.")
        assert months.age_max_months - months.age_min_months == 6
        assert years.age_min_months % 12 == 0


class TestHeights:
    @pytest.mark.parametrize("label,cm", [
        ("86", 86), ("128", 128), ("140", 140), ("164", 164), ("176", 176),
        # megasport's filter vocabulary bands two heights together.
        ("110-116", 110), ("122-128", 122),
    ])
    def test_heights_need_no_context(self, label, cm):
        """No EU shoe size reaches 80, so this band is never ambiguous.

        Which is exactly why a bare "38" is, and gets different treatment.
        """
        reading = read_size(label)
        assert reading.system == "height"
        assert reading.height_cm == cm


class TestNumbersNeedContext:
    def test_a_shoe_size_stays_a_shoe_size_on_footwear(self):
        assert read_size("42").system == "eu_shoe"
        assert read_size("36,5").system == "eu_shoe"

    def test_the_same_number_on_apparel_is_not_a_shoe_size(self):
        """The whole reason this module exists.

        38 is a women's dress size and a men's shoe size, and the label
        cannot tell you which. 148 apparel variants claimed EU shoe sizes
        before V18 because something tried to decide this from the number.
        """
        assert read_size("38", apparel=True).system == "numeric"
        assert read_size("42", apparel=True).system == "numeric"

    def test_a_bare_number_on_kids_apparel_is_an_age(self):
        """megasport writes "7" and means seven years old."""
        reading = read_size("7", apparel=True, kids=True)
        assert reading.system == "age"
        assert (reading.age_min_months, reading.age_max_months) == (84, 96)

    def test_but_only_when_we_know_it_is_a_kids_product(self):
        """A women's top labelled "12" is not a twelve-year-old.

        Without the kids flag there is nothing to distinguish the two, so
        the honest answer is that we read a number and could not place it.
        """
        assert read_size("12", apparel=True).system == "numeric"
        assert read_size("12", apparel=True, kids=True).system == "age"

    def test_numeric_is_a_reading_not_a_failure(self):
        """It says "we looked and could not place this", which a NULL would
        not distinguish from "nobody looked"."""
        assert read_size("38", apparel=True).system == "numeric"
        assert read_size(None).system is None
        assert read_size("").system is None


class TestOneSize:
    @pytest.mark.parametrize("label", [
        "BEZ VELICINA", "bez golemina", "ONE SIZE", "UNI", "-",
    ])
    def test_articles_without_a_size(self, label):
        assert read_size(label).system == "one_size"


class TestTwoLabelShops:
    """sport-m and sizeer state two labels per size, in one record."""

    def test_apparel_keeps_both_halves(self):
        """The mapping these two shops alone publish.

        `{"Velicina": "86", "EvropskaVelicina": "12-18 мес."}` is a height
        and an age for one garment. The adapter used to keep the age and drop
        the height, throwing away half of the only merchant-stated age/height
        mapping we have -- the mapping kids_size_chart is built from.
        """
        reading = read_pair("12-18 мес.", "86", apparel=True, kids=True)
        assert reading.system == "age"
        assert reading.height_cm == 86
        assert (reading.age_min_months, reading.age_max_months) == (12, 18)

    def test_order_does_not_matter(self):
        assert read_pair("86", "12-18 мес.", apparel=True, kids=True) == \
            read_pair("12-18 мес.", "86", apparel=True, kids=True)

    def test_footwear_still_reads_as_a_shoe_size(self):
        """On footwear the same two fields are the EU and UK sizes.

        Same columns, different meaning per vertical, which is why both are
        read rather than trusting the field name.
        """
        assert read_pair("41", "7.5").system == "eu_shoe"

    def test_an_empty_half_falls_through(self):
        assert read_pair("XL", None).alpha == "XL"
        assert read_pair(None, "XL").alpha == "XL"
        assert read_pair(None, None).is_empty
