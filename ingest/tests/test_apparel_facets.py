"""The apparel facet plans.

Plans are data, and wrong data here mislabels a whole vertical quietly. The
footwear phase supplied three cautionary tales: a department that was a
re-listing of three others, a Segment number that meant different things on
two installations of one platform, and a grid-tile class that existed on one
shop and not its sibling. Each produced a plausible number and a wrong
catalogue.

So these tests pin what recon actually measured, not what the taxonomy
"should" look like.
"""
from __future__ import annotations

import pytest

from mkagg.discover import (APPAREL_FACET_PLANS, FACET_CATEGORY, FACET_PLANS,
                            as_facets)
from mkagg.taxonomy import APPAREL_SLUGS, FACET_GENDERS, KNOWN_GENDERS


def facets(slug):
    return as_facets(APPAREL_FACET_PLANS[slug].categories)


class TestEveryShopIsCovered:
    def test_all_six_have_an_apparel_plan(self):
        assert set(APPAREL_FACET_PLANS) == set(FACET_PLANS) == {
            "sportvision", "sportreality", "buzz", "megasport", "sizeer",
            "sportm"}

    def test_every_facet_names_a_category_a_gender_and_a_label(self):
        for slug in APPAREL_FACET_PLANS:
            for facet in facets(slug):
                assert facet.category, (slug, facet.path)
                assert facet.gender in FACET_GENDERS, (slug, facet.path)
                assert facet.label, (slug, facet.path)

    def test_every_category_is_one_V18_seeded(self):
        for slug in APPAREL_FACET_PLANS:
            for facet in facets(slug):
                assert facet.category in APPAREL_SLUGS, (slug, facet.category)

    def test_all_eleven_leaves_are_reachable_somewhere(self):
        """A bucket no facet feeds is a bucket that stays empty for ever."""
        reached = {f.category for slug in APPAREL_FACET_PLANS
                   for f in facets(slug)}
        assert APPAREL_SLUGS - reached == set(), APPAREL_SLUGS - reached

    def test_labels_agree_with_the_shared_mapping(self):
        for slug in APPAREL_FACET_PLANS:
            for facet in facets(slug):
                assert FACET_CATEGORY[facet.label] == facet.category, (
                    slug, facet.label)


class TestSportVisionDeduplication:
    """The shops publish legacy and consolidated slugs for the same products.

    Measured: `dolen-del-trenerki` and `dolni-delovi-trenerki-` each return
    307 men's products -- the same 307. `jakni-i-eleci` (362) is `jakna`
    (290) plus `elek` (51). Walking both spellings fetches every page twice
    and discovers nothing new.
    """

    LEGACY = {"dolen-del-trenerki", "jakna", "elek", "helanki", "gradnik",
              "maica", "fustani", "sorc"}

    @pytest.mark.parametrize("slug", ["sportvision", "sportreality"])
    def test_no_legacy_slug_is_walked(self, slug):
        labels = {f.label for f in facets(slug)}
        assert labels & self.LEGACY == set(), labels & self.LEGACY

    @pytest.mark.parametrize("slug", ["sportvision", "sportreality"])
    def test_the_consolidated_ones_are(self, slug):
        labels = {f.label for f in facets(slug)}
        for consolidated in ("jakni-i-eleci", "dolni-delovi-trenerki-",
                             "helanki-i-biciklisticki", "gradnik-i-top",
                             "fustani-i-suknji", "maici"):
            assert consolidated in labels, consolidated

    def test_each_shop_gets_its_own_long_sleeve_spelling(self):
        """sportvision and sportreality disagree on one slug, and 404 on the
        other's. Found by fetching all 323 facets: six requests spent
        confirming a 404 three times per shop."""
        sv = {f.label for f in facets("sportvision")}
        sr = {f.label for f in facets("sportreality")}
        assert "maica-dolgi-rakavi" in sv and "maica-so-dolgi-rakavi" not in sv
        assert "maica-so-dolgi-rakavi" in sr and "maica-dolgi-rakavi" not in sr

    def test_buzz_keeps_its_own_vocabulary(self):
        """buzz is the same platform and shares none of those slugs.

        Its leaves summed to its umbrella exactly during recon, so its tree
        is disjoint -- and `maica` there is the real category, not a legacy
        alias, which is why the rule above is per shop and not global.
        """
        labels = {f.label for f in facets("buzz")}
        assert "maica" in labels
        assert "maici" not in labels
        assert "vetrovki-i-jakni" in labels


