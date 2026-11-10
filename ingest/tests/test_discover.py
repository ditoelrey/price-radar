"""Discovery tests. No network: every fetch goes through StubTransport.

The three strategies exist because the stores differ, and each test names the
measurement that drove the choice.
"""
from __future__ import annotations

import re

import pytest

from mkagg.discover import (DISCOVERY_PLANS, PRODUCT_URL_PATTERNS,
                            PaginatedPlan, SampledPlan, SitemapPlan,
                            discover, extract_links, parse_sitemap_index,
                            parse_sitemap_urls, parse_total_pages,
                            product_jobs)
from mkagg.fetch import (CircuitBreaker, Fetcher, FetcherConfig,
                         MemoryRateLimiter, StubTransport)

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.dsport.mk/media/sitemap/dsport-1-1.xml</loc>
<lastmod>2026-11-05T05:01:50+00:00</lastmod></sitemap>
<sitemap><loc>https://www.dsport.mk/media/sitemap/dsport-1-2.xml</loc></sitemap>
</sitemapindex>"""

URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.dsport.mk/muskarci</loc><lastmod>2026-11-01</lastmod></url>
<url><loc>https://www.dsport.mk/muskarci/obuca/cizme/adidas-terrex-kj8942</loc>
<lastmod>2026-11-04</lastmod></url>
<url><loc>https://www.dsport.mk/zene/obuca/adidas-pumpa-pump-cz9556</loc></url>
</urlset>"""


class TestSitemapParsers:
    def test_index_children(self):
        assert parse_sitemap_index(SITEMAP_INDEX) == [
            "https://www.dsport.mk/media/sitemap/dsport-1-1.xml",
            "https://www.dsport.mk/media/sitemap/dsport-1-2.xml"]

    def test_urlset_with_lastmod(self):
        urls = parse_sitemap_urls(URLSET)
        assert len(urls) == 3
        assert urls[0] == ("https://www.dsport.mk/muskarci", "2026-11-01")
        assert urls[2][1] is None

    def test_flat_sitemap_without_url_wrapper(self):
        flat = "<urlset><loc>https://x.mk/p/a</loc><loc>https://x.mk/p/b</loc></urlset>"
        assert [u for u, _ in parse_sitemap_urls(flat)] == [
            "https://x.mk/p/a", "https://x.mk/p/b"]

    def test_empty_input_is_not_an_error(self):
        assert parse_sitemap_index("") == []
        assert parse_sitemap_urls("") == []


class TestProductUrlPatterns:
    @pytest.mark.parametrize("adapter,url,expected", [
        ("sportvision", "/mk/patiki/8550245-puma-caven-2-0", True),
        ("sportvision", "/mk/patiki", False),
        ("sportvision", "/mk/patiki/page-2", False),
        ("magento_html",
         "/muskarci/obuca/cizme/adidas-terrex-skychaser-ax5-mid-gtx-za-mazhi-kj8942",
         True),
        ("magento_html", "/muskarci", False),
        ("woocommerce_html", "/p/patiki-puma-caven-2-0-2/", True),
        ("woocommerce_html", "/shop/", False),
        ("aspnet_mk", "/ProductCatalog/ProductDetails?ProductID=M20325", True),
        ("aspnet_mk", "/ProductCatalog?Segment=03&Grupa=01", False),
    ])
    def test_separates_products_from_categories(self, adapter, url, expected):
        assert bool(PRODUCT_URL_PATTERNS[adapter].search(url)) is expected

    def test_pagination_links_are_not_mistaken_for_products(self):
        """dsport's sitemap mixes 6 140 URLs of which only ~1 331 are products."""
        pattern = PRODUCT_URL_PATTERNS["sportvision"]
        assert not pattern.search("/mk/patiki/page-12")


class TestTotalPages:
    def test_reads_sport_vision_page_count(self):
        assert parse_total_pages('<div data-total-pages="124" >') == 124
        assert parse_total_pages("<div data-page-count='7'>") == 7

    def test_absent_or_absurd_is_none(self):
        assert parse_total_pages("<div>") is None
        assert parse_total_pages('data-total-pages="0"') is None
        assert parse_total_pages('data-total-pages="99999"') is None


