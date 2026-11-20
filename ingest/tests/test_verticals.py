"""Keeping two verticals apart.

Adding apparel to a shop that already sells footwear breaks two things
unless they are deliberately separated, and both failures are quiet.

**The sweep would walk the wrong tree.** The apparel facet plans built for
the labelling walk are not what `discover` reads; without a vertical it
re-walks shoes and reports a healthy-looking zero new products.

**The gate would judge apparel against footwear.** `ingest_run_baseline` is
keyed on (merchant_id, kind) and every "is this run normal?" check reads it.
sportvision's first apparel run is some 6,500 offers against a footwear
median near 3,800 -- far outside the plus-or-minus 20 percent band, and
enforced rather than provisional on a shop with that many promoted runs. It
would be rejected, and had it been promoted the median would have become a
blend that describes neither vertical.
"""
from __future__ import annotations

import pytest

from mkagg.discover import (ACCESSORY_FACET_PLANS, APPAREL_FACET_PLANS,
                            DISCOVERY_PLANS,
                            FACET_PLANS, MERCHANT_PLANS, as_facets,
                            discover, facet_plan, sweep_plan)
from mkagg.load import (ACCESSORY_KIND, APPAREL_KIND,
                        CATALOG_KIND, run_kind_for)
from mkagg.models import RawOffer
from mkagg.taxonomy import (ACCESSORY_SLUGS, APPAREL_SLUGS, FACET_GENDERS,
                            FOOTWEAR_SLUGS)

from test_discover import HTML, make_fetcher


def offer(hint=None):
    return RawOffer(merchant_slug="sportvision", merchant_sku="1",
                    raw_title="t", product_url="u", category_hint=hint)


class TestSweepPlanPerVertical:
    def test_apparel_sweeps_the_apparel_facets(self):
        plan = sweep_plan("sportvision", "sportvision", "apparel")
        assert plan is APPAREL_FACET_PLANS["sportvision"]

    def test_footwear_still_sweeps_what_it_always_did(self):
        """The footwear sweep walks the coarse branches, not the fine
        gender-by-category facets -- those exist to label what it found."""
        assert sweep_plan("sizeer", "aspnet_mk", "footwear") is \
            MERCHANT_PLANS["sizeer"]
        assert sweep_plan("sportvision", "sportvision", "footwear") is \
            DISCOVERY_PLANS["sportvision"]
        assert sweep_plan("dsport", "magento_html", "footwear") is \
            DISCOVERY_PLANS["magento_html"]

    def test_a_sweep_and_a_walk_differ_for_footwear(self):
        """Walking the sweep's plan would label nothing by gender; sweeping
        the walk's plan would fetch the same pages several times."""
        assert sweep_plan("sportvision", "sportvision", "footwear") is not \
            facet_plan("sportvision", "footwear")
        assert len(as_facets(FACET_PLANS["sportvision"].categories)) == 12
        assert len(as_facets(
            DISCOVERY_PLANS["sportvision"].categories)) == 2

    def test_but_are_the_same_for_apparel(self):
        """Its facets cover the vertical exactly once, so a sweep reads them
        directly -- and products arrive carrying a category and a gender."""
        assert sweep_plan("buzz", "sportvision", "apparel") is \
            facet_plan("buzz", "apparel")

    def test_a_shop_with_no_apparel_plan_gets_none(self):
        """dsport is footwear-only and inactive; silence beats a guess."""
        assert sweep_plan("dsport", "magento_html", "apparel") is None

    def test_an_unknown_vertical_is_not_quietly_footwear(self):
        assert sweep_plan("sportvision", "sportvision", "shoes") is None
        assert facet_plan("sportvision", "shoes") is None


class TestDiscoverHonoursTheVertical:
    ROUTES = {
        "/mk/maici/maski+unisex/vozrasni": (
            200, HTML, b'<a href="/mk/maici/999001-nike-maica">a</a>'),
        "/mk/patiki": (
            200, HTML, b'<a href="/mk/patiki/999002-nike-patika">b</a>'),
    }

    def _run(self, vertical):
        return discover(make_fetcher(self.ROUTES), "sportvision",
                        "sportvision", "https://www.sportvision.mk",
                        vertical=vertical, limit=1)

    def test_apparel_finds_apparel(self):
        report = self._run("apparel")
        assert report.count == 1
        url = report.product_urls[0]
        assert "maici" in url
        assert report.category_hints[url] == "tshirts"
        assert report.gender_hints[url] == "men"

    def test_footwear_finds_footwear(self):
        report = self._run("footwear")
        assert report.count == 1
        assert "patiki" in report.product_urls[0]

    def test_an_unknown_vertical_discovers_nothing_and_says_so(self):
        report = discover(make_fetcher(self.ROUTES), "sportvision",
                          "sportvision", "https://www.sportvision.mk",
                          vertical="hats")
        assert report.count == 0
        assert any("hats" in note for note in report.notes), report.notes