class TestDepartmentsThatDoNotStockACategory:
    """No men's department on these shops sells dresses or sports bras.

    Measured, not assumed: every one of these facets returned zero for men
    and plenty for women when all 323 were fetched. Leaving them in cost a
    request per walk to confirm an emptiness the shop's own shelves already
    stated -- and it is the same restriction the storefront nav applies, so
    the plan and the menu now agree for the same reason.
    """

    @pytest.mark.parametrize("slug", ["sportvision", "sportreality", "buzz"])
    @pytest.mark.parametrize("category", ["dresses_skirts", "sports_bras"])
    def test_not_walked_for_men(self, slug, category):
        for facet in facets(slug):
            if facet.category == category:
                assert facet.gender != "men", facet.path

    @pytest.mark.parametrize("slug", ["sportvision", "sportreality", "buzz"])
    @pytest.mark.parametrize("category", ["dresses_skirts", "sports_bras"])
    def test_but_still_walked_for_women(self, slug, category):
        genders = {f.gender for f in facets(slug) if f.category == category}
        assert "women" in genders, (slug, category)

    def test_categories_both_departments_stock_are_untouched(self):
        """The restriction is per category, not a blanket men's trim."""
        for slug in ("sportvision", "sportreality", "buzz"):
            genders = {f.gender for f in facets(slug)
                       if f.category == "tshirts"}
            assert genders == {"men", "women", "kids"}, slug


class TestMegasportExcludesHeadwear:
    """`kapi-obleka` -- 60 caps -- sits inside megasport's clothing tree.

    The footwear phase hit the mirror image of this: megasport's sitemap
    carried the whole shop, and a waist bag was served as footwear. The fix
    there was to name the leaves instead of walking the umbrella, and it is
    the fix here.
    """

    def test_caps_are_not_an_apparel_facet(self):
        labels = {f.label for f in facets("megasport")}
        assert "kapi-obleka" not in labels

    def test_and_no_umbrella_lets_them_in_the_back_door(self):
        paths = {f.path for f in facets("megasport")}
        for umbrella in ("/kategorija/mazhi/obleka-mazhi/",
                         "/kategorija/zheni/obleka/",
                         "/kategorija/deca/obleka-deca/"):
            assert umbrella not in paths, umbrella

    def test_the_other_shops_do_get_a_catch_all(self):
        """Their trees are clean, so the umbrella is safe and worth having.

        It runs last: discovery keeps the first facet to claim a URL, so
        specific categories win and the umbrella collects the remainder as
        clothing of unspecified kind.
        """
        for slug in ("sportvision", "sportreality", "buzz"):
            tail = facets(slug)[-3:]
            assert all(f.label == "tekstil" for f in tail), slug
            assert all(f.category == "apparel" for f in tail), slug


class TestAspnetSubgroups:
    @pytest.mark.parametrize("slug,segments", [
        ("sizeer", {"51", "52", "53"}),
        ("sportm", {"03", "04", "05"}),
    ])
    def test_each_shop_asks_for_its_own_departments(self, slug, segments):
        """Segment numbering is per installation -- V17's hardest lesson."""
        seen = {f.path.split("Segment=")[1].split("&")[0]
                for f in facets(slug)}
        assert seen == segments

    def test_everything_is_in_the_clothing_group(self):
        for slug in ("sizeer", "sportm"):
            for facet in facets(slug):
                assert "Grupa=02" in facet.path, (slug, facet.path)

    def test_the_group_codes_mean_the_same_on_both_shops(self):
        """PodGrupa is the shared product dictionary, unlike Segment."""
        def codes(slug):
            out = {}
            for f in facets(slug):
                if "PodGrupa=" in f.path:
                    out[f.path.rsplit("PodGrupa=", 1)[1]] = f.category
            return out

        sizeer, sportm = codes("sizeer"), codes("sportm")
        shared = set(sizeer) & set(sportm)
        assert shared
        for code in shared:
            assert sizeer[code] == sportm[code], code

    def test_the_catch_all_comes_after_the_specific_subgroups(self):
        """Order is load-bearing: first facet to claim a URL keeps it.

        The subgroup facets must run first or every product would be
        labelled with the generic `apparel` and nothing would refine it.
        """
        for slug in ("sizeer", "sportm"):
            paths = [f.path for f in facets(slug)]
            last_specific = max(i for i, p in enumerate(paths)
                                if "PodGrupa=" in p)
            first_generic = min(i for i, p in enumerate(paths)
                                if "PodGrupa=" not in p)
            assert last_specific < first_generic, slug

    def test_one_catch_all_per_department(self):
        for slug in ("sizeer", "sportm"):
            generic = [f for f in facets(slug) if "PodGrupa=" not in f.path]
            assert len(generic) == 3, slug
            assert {f.gender for f in generic} == KNOWN_GENDERS


class TestFootwearIsUntouched:
    def test_no_apparel_facet_walks_a_footwear_group(self):
        for slug in ("sizeer", "sportm"):
            for facet in facets(slug):
                assert "Grupa=01" not in facet.path

    def test_the_footwear_plans_still_say_what_they_said(self):
        """Adding a vertical must not disturb the one already running."""
        assert len(as_facets(FACET_PLANS["sportvision"].categories)) == 12
        assert len(as_facets(FACET_PLANS["sportm"].categories)) == 28
        assert len(as_facets(FACET_PLANS["buzz"].categories)) == 9