class TestExtractLinks:
    def test_absolutises_and_dedupes(self):
        html = ('<a href="/mk/patiki/51378-a">x</a>'
                '<a href="/mk/patiki/51378-a">again</a>'
                '<a href="https://www.sportvision.mk/mk/patiki/8550245-b">y</a>')
        links = extract_links(html, PRODUCT_URL_PATTERNS["sportvision"],
                              "https://www.sportvision.mk/")
        assert links == ["https://www.sportvision.mk/mk/patiki/51378-a",
                         "https://www.sportvision.mk/mk/patiki/8550245-b"]

    def test_decodes_html_entities_in_query_strings(self):
        """sport-m writes &amp; in hrefs; a literal &amp; breaks the request."""
        html = ('<a href="/ProductCatalog/ProductDetails?ProductID=M1&amp;x=1">'
                'a</a>')
        links = extract_links(html, PRODUCT_URL_PATTERNS["aspnet_mk"],
                              "https://www.sport-m.com.mk/")
        assert links == [
            "https://www.sport-m.com.mk/ProductCatalog/ProductDetails?ProductID=M1&x=1"]


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

def make_fetcher(routes):
    return Fetcher(
        StubTransport(routes=routes),
        limiter=MemoryRateLimiter(rps=1000, capacity=1000, reserve=0),
        breaker=CircuitBreaker(),
        config=FetcherConfig(respect_robots=False, max_attempts=1))


XML = {"content-type": "text/xml"}
HTML = {"content-type": "text/html"}


class TestSitemapStrategy:
    def test_follows_the_index_and_keeps_only_products(self):
        fetcher = make_fetcher({
            "/media/sitemap/dsport.xml": (200, XML, SITEMAP_INDEX.encode()),
            "dsport-1-1.xml": (200, XML, URLSET.encode()),
            "dsport-1-2.xml": (200, XML, b"<urlset></urlset>"),
        })
        report = discover(fetcher, "dsport", "magento_html",
                          "https://www.dsport.mk")
        assert report.strategy == "sitemap"
        assert report.count == 2, report.product_urls
        assert all("adidas" in u for u in report.product_urls)
        assert "muskarci" not in [u.rsplit("/", 1)[-1] for u in report.product_urls]

    def test_child_filter_skips_non_product_sitemaps(self):
        """megasport's index also lists a page sitemap we do not want."""
        index = ("<sitemapindex>"
                 "<sitemap><loc>https://m.mk/page-sitemap.xml</loc></sitemap>"
                 "<sitemap><loc>https://m.mk/product-sitemap1.xml</loc></sitemap>"
                 "</sitemapindex>")
        fetcher = make_fetcher({
            "/sitemap_index.xml": (200, XML, index.encode()),
            "product-sitemap1.xml": (
                200, XML, b"<urlset><url><loc>https://m.mk/p/a-shoe/</loc>"
                          b"</url></urlset>"),
            "page-sitemap.xml": (200, XML, b"<urlset><url>"
                                           b"<loc>https://m.mk/p/should-not-be-read/</loc>"
                                           b"</url></urlset>"),
        })
        report = discover(fetcher, "megasport", "woocommerce_html",
                          "https://megasportonlineshop.com")
        assert report.product_urls == ["https://m.mk/p/a-shoe/"]
        assert all("page-sitemap" not in c["url"]
                   for c in fetcher.transport.calls)


class TestPaginatedStrategy:
    def test_uses_the_declared_total_pages(self):
        first = ('<div data-total-pages="3"></div>'
                 '<a href="/mk/patiki/51378-a">a</a>')
        pages = {
            "/mk/patiki/page-2": (200, HTML, b'<a href="/mk/patiki/51379-b">b</a>'),
            "/mk/patiki/page-3": (200, HTML, b'<a href="/mk/patiki/51380-c">c</a>'),
            "/mk/patiki": (200, HTML, first.encode()),
            "/mk/obuvki": (200, HTML, b'<div data-total-pages="1"></div>'),
        }
        fetcher = make_fetcher(pages)
        report = discover(fetcher, "sportvision", "sportvision",
                          "https://www.sportvision.mk")
        assert report.strategy == "paginated"
        assert report.count == 3
        # 2 categories: 1 + 2 extra pages, and 1 with no extra pages.
        assert report.requests == 4

    def test_stops_at_the_limit(self):
        many = "".join(f'<a href="/mk/patiki/{51000 + i}-x">{i}</a>' for i in range(50))
        fetcher = make_fetcher({
            "/mk/patiki": (200, HTML,
                           f'<div data-total-pages="99"></div>{many}'.encode()),
            "/mk/obuvki": (200, HTML, b""),
        })
        report = discover(fetcher, "sportvision", "sportvision",
                          "https://www.sportvision.mk", limit=10)
        assert report.count == 10

    def test_max_pages_caps_a_runaway_category(self):
        plan = DISCOVERY_PLANS["sportvision"]
        assert isinstance(plan, PaginatedPlan)
        assert plan.max_pages <= 500