class TestRunKind:
    @pytest.mark.parametrize("hint", sorted(APPAREL_SLUGS))
    def test_every_apparel_facet_opens_an_apparel_run(self, hint):
        assert run_kind_for(offer(hint)) == APPAREL_KIND

    @pytest.mark.parametrize("hint", sorted(FOOTWEAR_SLUGS))
    def test_every_footwear_facet_opens_a_catalogue_run(self, hint):
        assert run_kind_for(offer(hint)) == CATALOG_KIND

    @pytest.mark.parametrize("hint", sorted(ACCESSORY_SLUGS))
    def test_every_accessory_facet_opens_an_accessory_run(self, hint):
        """Including `socks`, which V10 filed under this kind long before
        there was a vertical to put it in. A pack of socks found on a shoe
        shelf still belongs to the equipment run -- the category decides,
        not the sweep that happened to reach it."""
        assert run_kind_for(offer(hint)) == ACCESSORY_KIND

    @pytest.mark.parametrize("hint", [None, "", "unknown-slug"])
    def test_anything_else_stays_with_the_catalogue(self, hint):
        """dsport's sitemap carries no hint, and a stock probe none either.

        Defaulting the unknown case to another vertical's run would quietly
        move products out of the baseline they have been measured against
        for every run so far.
        """
        assert run_kind_for(offer(hint)) == CATALOG_KIND

    def test_the_three_kinds_are_distinct(self):
        """A shared kind would make `ingest_run_baseline` compare each
        vertical against the others' medians, which rejects every first
        run."""
        assert len({CATALOG_KIND, APPAREL_KIND, ACCESSORY_KIND}) == 3

    def test_a_retired_slug_no_longer_routes(self):
        """V23 deleted the `equipment` category, so nothing can be hinted
        with it any more; it falls back rather than opening a run of its
        own."""
        assert run_kind_for(offer("equipment")) == CATALOG_KIND

    def test_the_two_kinds_are_distinct(self):
        assert APPAREL_KIND != CATALOG_KIND


class TestDrainSplitsByKind:
    """`run_once` groups by (merchant, kind), not by merchant.

    A drain can hold both verticals -- nothing stops a queue being refilled
    from two sweeps -- and filing them as one run would put apparel offers
    into the footwear baseline, which is the failure this change exists to
    prevent. Driven through the real loop rather than a re-implementation of
    its grouping, because the grouping is the thing under test.
    """

    def _drain(self, hints):
        from mkagg.fetch.queue import FetchJob, MemoryFetchQueue
        from mkagg.worker import run_once
        from test_worker import FakeConn, load_bytes, make_fetcher

        body = load_bytes("sportvision_caven20.html")
        routes = {f"/p{i}": (200, HTML, body) for i in range(len(hints))}
        fetcher = make_fetcher(routes)
        queue = MemoryFetchQueue()
        for i, hint in enumerate(hints):
            queue.push(FetchJob(merchant_slug="sportvision",
                                url=f"https://x.mk/p{i}",
                                category_hint=hint), dedupe=False)

        seen = []

        def spy(conn, slug, offers, *, kind, **kw):
            seen.append((slug, kind, len(offers)))
            return None

        run_once(FakeConn(), fetcher, queue, ingest_fn=spy)
        return seen

    def test_a_mixed_drain_becomes_two_runs(self):
        seen = self._drain(["tshirts", "hoodies", "sneakers"])
        assert sorted(seen) == [
            ("sportvision", APPAREL_KIND, 2),
            ("sportvision", CATALOG_KIND, 1),
        ]

    def test_one_vertical_alone_stays_one_run(self):
        seen = self._drain(["sneakers", "cleats"])
        assert seen == [("sportvision", CATALOG_KIND, 2)]

    def test_apparel_alone_opens_only_an_apparel_run(self):
        seen = self._drain(["tshirts", "trousers"])
        assert seen == [("sportvision", APPAREL_KIND, 2)]

    def test_an_unhinted_drain_is_still_a_catalogue_run(self):
        """dsport's sitemap carries no hint; nothing should move baseline."""
        seen = self._drain([None, None])
        assert seen == [("sportvision", CATALOG_KIND, 2)]


