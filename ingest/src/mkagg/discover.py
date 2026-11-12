"""URL discovery: finding the products in the first place.

Three strategies, one per platform family, each chosen by measuring the live
site rather than by assuming:

``sitemap``
    dsport publishes ``/media/sitemap/dsport.xml`` (3 children, 6 140 URLs in
    the first alone) and megasport ``/sitemap_index.xml`` (11+
    ``product-sitemapN.xml``). Both are robots-permitted and carry
    ``<lastmod>``, so a crawl can skip what has not changed. Where a sitemap
    exists it wins: one request yields thousands of URLs.

``paginated``
    The Sport Vision group has no usable sitemap but paginates predictably at
    ``{category}/page-{n}`` and prints ``data-total-pages="124"`` on the first
    page, so the whole run is known after one request.

``sampled``
    sport-m and sizeer have neither. **They return a random sample of ~18
    matching products per request**, not a stable page: the same URL fetched
    twice shared 1 of 18 results. There is no deterministic enumeration to be
    had, so the only honest approach is to re-request a narrowed facet until
    it stops yielding anything new. Measured on one facet, that saturates at
    21 products after about 5 requests, and the taxonomy
    (``Segment`` / ``Grupa`` / ``PodGrupa`` / ``Brend``) narrows the pool
    enough to make this tractable.

    Worth being clear about the limit: sampling cannot *prove* it has seen
    everything, so these two stores will always have a long tail. They are
    also the two most likely to hand over a feed -- one operator, no
    robots.txt, no SEO tooling -- which would remove the problem entirely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from .fetch.queue import FetchJob
from .fetch.ratelimit import Priority

# -----------------------------------------------------------------------------
# Pure parsers
# -----------------------------------------------------------------------------

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_SITEMAP_ENTRY = re.compile(r"<sitemap\b.*?</sitemap>", re.I | re.S)
_URL_ENTRY = re.compile(r"<url\b.*?</url>", re.I | re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


def parse_sitemap_index(xml: str) -> list[str]:
    """Child sitemap URLs from a ``<sitemapindex>``."""
    out: list[str] = []
    for entry in _SITEMAP_ENTRY.findall(xml):
        m = _LOC.search(entry)
        if m:
            out.append(m.group(1))
    return out


def parse_sitemap_urls(xml: str) -> list[tuple[str, str | None]]:
    """``(loc, lastmod)`` pairs from a ``<urlset>``.

    ``lastmod`` is what lets a catalogue crawl skip unchanged products, which
    matters more on these stores than usual because none of them honours a
    conditional request.
    """
    out: list[tuple[str, str | None]] = []
    for entry in _URL_ENTRY.findall(xml):
        loc = _LOC.search(entry)
        if not loc:
            continue
        mod = _LASTMOD.search(entry)
        out.append((loc.group(1), mod.group(1) if mod else None))
    if not out:
        # Some generators emit a bare list of <loc> with no <url> wrapper.
        out = [(loc, None) for loc in _LOC.findall(xml)]
    return out


_TOTAL_PAGES = re.compile(
    r'data-(?:total-pages|page-count)\s*=\s*["\'](\d{1,5})["\']', re.I)


def parse_total_pages(html: str) -> int | None:
    """Sport Vision prints the page count on the first category page."""
    m = _TOTAL_PAGES.search(html)
    if not m:
        return None
    try:
        total = int(m.group(1))
    except ValueError:
        return None
    return total if 0 < total <= 10_000 else None


def extract_links(html: str, pattern: re.Pattern[str], base_url: str) -> list[str]:
    """Absolute, de-duplicated URLs matching ``pattern``, order preserved."""
    seen: dict[str, None] = {}
    for raw in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        candidate = raw.replace("&amp;", "&").strip()
        if not pattern.search(candidate):
            continue
        seen.setdefault(urljoin(base_url, candidate), None)
    return list(seen)


# -----------------------------------------------------------------------------
# Per-platform configuration
# -----------------------------------------------------------------------------

#: What a product URL looks like on each platform, used to separate product
#: links from the category and editorial URLs that share a sitemap.
PRODUCT_URL_PATTERNS: dict[str, re.Pattern[str]] = {
    # /mk/patiki/8550245-puma-caven-2-0
    "sportvision": re.compile(r"/mk/[a-z0-9-]+/\d{3,12}-[a-z0-9-]+/?$", re.I),
    # dsport has no path marker, but every product URL ends in its article
    # code: /muskarci/obuca/cizme/adidas-terrex-...-kj8942
    "magento_html": re.compile(r"-[a-z0-9]{5,14}/?$", re.I),
    # /p/patiki-puma-caven-2-0-2/
    "woocommerce_html": re.compile(r"/p/[^/]+/?$", re.I),
    # /ProductCatalog/ProductDetails?ProductID=M20325
    "aspnet_mk": re.compile(r"/ProductCatalog/ProductDetails\?ProductID=[\w.-]+", re.I),
}


@dataclass(frozen=True)
class SitemapPlan:
    index_path: str
    #: Only follow children whose URL contains this (megasport's index also
    #: lists a page sitemap we do not want).
    child_contains: str | None = None
    strategy: str = "sitemap"


@dataclass(frozen=True)
class PaginatedPlan:
    #: (path, category slug implied by that path).
    categories: tuple[tuple[str, str | None], ...]
    page_suffix: str = "/page-{page}"
    max_pages: int = 200
    strategy: str = "paginated"


@dataclass(frozen=True)
class SampledPlan:
    """Repeated sampling of a facet until it stops producing new URLs."""

    #: (facet path, category slug implied by that facet).
    facets: tuple[tuple[str, str | None], ...]
    #: Consecutive empty rounds that count as saturated. Measured: a facet
    #: yields nothing new for 3 straight requests once exhausted.
    saturation_rounds: int = 3
    #: Hard ceiling per facet, so a large or mis-narrowed pool cannot turn
    #: into an unbounded crawl of one store.
    max_requests: int = 15
    strategy: str = "sampled"


DISCOVERY_PLANS: dict[str, SitemapPlan | PaginatedPlan | SampledPlan] = {
    "magento_html": SitemapPlan(index_path="/media/sitemap/dsport.xml"),
    "woocommerce_html": SitemapPlan(index_path="/sitemap_index.xml",
                                    child_contains="product-sitemap"),
    # Footwear only for the MVP. Adding apparel is adding strings here.
    # Each entry records what the shop's own category page implies.
    # That is strong evidence and costs nothing to carry.
    "sportvision": PaginatedPlan(categories=(
        ("/mk/patiki", "sneakers"),
        ("/mk/obuvki", "footwear"),
    )),
    # Segment=03 / Grupa=01 is this platform's footwear branch, which is
    # exactly the context its titles omit: "Adidas Handball Spezial" names no
    # category at all, and discovery knew it was a shoe before it was fetched.
    "aspnet_mk": SampledPlan(facets=(
        ("/ProductCatalog?Segment=03&Grupa=01", "footwear"),
        ("/ProductCatalog?Segment=03&Grupa=01&PodGrupa=500", "footwear"),
        ("/ProductCatalog?Segment=03&Grupa=01&PodGrupa=502", "footwear"),
        ("/ProductCatalog?Segment=03&Grupa=01&PodGrupa=503", "footwear"),
        # Brand facets double as the brand-term sweep: narrower pools
        # saturate faster and reach products the group facets miss. They say
        # nothing about category, so they carry no hint.
        ("/ProductCatalog?Segment=03&Brend=01", None),
        ("/ProductCatalog?Segment=03&Brend=02", None),
        ("/ProductCatalog?Segment=03&Brend=04", None),
        ("/ProductCatalog?Segment=03&Brend=25", None),
        ("/ProductCatalog?Segment=03&Brend=52", None),
        ("/ProductCatalog?Segment=03&Brend=69", None),
        ("/ProductCatalog?Segment=03&Brend=70", None),
        ("/ProductCatalog?Segment=03&Brend=81", None),
        ("/ProductCatalog?Segment=03&Brend=00050", None),
    )),
    # The API adapters discover through their own paginated endpoints and do
    # not need URL enumeration; they are robots-blocked today in any case.
}

#: Search-based sweep for the sampled platform, used when the facet taxonomy
#: misses a brand. Verified term-sensitive: "zzzznonsense" returns 0 results
#: while "adidas" returns matches.
SEARCH_SWEEP_PATH = "/ProductCatalog/Search?SearchKey={term}"
SWEEP_TERMS = ("adidas", "nike", "puma", "reebok", "new balance", "converse",
               "vans", "asics", "fila", "jordan", "under armour", "skechers")


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

@dataclass
class DiscoveryReport:
    merchant_slug: str
    adapter: str
    strategy: str = ""
    requests: int = 0
    listings_seen: int = 0
    product_urls: list[str] = field(default_factory=list)
    #: product URL -> category slug implied by where it was found.
    category_hints: dict = field(default_factory=dict)
    saturated_facets: int = 0
    exhausted_facets: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.product_urls)


def _listing_job(merchant_slug: str, url: str,
                 priority: Priority = Priority.COLD) -> FetchJob:
    return FetchJob(merchant_slug=merchant_slug, url=url, kind="discovery",
                    priority=priority)


def discover(fetcher, merchant_slug: str, adapter: str, base_url: str, *,
             priority: Priority = Priority.COLD,
             max_requests: int = 400,
             limit: int | None = None) -> DiscoveryReport:
    """Enumerate product URLs for one merchant.

    Uses the fetcher, so every request still passes through the rate limiter,
    the robots check and the circuit breaker. Discovery runs at ``COLD`` by
    default: it is the most preemptible work in the system.
    """
    report = DiscoveryReport(merchant_slug=merchant_slug, adapter=adapter)
    plan = DISCOVERY_PLANS.get(adapter)
    if plan is None:
        report.notes.append(f"no discovery plan for adapter {adapter!r}")
        return report
    report.strategy = plan.strategy

    pattern = PRODUCT_URL_PATTERNS.get(adapter)
    if pattern is None:
        report.notes.append(f"no product URL pattern for adapter {adapter!r}")
        return report

    found: dict[str, None] = {}
    hints: dict[str, str] = {}

    def fetch(url: str) -> str | None:
        if report.requests >= max_requests:
            return None
        result = fetcher.fetch(_listing_job(merchant_slug, url, priority))
        report.requests += 1
        if result.skipped:
            report.notes.append(f"{result.skipped}: {url}")
            return None
        if not result.ok:
            report.errors += 1
            return None
        report.listings_seen += 1
        return result.body.decode("utf-8", "replace")

    def harvest(text: str, hint: str | None = None) -> int:
        before = len(found)
        for url in extract_links(text, pattern, base_url):
            found.setdefault(url, None)
            if hint:
                hints.setdefault(url, hint)
        # Sitemaps carry <loc> rather than href.
        for loc, _lastmod in parse_sitemap_urls(text):
            if pattern.search(loc):
                found.setdefault(loc, None)
                if hint:
                    hints.setdefault(loc, hint)
        return len(found) - before

    def done() -> bool:
        return limit is not None and len(found) >= limit

    # --- sitemap ----------------------------------------------------------
    if isinstance(plan, SitemapPlan):
        index = fetch(urljoin(base_url, plan.index_path))
        if index:
            children = parse_sitemap_index(index)
            if plan.child_contains:
                children = [c for c in children if plan.child_contains in c]
            if not children:
                # A flat sitemap with no index wrapper.
                harvest(index)
            for child in children:
                if done():
                    break
                body = fetch(child)
                if body:
                    harvest(body)

    # --- paginated categories --------------------------------------------
    elif isinstance(plan, PaginatedPlan):
        for category, hint in plan.categories:
            if done():
                break
            first = fetch(urljoin(base_url, category))
            if not first:
                continue
            harvest(first, hint)
            total = parse_total_pages(first) or 1
            total = min(total, plan.max_pages)
            report.notes.append(f"{category}: {total} pages")
            for page in range(2, total + 1):
                if done():
                    break
                body = fetch(urljoin(base_url, f"{category}"
                                     f"{plan.page_suffix.format(page=page)}"))
                if body is None:
                    break
                harvest(body, hint)

    # --- sampled facets ---------------------------------------------------
    else:
        for facet, hint in plan.facets:
            if done():
                break
            url = urljoin(base_url, facet)
            empty_rounds = 0
            for attempt in range(plan.max_requests):
                body = fetch(url)
                if body is None:
                    break
                new = harvest(body, hint)
                if new == 0:
                    empty_rounds += 1
                    if empty_rounds >= plan.saturation_rounds:
                        report.saturated_facets += 1
                        break
                else:
                    empty_rounds = 0
            else:
                # Hit the ceiling without saturating: the pool is larger than
                # sampling can confirm, so this facet has an unknown tail.
                report.exhausted_facets += 1
                report.notes.append(f"facet not saturated: {facet}")

        # Search sweep for brands the facet taxonomy may miss.
        for term in SWEEP_TERMS:
            if done():
                break
            url = urljoin(base_url,
                          SEARCH_SWEEP_PATH.format(term=term.replace(" ", "+")))
            empty_rounds = 0
            for _ in range(plan.max_requests):
                body = fetch(url)
                if body is None:
                    break
                if harvest(body) == 0:
                    empty_rounds += 1
                    if empty_rounds >= plan.saturation_rounds:
                        break
                else:
                    empty_rounds = 0

    report.product_urls = list(found)[:limit] if limit else list(found)
    report.category_hints = {u: hints[u] for u in report.product_urls
                             if u in hints}
    return report


def product_jobs(report: DiscoveryReport, kind: str = "catalog_parse",
                 priority: Priority = Priority.COLD) -> list[FetchJob]:
    """Turn discovered URLs into fetch jobs for the worker."""
    return [FetchJob(merchant_slug=report.merchant_slug, url=url, kind=kind,
                     priority=priority,
                     category_hint=report.category_hints.get(url))
            for url in report.product_urls]