class TestSampledStrategy:
    """sport-m and sizeer return a random ~18-product sample per request.

    The same URL fetched twice shared 1 of 18 results, so there is no stable
    pagination. The only honest enumeration is to re-request until a facet
    stops yielding anything new; measured, that saturates at 21 products in
    about 5 requests.
    """

    def _sampling_route(self, pool, per_request=3):
        """Serve a rotating window of `pool`, imitating the random sample."""
        state = {"i": 0}

        def respond(method, url, headers, body):
            i = state["i"]
            state["i"] += 1
            window = [pool[(i * per_request + k) % len(pool)]
                      for k in range(per_request)]
            links = "".join(
                f'<a href="/ProductCatalog/ProductDetails?ProductID={p}">x</a>'
                for p in window)
            return (200, HTML, links.encode())
        return respond

    def test_saturates_and_stops(self):
        pool = [f"SKU{i}" for i in range(6)]
        fetcher = make_fetcher({"/ProductCatalog": self._sampling_route(pool)})
        report = discover(fetcher, "sportm", "aspnet_mk",
                          "https://www.sport-m.com.mk", max_requests=200)
        assert report.strategy == "sampled"
        assert report.count == len(pool), report.product_urls
        assert report.saturated_facets > 0

    def test_request_ceiling_is_enforced_per_facet(self):
        """A pool too large to confirm must not become an unbounded crawl."""
        plan = DISCOVERY_PLANS["aspnet_mk"]
        assert isinstance(plan, SampledPlan)
        assert plan.max_requests <= 20
        assert plan.saturation_rounds >= 2

        huge = [f"SKU{i}" for i in range(5000)]
        fetcher = make_fetcher({"/ProductCatalog": self._sampling_route(huge)})
        report = discover(fetcher, "sportm", "aspnet_mk",
                          "https://www.sport-m.com.mk", max_requests=60)
        assert report.requests <= 60
        assert report.exhausted_facets > 0, \
            "an unsaturated facet must be reported, not silently truncated"

    def test_global_request_cap_respected(self):
        pool = [f"SKU{i}" for i in range(500)]
        fetcher = make_fetcher({"/ProductCatalog": self._sampling_route(pool)})
        report = discover(fetcher, "sportm", "aspnet_mk",
                          "https://www.sport-m.com.mk", max_requests=12)
        assert report.requests <= 12


class TestDriverRobustness:
    def test_unknown_adapter_reports_instead_of_raising(self):
        fetcher = make_fetcher({})
        report = discover(fetcher, "x", "no_such_adapter", "https://x.mk")
        assert report.count == 0
        assert any("no discovery plan" in n for n in report.notes)

    def test_errors_are_counted_not_fatal(self):
        fetcher = make_fetcher({"/media/sitemap/dsport.xml": (500, XML, b"")})
        report = discover(fetcher, "dsport", "magento_html",
                          "https://www.dsport.mk")
        assert report.errors >= 1
        assert report.count == 0

    def test_robots_skip_is_recorded(self):
        fetcher = Fetcher(
            StubTransport(routes={
                "/robots.txt": (200, {"content-type": "text/plain"},
                                b"User-agent: *\nDisallow: /\n")}),
            limiter=MemoryRateLimiter(rps=1000, capacity=1000, reserve=0),
            config=FetcherConfig(respect_robots=True))
        report = discover(fetcher, "dsport", "magento_html",
                          "https://www.dsport.mk")
        assert report.count == 0
        assert any("robots_disallowed" in n for n in report.notes)

    def test_product_jobs_carry_the_right_kind(self):
        fetcher = make_fetcher({
            "/media/sitemap/dsport.xml": (200, XML, SITEMAP_INDEX.encode()),
            "dsport-1-1.xml": (200, XML, URLSET.encode()),
            "dsport-1-2.xml": (200, XML, b"<urlset></urlset>"),
        })
        report = discover(fetcher, "dsport", "magento_html",
                          "https://www.dsport.mk")
        jobs = product_jobs(report)
        assert jobs and all(j.kind == "catalog_parse" for j in jobs)
        assert all(j.merchant_slug == "dsport" for j in jobs)


def test_every_live_adapter_has_a_discovery_plan():
    """Any adapter a merchant actually uses must be enumerable."""
    live = {"sportvision", "magento_html", "woocommerce_html", "aspnet_mk"}
    assert live <= set(DISCOVERY_PLANS)
    assert live <= set(PRODUCT_URL_PATTERNS)