class TestAccessoryFacetPlans:
    """The Опрема plans, every slug of which the probe confirmed.

    These assertions are cheap and the failure they prevent is not: a slug
    that 404s inside a facet walk takes its whole section with it silently,
    and nothing in the run report says a thing.
    """

    SHOPS = ("sportvision", "sportreality", "buzz", "megasport", "sizeer",
             "sportm")

    @pytest.mark.parametrize("slug", SHOPS)
    def test_every_shop_has_one(self, slug):
        assert ACCESSORY_FACET_PLANS.get(slug) is not None

    @pytest.mark.parametrize("slug", SHOPS)
    def test_every_facet_names_a_leaf_this_kind_owns(self, slug):
        """A category outside the kind would make a full sweep retire rows
        from another vertical -- the exact failure V19 and V23 exist to stop."""
        for facet in as_facets(ACCESSORY_FACET_PLANS[slug].categories):
            assert facet.category in ACCESSORY_SLUGS, (slug, facet.path)

    @pytest.mark.parametrize("slug", SHOPS)
    def test_every_gender_is_one_a_department_may_declare(self, slug):
        """`unisex` is allowed here and nowhere else. See FACET_GENDERS."""
        for facet in as_facets(ACCESSORY_FACET_PLANS[slug].categories):
            assert facet.gender is None or facet.gender in FACET_GENDERS, (
                slug, facet.gender)

    @pytest.mark.parametrize("slug", ("sportvision", "sportreality", "buzz"))
    def test_the_sport_vision_family_walks_unisex_outright(self, slug):
        """55 percent of sportvision's equipment is unisex and 66 of sport
        reality's, against 4.2 percent of footwear. Inferring it from two
        bundled departments is not enough when a shop publishes the
        department itself."""
        genders = {f.gender for f in
                   as_facets(ACCESSORY_FACET_PLANS[slug].categories)}
        assert "unisex" in genders
        assert {"men", "women", "kids"} <= genders

    def test_sportm_walks_its_genderless_section(self):
        """Segment=06 holds 758 articles with no department in any URL. The
        facet carries no gender rather than inventing one; the Спецификации
        table on each page supplies it."""
        facets = as_facets(ACCESSORY_FACET_PLANS["sportm"].categories)
        genderless = [f for f in facets if f.gender is None]
        assert genderless, "the standalone Опрема section is missing"
        assert all("Segment=06" in f.path for f in genderless)

    def test_the_h_less_spellings_are_the_ones_used(self):
        """The probe's central finding: the shops drop the `h` the
        transliterator produces. `chorapi` 404s and `corapi` answers."""
        paths = " ".join(
            f.path for f in
            as_facets(ACCESSORY_FACET_PLANS["sportvision"].categories))
        assert "/mk/corapi/" in paths
        assert "/mk/chorapi/" not in paths
        assert "/mk/sise-za-voda/" in paths
        assert "/mk/shishe-za-voda/" not in paths

    def test_the_two_sport_vision_shops_do_not_share_a_list(self):
        """Unlike apparel, and not by a little.

        sportreality names forty-eight equipment sections against
        sportvision's nineteen, and spells several of them differently:
        `kacketi-i-kapi` on one, `kapa` and `kacket` on the other.
        """
        sv = {f.label for f in
              as_facets(ACCESSORY_FACET_PLANS["sportvision"].categories)}
        sr = {f.label for f in
              as_facets(ACCESSORY_FACET_PLANS["sportreality"].categories)}
        assert "kacketi-i-kapi" in sv and "kacketi-i-kapi" not in sr
        assert "kacket" in sr and "kacket" not in sv
        assert len(sr) > len(sv)

    def test_sportreality_names_the_sections_its_offers_sit_in(self):
        """Built from ingested URLs, not from a candidate list.

        The first version named eight sections and left 326 of 609 offers on
        the umbrella, because a probe can only confirm what it is asked. Each
        of these carries ten or more offers and none was in that list.
        """
        labels = {f.label for f in
                  as_facets(ACCESSORY_FACET_PLANS["sportreality"].categories)}
        for section in ("kapa", "ranec", "vreka-za-trening", "kufer",
                        "golmanski-rakavici", "rakavici", "kostobran"):
            assert section in labels, section

    def test_the_umbrella_comes_last(self):
        """Discovery keeps the first facet to claim a URL, so a catch-all
        placed earlier would swallow every leaf behind it."""
        for slug in ("sportvision", "sportreality", "buzz"):
            labels = [f.label for f in
                      as_facets(ACCESSORY_FACET_PLANS[slug].categories)]
            assert labels[-1] == "oprema", slug

    def test_the_excluded_subgroups_are_not_walked(self):
        """Pets, Funko, bicycles and watches. Leaving them out of the plan is
        half of it; `taxonomy.is_excluded` is the other half, because the
        Спецификации parser reads subgroups off the product page."""
        for slug in ("sizeer", "sportm"):
            paths = " ".join(f.path for f in
                             as_facets(ACCESSORY_FACET_PLANS[slug].categories))
            for code in ("798", "742", "649", "740"):
                assert f"PodGrupa={code}" not in paths, (slug, code)
