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

from mkagg.discover import (APPAREL_FACET_PLANS, DISCOVERY_PLANS,
                            FACET_PLANS, MERCHANT_PLANS, as_facets,
                            discover, facet_plan, sweep_plan)
from mkagg.load import APPAREL_KIND, CATALOG_KIND, run_kind_for
from mkagg.models import RawOffer
from mkagg.taxonomy import APPAREL_SLUGS, FOOTWEAR_SLUGS

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

    @pytest.mark.parametrize("hint", [None, "socks", "accessories",
                                      "equipment"])
    def test_anything_else_stays_with_the_catalogue(self, hint):
        """dsport's sitemap carries no hint, and a sock is not apparel here.

        Defaulting the unknown case to the apparel run would quietly move
        products out of the baseline they have been measured against for
        every run so far.
        """
        assert run_kind_for(offer(hint)) == CATALOG_KIND

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
