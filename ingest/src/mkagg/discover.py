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
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

from .fetch.queue import FetchJob
from .fetch.ratelimit import Priority
from .taxonomy import resolve_departments

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


#: Page numbers as they appear in a paginator link: `/page/22/`, `/page-22`.
#: Unbounded digits on purpose -- a bounded `\d{1,4}` reads "99999" as 9999
#: and quietly returns a plausible wrong answer instead of refusing.
_PAGE_LINK = re.compile(r"/page[/-](\d+)/?", re.I)

#: Same ceiling `parse_total_pages` applies: past this it is not a page count.
_MAX_PAGES = 10_000


def parse_last_page_link(html: str) -> int | None:
    """Highest page number the paginator links to, or None if it has none.

    The fallback for shops that do not advertise a total. Sport Vision prints
    ``data-total-pages`` and needs nothing else; WooCommerce prints no total
    at all, but its paginator does link the last page -- "1 2 3 ... 21 22" --
    so the number is on the page, just as a link rather than an attribute.

    Reading it matters more than it looks: without it a category collapses to
    its first page, and discovery reports a confident, wrong total. Megasport
    would have come back with 90 products instead of 1 619.

    Implausible numbers are dropped rather than allowed to decide the
    answer: one junk link must not reduce a 22-page category to a single
    page, which is what rejecting the whole result would do.
    """
    pages = [p for p in (int(m) for m in _PAGE_LINK.findall(html or ""))
             if 0 < p <= _MAX_PAGES]
    return max(pages) if pages else None


#: Adapters whose product links carry the listing they were found in, which
#: has to come off before anything deduplicates on the URL.
#:
#: aspnet writes them as
#: ``/ProductCatalog/ProductDetails?ProductID=KD8253&Segment=52&Grupa=03&...``
#: -- the department the shopper clicked from, baked into the href. So one
#: article is three different URLs across the men's, women's and kids'
#: segments, and three things went wrong at once: the same page was fetched
#: three times, the per-URL gender union that is the *only* way `unisex` is
#: ever found never happened, and whichever segment staged last silently
#: decided the offer's department.
#:
#: Sizeer's first accessory sweep came back **461 women against 1 man** --
#: 1,096 URLs for 570 articles. The segments really do differ (14 of 18 caps
#: shared between men's and women's, checked directly); nothing could see it.
#:
#: For this platform the matched span *is* the canonical URL, and the bare
#: form serves the same page byte for byte -- verified on three products.
#: Other adapters match only part of their URL, so this is opt-in.
CANONICALISE_MATCH = frozenset({"aspnet_mk"})


def extract_links(html: str, pattern: re.Pattern[str], base_url: str,
                  canonical: bool = False) -> list[str]:
    """Absolute, de-duplicated URLs matching ``pattern``, order preserved.

    ``canonical`` keeps only the matched span, for the platforms listed in
    :data:`CANONICALISE_MATCH`.
    """
    seen: dict[str, None] = {}
    for raw in _candidate_links(html):
        candidate = raw.replace("&amp;", "&").strip()
        found = pattern.search(candidate)
        if not found:
            continue
        link = found.group(0) if canonical else candidate
        seen.setdefault(urljoin(base_url, link), None)
    return list(seen)


#: A product URL inside a JSON listing rather than an HTML one. The
#: WooCommerce Store API states each product's own canonical address in
#: `permalink`, with the slashes escaped as JSON requires::
#:
#:     "permalink":"https:\/\/e-elixir.mk\/shop\/valentino-donna-edp\/"
#:
#: Reading it is what lets one discovery driver walk an API listing and an
#: HTML category page alike. The alternative -- a second driver for JSON --
#: would have to re-implement pagination, facet labelling and the
#: saturation rules, none of which differ.
_JSON_LINK = re.compile(r'"(?:permalink|link)"\s*:\s*"([^"]+)"')


def _candidate_links(body: str) -> list[str]:
    """Every URL a listing body offers, HTML or JSON."""
    links = re.findall(r'href=["\']([^"\']+)["\']', body, re.I)
    links += [m.replace(r"\/", "/") for m in _JSON_LINK.findall(body)]
    return links


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
    # e-elixir, the WooCommerce Store API: /shop/valentino-donna-edp/
    "woocommerce": re.compile(r"/shop/[^/?#]+/?$", re.I),
    # schatze, nopCommerce: /women/pour-homme-edt-2, /men/1-million-edt.
    # Two segments, the first being the shelf the shop filed it under.
    #
    # The exclusions are measured, not imagined: of 27 two-segment links on
    # a listing page, 24 are products and the other three are
    # /customer/addresses, /customer/info and /order/history. The account
    # and board prefixes are listed too -- they are in the shop's own
    # robots.txt, so they exist, and a crawl that followed one would be
    # fetching a login wall.
    "nopcommerce": re.compile(
        r"^/(?!customer/|order/|boards/|checkout/|compareproducts/"
        r"|manufacturer/|newsletter/|passwordrecovery/|returnrequest/)"
        r"[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*/?$", re.I),
}


@dataclass(frozen=True)
class SitemapPlan:
    index_path: str
    #: Only follow children whose URL contains this, for an index that also
    #: lists sitemaps we do not want. No active plan needs it since megasport
    #: moved to category pagination; kept because the next sitemap shop will.
    child_contains: str | None = None
    strategy: str = "sitemap"


@dataclass(frozen=True)
class PaginatedPlan:
    #: (path, category slug implied by that path), or a :class:`Facet`, which
    #: carries a gender and the shop's own label as well.
    categories: tuple[tuple[str, str | None], ...]
    page_suffix: str = "/page-{page}"
    max_pages: int = 200
    #: Ignore any advertised total and walk pages until one comes back with no
    #: products on it.
    #:
    #: For a shop whose paginator renders a *window* rather than the last
    #: page. sport-m shows "1 2 3 4" on a facet that runs to 47, so both the
    #: `data-total-pages` attribute and the highest paginator link understate
    #: it -- believing either caps the facet at 72 products instead of 840.
    #: Costs one extra request per category, the empty page that ends it.
    walk_until_empty: bool = False
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


class Facet(NamedTuple):
    """One listing URL, and what finding a product there proves about it.

    A plain ``(path, category)`` pair still works wherever a plan takes
    facets -- :func:`as_facets` widens it -- because most plans only ever knew
    the category. V17 added the other two fields:

    ``gender``
        Who the shop sells this department to. The strong source for
        ``product.gender``: title words reach 4.9 percent of men's titles, and
        EU sizes cannot separate men from women at all, since 36-46 is shared.

    ``label``
        The shop's own name for the facet, kept verbatim for
        ``merchant_offer.merchant_category_path``. sportm's "Патики-ниски" is
        not a canonical category -- it is that shop's merchandising, and two
        shops can file one article differently and both be right -- so it is
        recorded next to the offer rather than resolved into the product.
    """
    path: str
    category: str | None = None
    gender: str | None = None
    label: str | None = None


def as_facets(entries) -> list[Facet]:
    """Widen plan entries to :class:`Facet`, leaving Facets alone."""
    out = []
    for entry in entries:
        out.append(entry if isinstance(entry, Facet) else Facet(*entry))
    return out


DISCOVERY_PLANS: dict[str, SitemapPlan | PaginatedPlan | SampledPlan] = {
    "magento_html": SitemapPlan(index_path="/media/sitemap/dsport.xml"),
    # megasport. Its sitemap is reachable and was what we used first, but it
    # indexes the whole shop -- 20 children, roughly 4 000 products, of which
    # only the ~1 600 below are footwear. That is not merely wasteful. The
    # storefront's filter excludes *known* non-footwear and keeps products
    # with no category, on the reasoning that an uncategorised product was
    # reached through a footwear facet and so is probably a shoe. True of
    # every plan here; false of a catalogue-wide sitemap. Of the 529 products
    # the sitemap brought us, 216 are footwear and 73 have no category at
    # all, and that bucket really is mixed -- shoes this shop abbreviates
    # "ПАТ" or "CALZ." sitting next to jackets, shorts and a waist bag, the
    # last of which the storefront was serving as footwear.
    #
    # So discovery is scoped to the three footwear trees, which are disjoint
    # (no unisex facet to double-count) and carry the hint that keeps those
    # "ПАТ" products out of the uncategorised bucket in the first place.
    # Verified against a manual count: 641 + 261 + 717 = 1 619.
    "woocommerce_html": PaginatedPlan(categories=(
        ("/kategorija/mazhi/obuvki-mazhi/", "footwear"),
        ("/kategorija/zheni/obuvki-zheni/", "footwear"),
        ("/kategorija/deca/obuvki/", "footwear"),
    # WooCommerce paginates as /page/2/, not Sport Vision's /page-2, and
    # prints no total -- see parse_last_page_link.
    ), page_suffix="page/{page}/"),
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
    # sizeer + sport-m. Segment=03 / Grupa=01 is this platform's footwear
    # branch, which is exactly the context its titles omit: "Adidas Handball
    # Spezial" names no category at all, and discovery knew it was a shoe
    # before it was fetched.
    #
    # This was a SampledPlan, which re-requested one facet URL until it
    # stopped yielding new products. That assumed the shop returns a rotating
    # subset. Measured: it does not. Three consecutive requests returned an
    # identical 18 products on both shops, so the facet saturated after four
    # requests holding one page's worth -- which is precisely the 331 and 333
    # products we held, mistaken for the whole catalogue.
    #
    # The real pagination is `&Page=N`, and it reaches 418 on sizeer (24
    # pages, verified: page 25 is empty) and 840 on sport-m (47 pages). The
    # brand facets and the search sweep existed to work around sampling --
    # narrower pools saturate sooner -- and that rationale goes with it: the
    # group facet now returns its whole pool, and PodGrupa 500/502/503 are
    # subsets of it (503 is 378 of the 418).
    "aspnet_mk": PaginatedPlan(categories=(
        ("/ProductCatalog?Segment=03&Grupa=01", "footwear"),
    # The suffix joins an existing query string, and sport-m's paginator
    # shows a window rather than a last page -- hence walking. 120 pages is
    # roughly double the deepest facet measured.
    ), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
    # The API adapters discover through their own paginated endpoints and do
    # not need URL enumeration; they are robots-blocked today in any case.
}

#: Plans that belong to one shop rather than to its platform. Checked before
#: :data:`DISCOVERY_PLANS`.
#:
#: aspnet_mk is white-label: sizeer and sport-m run the same software over
#: their own taxonomies. `Grupa=01` means footwear in both, but `Segment` is
#: the shop's own department numbering -- sizeer files footwear under 51, 52
#: and 53, sport-m under 03, 04, 05 and 07, and the numbers mean nothing in
#: common. A plan keyed on the adapter cannot express that, and the cost of
#: pretending it could was a whole catalogue read as one department: sizeer's
#: `Segment=03` returns exactly the 418 products of `Segment=51`, which we
#: took for its entire footwear range of 1 017.
#:
#: Measured, by ProductID, walking each department to its first empty page:
#:   sizeer  51=418  52=422  53=209  ->  1 017 distinct (32 filed twice)
#:   sport-m 03, 04, 05, 07, all distinct on their first pages
#:
#: sizeer also exposes `Segment=55` ("БРЕНДОВИ"), 1 418 footwear products of
#: which 845 appear under no department at all. Left out deliberately: the
#: shop's own navigation does not reach them, so their status is unknown,
#: and including them would near-double the shop on a guess.
MERCHANT_PLANS: dict[str, SitemapPlan | PaginatedPlan | SampledPlan] = {
    "sizeer": PaginatedPlan(categories=(
        ("/ProductCatalog?Segment=51&Grupa=01", "footwear"),
        ("/ProductCatalog?Segment=52&Grupa=01", "footwear"),
        ("/ProductCatalog?Segment=53&Grupa=01", "footwear"),
    ), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
    # 03/04/05 are men, women and kids: 840 + 397 + 832, which is a manual
    # count of 840/397/832 exactly, and 2 047 distinct once the 22 products
    # filed under two departments are counted once.
    #
    # Segment=07 is deliberately absent. It looks like a fourth department --
    # 113 pages, 2 030 products, more than any other -- and it is a
    # re-listing: measured by ProductID, every product in it is already in
    # 03/04/05 and it contributes exactly zero. Including it doubled
    # discovery to 4 099 listings for the same 2 047 products, so it bought
    # 113 wasted category pages and ~2 030 duplicate product fetches.
    "sportm": PaginatedPlan(categories=(
        ("/ProductCatalog?Segment=03&Grupa=01", "footwear"),
        ("/ProductCatalog?Segment=04&Grupa=01", "footwear"),
        ("/ProductCatalog?Segment=05&Grupa=01", "footwear"),
    ), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
}

# -----------------------------------------------------------------------------
# Facet plans -- the gender x category walk (V17)
# -----------------------------------------------------------------------------
#: Per-merchant plans whose facets carry a gender and a leaf category, used by
#: the ``facets`` command rather than by a sweep.
#:
#: Why these exist at all: category and gender are properties of *where* a
#: product was found, not of its title. Four of the six shops write "adidas
#: Supernova Rise" and nothing else, so pooling every merchant's title for a
#: product still leaves 2,580 of the 2,767 generic-footwear rows silent. The
#: facet is the evidence, and until V17 it was discarded after
#: ``create_product`` read it once.
#:
#: Why a separate plan from the sweep above: a sweep's job is to find products
#: to fetch, and it only needs enough facets to cover the catalogue. This walk
#: needs the *finest* department that still maps to a canonical bucket, and it
#: needs no product fetches at all -- the listing page is what carries the
#: facet. Gender x category partitions each shop, so the page count is set by
#: the product count and does not change; the overhead is one partial last
#: page per facet.
#:
#: Every URL here was fetched and confirmed to return products of its own.
#: Constructed is not the same as real: the shops' navigation links only some
#: combinations, and sportreality's women's Копачки facet and buzz's Копачки
#: facets came back empty, which is why they are absent rather than assumed.

#: The Sport Vision platform reads /mk/<category>/<gender>/<age>. The men's
#: and women's facets both include `unisex` -- that is the shops' own
#: construction, and it is the only evidence either publishes for a unisex
#: article: appearing in both adult departments is what unisex means here.
_SV_GENDERS = (
    ("men",   "maski+unisex/vozrasni"),
    ("women", "unisex+zenski/vozrasni"),
    ("kids",  "deca-momcinja+deca-devojcinja+kids+unisex/"
              "tinejdzeri+deca-malecki+bebe+kids-vozrast"),
)

#: buzz runs the same adapter over its own paths: `za-mazi` not `maski`, and
#: "Папучи и апостолки" where the others have "Папучи и сандали". Confirmed
#: by fetching: the sportvision spelling 404s on buzz, every one of them.
_BUZZ_GENDERS = (
    ("men",   "za-mazi+unisex/za-vozrasni"),
    ("women", "za-zeni+unisex/za-vozrasni"),
    ("kids",  "za-tinejdzeri+mali-deca+za-bebe"),
)


def _sv_facets(categories, genders) -> tuple[Facet, ...]:
    # No trailing slash: this platform's page suffix is "/page-2", and a
    # trailing slash would build ".../vozrasni//page-2".
    return tuple(
        Facet(path=f"/mk/{cat}/{suffix}", category=canonical, gender=gender,
              label=cat)
        for cat, canonical in categories
        for gender, suffix in genders)


#: Shared by sportvision and sportreality. Measured page counts on
#: sportvision: patiki 49/50/34, kopacki 4/1/3, konduri-i-cizmi 3/2/4,
#: papuci-i-sandali 7/7/8 -- against obuvki (the umbrella) at 61/58/48, so the
#: four leaves account for the shop and the umbrella is not walked.
_SV_CATEGORIES = (
    ("patiki", "sneakers"),
    ("kopacki", "cleats"),
    ("konduri-i-cizmi", "shoes_boots"),
    ("papuci-i-sandali", "slides_sandals"),
)

#: megasport's WooCommerce slugs are per-gender and inconsistent -- `konduri`
#: for men, `konduri-obuvki-zheni` for women, `konduri-obuvki` for kids -- so
#: they are listed rather than generated. Women's has no Копачки facet and
#: kids' Чизми lives at `chizmi-obuvki`; both match the shop's own navigation.
#: Two subcategories map to `shoes_boots` (Кондури and Чизми), which the
#: canonical bucket merges and `merchant_category_path` keeps apart.
_MEGA_FACETS = (
    ("/kategorija/mazhi/obuvki-mazhi/patiki-obuvki-mazhi/", "sneakers", "men"),
    ("/kategorija/mazhi/obuvki-mazhi/kopachki-obuvki-mazhi/", "cleats", "men"),
    ("/kategorija/mazhi/obuvki-mazhi/konduri/", "shoes_boots", "men"),
    ("/kategorija/mazhi/obuvki-mazhi/chizmi-obuvki-mazhi/", "shoes_boots",
     "men"),
    ("/kategorija/mazhi/obuvki-mazhi/papuchi-obuvki-mazhi/", "slides_sandals",
     "men"),
    ("/kategorija/zheni/obuvki-zheni/patiki-obuvki-zheni/", "sneakers",
     "women"),
    ("/kategorija/zheni/obuvki-zheni/konduri-obuvki-zheni/", "shoes_boots",
     "women"),
    ("/kategorija/zheni/obuvki-zheni/chizmi/", "shoes_boots", "women"),
    ("/kategorija/zheni/obuvki-zheni/papuchi-obuvki-zheni/", "slides_sandals",
     "women"),
    ("/kategorija/deca/obuvki/patiki/", "sneakers", "kids"),
    ("/kategorija/deca/obuvki/kopachki/", "cleats", "kids"),
    ("/kategorija/deca/obuvki/konduri-obuvki/", "shoes_boots", "kids"),
    ("/kategorija/deca/obuvki/chizmi-obuvki/", "shoes_boots", "kids"),
    ("/kategorija/deca/obuvki/papuchi/", "slides_sandals", "kids"),
)

#: aspnet_mk's `PodGrupa` is the product-group dictionary, and unlike
#: `Segment` it *is* shared between the two installations: 503 is
#: "Патики-ниски" on sizeer and on sport-m alike. So the codes are declared
#: once and the departments differ per shop.
_PODGRUPA = {
    "503": ("sneakers", "Патики-ниски"),
    "502": ("sneakers", "Патики-високи"),
    "599": ("shoes_boots", "Чизми"),
    "786": ("shoes_boots", "Балетанки"),
    "536": ("shoes_boots", "Мокасини"),
    "515": ("cleats", "Фудбал-сала"),
    "514": ("cleats", "Фудбал-копачки"),
    "779": ("cleats", "Патики за вештачка трева"),
    "500": ("slides_sandals", "Папучи"),
    "508": ("slides_sandals", "Сандали"),
    "587": ("slides_sandals", "Обувки за вода"),
    "537": ("slides_sandals", "Апостолки"),
}


def _aspnet_facets(departments) -> tuple[Facet, ...]:
    """Build Segment x PodGrupa facets from a shop's own department map."""
    out = []
    for segment, gender, codes in departments:
        for code in codes:
            canonical, label = _PODGRUPA[code]
            out.append(Facet(
                path=f"/ProductCatalog?Segment={segment}&Grupa=01"
                     f"&PodGrupa={code}",
                category=canonical, gender=gender, label=label))
    return tuple(out)


#: Which PodGrupa each shop publishes per department, read from their own
#: navigation. The sub-facets are subsets of the `Grupa=01` facet the sweep
#: walks, so a product in none of them keeps the generic footwear category it
#: already has -- the walk can only improve on what is there.
FACET_PLANS: dict[str, PaginatedPlan] = {
    "sportvision": PaginatedPlan(
        categories=_sv_facets(_SV_CATEGORIES, _SV_GENDERS)),
    "sportreality": PaginatedPlan(
        categories=_sv_facets(_SV_CATEGORIES, _SV_GENDERS)),
    # buzz sells no football boots: its three kopacki facets all returned
    # zero products, which agrees with its titles -- not one of its 1,921
    # offers carries a cleat word.
    "buzz": PaginatedPlan(
        categories=_sv_facets((("patiki", "sneakers"),
                               ("konduri-i-cizmi", "shoes_boots"),
                               ("papuci-i-apostolki", "slides_sandals")),
                              _BUZZ_GENDERS)),
    "megasport": PaginatedPlan(
        categories=tuple(Facet(path=p, category=c, gender=g,
                               label=p.rstrip("/").rsplit("/", 1)[-1])
                         for p, c, g in _MEGA_FACETS),
        page_suffix="page/{page}/"),
    "sizeer": PaginatedPlan(categories=_aspnet_facets((
        ("51", "men",   ("503", "502", "599", "500")),
        ("52", "women", ("786", "536", "503", "502", "599", "500", "508")),
        ("53", "kids",  ("503", "502", "599", "500", "508")),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
    "sportm": PaginatedPlan(categories=_aspnet_facets((
        ("03", "men",   ("503", "502", "599", "515", "514", "779", "500",
                         "508", "587", "537")),
        ("04", "women", ("786", "503", "502", "599", "500", "508", "587",
                         "537")),
        ("05", "kids",  ("503", "502", "599", "515", "514", "779", "500",
                         "508", "587", "537")),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
}

#: Every facet label in :data:`FACET_PLANS`, mapped to the canonical category
#: it implies. Built from the plans themselves, so a label and its meaning
#: cannot drift apart: changing one changes the other in the same edit.
#:
#: This is what lets ``merchant_offer.merchant_category_path`` hold the shop's
#: own word -- "Патики-ниски", "papuchi-obuvki-zheni" -- while derivation
#: still knows what it means. Labels repeat across shops ("patiki" on both
#: Sport Vision and megasport) and agree where they do; a test asserts it.
FACET_CATEGORY: dict[str, str] = {}
for _plan in FACET_PLANS.values():
    for _facet in as_facets(_plan.categories):
        if _facet.label and _facet.category:
            FACET_CATEGORY[_facet.label] = _facet.category

# -----------------------------------------------------------------------------
# Apparel facets (V18)
# -----------------------------------------------------------------------------
#: The same idea as FACET_PLANS, over the clothing trees. 17,035 listings
#: across the six shops -- more than the whole footwear catalogue -- counted
#: during recon and checked against a manual audit that matched to the
#: product on five of the six.
#:
#: Three things shape these lists, each found rather than assumed.
#:
#: **Only canonical slugs on the Sport Vision shops.** They run legacy and
#: current categories side by side: `dolen-del-trenerki` and
#: `dolni-delovi-trenerki-` return the identical 307 products for men, and
#: `jakni-i-eleci` (362) is `jakna` (290) plus `elek` (51). Walking both
#: spellings would fetch every page twice for nothing -- so only the
#: consolidated ones are here, and they happen to be merged exactly the way
#: V18's eleven buckets are, because the shop reached the same conclusion.
#:
#: **A catch-all last, where the tree is clean.** Discovery keeps the first
#: facet to claim a URL, so the specific facets come before the umbrella and
#: the umbrella picks up only what none of them covered -- as the parent
#: `apparel` category, meaning "clothing, kind unspecified".
#:
#: **No catch-all on megasport**, because its clothing tree is not clean:
#: `kapi-obleka`, 60 caps, sits inside it. Enumerating the real children
#: covers 640 of 671 men, 543 of 545 women and 212 of 228 kids, and keeps
#: headwear out of the apparel vertical -- the same trap the footwear
#: umbrella set, which is why those plans name their leaves too.

#: Categories no men's department stocks. Checked rather than assumed: every
#: one of these returned zero products for men on both shops, while
#: returning plenty for women. It is the same restriction the storefront nav
#: applies to `sports_bras` and `dresses_skirts`, arrived at from the shops'
#: own shelves rather than from the menu design.
_WOMEN_AND_KIDS = ("women", "kids")

#: (slug, canonical category, departments that stock it).
#:
#: Two near-identical slugs are per shop rather than shared: sportvision
#: writes `maica-dolgi-rakavi` and sportreality `maica-so-dolgi-rakavi`, and
#: each 404s on the other's spelling. One list carrying both spent three
#: requests per shop confirming a 404.
_SV_APPAREL = (
    ("maici", "tshirts", None),
    ("polo-maica", "tshirts", None),
    ("dres", "tshirts", None),
    ("sorc-i-maica", "tshirts", None),        # shorts-and-tee sets
    ("dukser", "hoodies", None),
    ("jakni-i-eleci", "jackets", None),
    ("dolni-delovi-trenerki-", "trousers", None),  # trailing dash is theirs
    ("pantaloni", "trousers", None),
    ("trenerka", "tracksuits", None),
    ("kombinezon", "tracksuits", None),
    ("sorcevi", "shorts", None),
    ("helanki-i-biciklisticki", "leggings", None),
    ("gradnik-i-top", "sports_bras", _WOMEN_AND_KIDS),
    ("dolna-obleka-", "underwear", None),
    ("fustani-i-suknji", "dresses_skirts", _WOMEN_AND_KIDS),
    ("dolg-fustan", "dresses_skirts", _WOMEN_AND_KIDS),
    ("kostimi-za-kapenje", "swimwear", None),
    # Clothing whose kind the shop does not narrow, then the umbrella.
    ("aktivna-obleka", "apparel", None),
    ("tekstil", "apparel", None),
)

#: The long-sleeve tee, spelled each shop's own way.
_SV_LONG_SLEEVE = {
    "sportvision": ("maica-dolgi-rakavi", "tshirts", None),
    "sportreality": ("maica-so-dolgi-rakavi", "tshirts", None),
}

#: buzz names its own, and during recon its leaves summed to its umbrella
#: exactly -- 833, 936, 351 -- so its tree is disjoint and complete.
_BUZZ_APPAREL = (
    ("maica", "tshirts", None),
    ("maica-bez-rakavi", "tshirts", None),
    ("majica-dolgi-rakavi", "tshirts", None),
    ("polo-maica", "tshirts", None),
    ("kosula", "tshirts", None),
    ("dres", "tshirts", None),
    ("sorcevi-i-maica", "tshirts", None),
    ("dukser", "hoodies", None),
    ("dzemper", "hoodies", None),
    ("vetrovki-i-jakni", "jackets", None),
    ("elek", "jackets", None),
    ("dolen-del-trenerki", "trousers", None),
    ("pantaloni", "trousers", None),
    ("trenerka", "tracksuits", None),
    ("set", "tracksuits", None),
    ("sorc", "shorts", None),
    ("helanki", "leggings", None),
    ("helanki-7-8", "leggings", None),
    ("biciklisticke", "leggings", None),
    ("gradnik", "sports_bras", _WOMEN_AND_KIDS),
    ("top", "sports_bras", _WOMEN_AND_KIDS),
    ("bodi", "sports_bras", _WOMEN_AND_KIDS),
    ("bokserici", "underwear", None),
    ("dolna-obleka", "underwear", None),
    ("fustan", "dresses_skirts", _WOMEN_AND_KIDS),
    ("suknja", "dresses_skirts", _WOMEN_AND_KIDS),
    ("kostimi-za-kapenje", "swimwear", None),
    ("tekstil", "apparel", None),
)

#: megasport, whose slugs differ per gender for the same thing -- `konduri`
#: for men against `konduri-obuvki-zheni` for women was the footwear version
#: of the same habit -- so they are listed rather than generated.
_MEGA_APPAREL = (
    ("/kategorija/mazhi/obleka-mazhi/maici/", "tshirts", "men"),
    ("/kategorija/mazhi/obleka-mazhi/bluza/", "tshirts", "men"),
    ("/kategorija/mazhi/obleka-mazhi/polo-bluza/", "tshirts", "men"),
    ("/kategorija/mazhi/obleka-mazhi/dukseri-obleka-mazhi/", "hoodies", "men"),
    ("/kategorija/mazhi/obleka-mazhi/jakni-obleka-mazhi/", "jackets", "men"),
    ("/kategorija/mazhi/obleka-mazhi/dolna-trenerka/", "trousers", "men"),
    ("/kategorija/mazhi/obleka-mazhi/pantaloni/", "trousers", "men"),
    ("/kategorija/mazhi/obleka-mazhi/ski-pantaloni-obleka-mazhi/",
     "trousers", "men"),
    ("/kategorija/mazhi/obleka-mazhi/komplet-trenerki-obleka-mazhi/",
     "tracksuits", "men"),
    ("/kategorija/mazhi/obleka-mazhi/shorcevi/", "shorts", "men"),
    ("/kategorija/mazhi/obleka-mazhi/helanki-obleka-mazhi/",
     "leggings", "men"),
    ("/kategorija/mazhi/obleka-mazhi/pododelo-obleka-mazhi/",
     "underwear", "men"),
    ("/kategorija/mazhi/obleka-mazhi/kupaki/", "swimwear", "men"),
    ("/kategorija/zheni/obleka/maici-obleka/", "tshirts", "women"),
    ("/kategorija/zheni/obleka/dukseri/", "hoodies", "women"),
    ("/kategorija/zheni/obleka/jakni/", "jackets", "women"),
    ("/kategorija/zheni/obleka/dolna-trenerka-obleka/", "trousers", "women"),
    ("/kategorija/zheni/obleka/ski-pantaloni-obleka/", "trousers", "women"),
    ("/kategorija/zheni/obleka/komplet-trenerki/", "tracksuits", "women"),
    ("/kategorija/zheni/obleka/shorcevi-obleka/", "shorts", "women"),
    ("/kategorija/zheni/obleka/helanki/", "leggings", "women"),
    ("/kategorija/zheni/obleka/sportski-gradnik/", "sports_bras", "women"),
    ("/kategorija/zheni/obleka/pododelo-obleka/", "underwear", "women"),
    ("/kategorija/zheni/obleka/kostimi-za-kapene/", "swimwear", "women"),
    ("/kategorija/deca/obleka-deca/maici-deca/", "tshirts", "kids"),
    ("/kategorija/deca/obleka-deca/jakni-obleka-deca/", "jackets", "kids"),
    ("/kategorija/deca/obleka-deca/ski-pantaloni/", "trousers", "kids"),
    ("/kategorija/deca/obleka-deca/komplet-trenerki-obleka-deca/",
     "tracksuits", "kids"),
    ("/kategorija/deca/obleka-deca/kompleti-detski/", "tracksuits", "kids"),
    ("/kategorija/deca/obleka-deca/socevi/", "shorts", "kids"),
    ("/kategorija/deca/obleka-deca/helanki-obleka-deca/", "leggings", "kids"),
    ("/kategorija/deca/obleka-deca/pododelo/", "underwear", "kids"),
)

#: aspnet `PodGrupa` codes for clothing, read from the shops' own navigation
#: and shared between the two installations exactly as the footwear codes
#: are.
#:
#: The nav links only 12 of the 26 subgroups the facet sidebar counts --
#: Градник, Пододело, Дресови and others are counted but never linked, so
#: there is no code to address them by. Hence the catch-all: everything the
#: specific facets miss lands as clothing of unspecified kind, which is true
#: and improvable, rather than missing.
_PODGRUPA_APPAREL = {
    "496": ("tshirts", "Маици"),
    "495": ("tshirts", "Маица со долги ракави"),
    "540": ("tshirts", "Кошули"),
    "797": ("tshirts", "Македонски дрес"),
    "486": ("hoodies", "Блузони"),
    "796": ("hoodies", "Џемпери"),
    "614": ("hoodies", "Полари"),
    "492": ("jackets", "Јакни"),
    "794": ("jackets", "Тексас јакни"),
    "616": ("jackets", "Софтшел"),
    "597": ("jackets", "Елек"),
    # "Шушкавец" is the rustly shell garment. On these shops it sits beside
    # Јакни rather than beside Панталони, so it is filed with jackets; a
    # title rule can disagree later with better evidence.
    "521": ("jackets", "Шушкавци"),
    "499": ("trousers", "Панталони"),
    "787": ("trousers", "Фармерки"),
    "513": ("tracksuits", "Тренерки"),
    "584": ("tracksuits", "Летни комплети"),
    "520": ("shorts", "Шорцеви"),
    "795": ("shorts", "Тексас шорцеви"),
    "517": ("leggings", "Хеланки"),
    "516": ("dresses_skirts", "Фустани"),
    "510": ("dresses_skirts", "Здолништа"),
    "441": ("swimwear", "Шорцеви за пливање"),
    "588": ("swimwear", "Костим за капење"),
}


def _sv_apparel_facets(categories, genders, extra=None) -> tuple[Facet, ...]:
    """Build the facets, skipping departments that do not stock a category.

    `only` is not a guess about what a shop ought to sell: each restriction
    below was measured, by fetching the facet and finding it empty for men
    and full for women.
    """
    # The shop-specific entry goes first, never last: the umbrella closes
    # the list, and discovery keeps the first facet to claim a URL, so an
    # entry after it would never win anything.
    entries = ([extra] if extra else []) + list(categories)
    return tuple(
        Facet(path=f"/mk/{cat}/{suffix}", category=canonical, gender=gender,
              label=cat)
        for cat, canonical, only in entries
        for gender, suffix in genders
        if only is None or gender in only)


def _aspnet_apparel_facets(departments) -> tuple[Facet, ...]:
    """Specific subgroups first, then each department as a catch-all."""
    out = []
    for segment, gender, codes in departments:
        for code in codes:
            canonical, label = _PODGRUPA_APPAREL[code]
            out.append(Facet(
                path=f"/ProductCatalog?Segment={segment}&Grupa=02"
                     f"&PodGrupa={code}",
                category=canonical, gender=gender, label=label))
    for segment, gender, _codes in departments:
        out.append(Facet(
            path=f"/ProductCatalog?Segment={segment}&Grupa=02",
            category="apparel", gender=gender, label="Текстил"))
    return tuple(out)


APPAREL_FACET_PLANS: dict[str, PaginatedPlan] = {
    "sportvision": PaginatedPlan(
        categories=_sv_apparel_facets(_SV_APPAREL, _SV_GENDERS,
                                      _SV_LONG_SLEEVE["sportvision"])),
    "sportreality": PaginatedPlan(
        categories=_sv_apparel_facets(_SV_APPAREL, _SV_GENDERS,
                                      _SV_LONG_SLEEVE["sportreality"])),
    "buzz": PaginatedPlan(
        categories=_sv_apparel_facets(_BUZZ_APPAREL, _BUZZ_GENDERS)),
    "megasport": PaginatedPlan(
        categories=tuple(Facet(path=p, category=c, gender=g,
                               label=p.rstrip("/").rsplit("/", 1)[-1])
                         for p, c, g in _MEGA_APPAREL),
        page_suffix="page/{page}/"),
    "sizeer": PaginatedPlan(categories=_aspnet_apparel_facets((
        ("51", "men",   ("496", "495", "540", "486", "492", "794", "521",
                         "499", "787", "520", "795", "441")),
        ("52", "women", ("496", "495", "540", "486", "796", "492", "794",
                         "521", "499", "787", "520", "795")),
        ("53", "kids",  ("496", "495", "486", "492", "597", "521", "499",
                         "787", "513", "584", "520", "517", "516", "510",
                         "588")),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
    "sportm": PaginatedPlan(categories=_aspnet_apparel_facets((
        ("03", "men",   ("496", "495", "540", "486", "492", "794", "616",
                         "521", "499", "787", "513", "797")),
        ("04", "women", ("496", "495", "486", "796", "492", "794", "616",
                         "521", "499", "787", "513", "797")),
        ("05", "kids",  ("496", "495", "486", "614", "492", "521", "499",
                         "787", "513", "520", "517", "516")),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
}

#: Apparel facet labels folded into the same mapping the footwear ones use,
#: so `OfferEvidence.facet_category` keeps working without knowing which
#: vertical a label came from. `setdefault`, because a label shared with
#: footwear (there are none today) must not change meaning here.
for _plan in APPAREL_FACET_PLANS.values():
    for _facet in as_facets(_plan.categories):
        if _facet.label and _facet.category:
            FACET_CATEGORY.setdefault(_facet.label, _facet.category)


# -----------------------------------------------------------------------------
# Опрема facets (V23)
# -----------------------------------------------------------------------------
#: The third vertical. Every slug below was confirmed by
#: `tools/probe_accessory_slugs.py` rather than transliterated and hoped for,
#: and the probe is the reason this list looks the way it does.
#:
#: **The shops drop the `h`.** `chorapi` 404s and `corapi` answers, on all
#: three Sport Vision family shops; so do `kacketi-i-kapi`, `sise-za-voda`,
#: `naocari-za-plivanje` and `oprema-za-cistenje`. The transliterator
#: produces the other spelling, which is how `/mk/sorc/` once held 835 offers
#: no rule could read.
#:
#: **sportvision and sportreality do not share a list**, unlike
#: apparel. One writes `kacketi-i-kapi` and the other `kapa` and
#: `kacket` both; sportreality names forty-eight sections where
#: sportvision names nineteen. (`ranci` 404s on sportreality --
#: `ranec` does not, and an earlier note here said otherwise.)
#:
#: **Unisex is walked explicitly**, which the other two verticals never do.
#: Equipment is 55 percent unisex on sportvision and 66 on sportreality,
#: against 4.2 percent of footwear, and discovery collects every department a
#: URL was found in -- so a bare `unisex/vozrasni` alongside the two bundled
#: suffixes resolves those articles to `unisex` outright instead of leaving
#: it to be inferred. It costs a fourth walk per category and is the only
#: thing that genders Sport Reality's 404 unisex articles correctly.
_SV_ACC_GENDERS = _SV_GENDERS + (("unisex", "unisex/vozrasni"),)
_BUZZ_ACC_GENDERS = _BUZZ_GENDERS + (("unisex", "unisex/za-vozrasni"),)

#: (slug, canonical category, departments that stock it).
_SV_ACCESSORY = (
    ("corapi", "socks", None),
    ("kacketi-i-kapi", "caps_hats", None),
    ("ranec", "bags_backpacks", None),
    ("sise-za-voda", "other_accessories", None),
    ("oprema-za-plivanje", "swim_gear", None),
    ("naocari-za-plivanje", "swim_gear", None),
    # The mask shelf, and a facet rather than a keyword on purpose: "маска"
    # alone is a face mask as often as a diving one, and the
    # `other_accessories` rule claims those. Sport Vision is the only shop
    # that publishes it, and it holds three Speedo swim masks and a J2C --
    # the J2C was in Облека за капење, because its title says nothing but
    # "Swim" and the swimwear rule runs before any equipment one.
    ("maska", "swim_gear", None),
    ("topka", "balls_training", None),
    ("podloga", "balls_training", None),
    ("oprema-za-trening", "balls_training", None),
    ("golmanski-rakavici", "gloves", None),
    ("kaciga", "protective_gear", None),
    ("roleri", "skates_scooters", None),
    ("pribor-i-dodatoci-za-obuvki", "other_accessories", None),
    # Sport-specific shelves that mix leaves -- a football one holds balls,
    # shin guards and gloves together -- so the parent is the truest answer
    # rather than a shrug.
    ("oprema-za-fudbal", "accessories", None),
    ("oprema-za-ping-pong", "accessories", None),
    ("oprema-za-planinarenje", "accessories", None),
    ("oprema-za-skijanje", "accessories", None),
    ("ostanata-oprema", "accessories", None),
    # The umbrella last: discovery keeps the first facet to claim a URL, so
    # anything above wins and this picks up only what none of them covered.
    ("oprema", "accessories", None),
)

#: sportreality, rebuilt from the sections its own offers sit in rather than
#: from a candidate list.
#:
#: The first version of this was built from recon labels, probed, and still
#: wrong: 326 of its 609 offers arrived through the `oprema` umbrella because
#: the list named eight sections and the shop uses forty-eight. The probe
#: confirmed everything it was asked about and could not say a word about
#: what it was never asked -- `kapa` with 92 offers, `ranec` with 60,
#: `vreka-za-trening` with 11, which an earlier note here called unlocated.
#:
#: So these come from the URL sections of products already ingested, which is
#: the only source that cannot omit anything the shop actually sells.
#:
#: Five are deliberately absent. `set`, `potnik`, `traka`, `rosuli` and
#: `rakav` are genuinely ambiguous and the umbrella is the honest answer for
#: them; `velosiped` is excluded outright.
#:
#: `potnik` is still absent *here* -- it is not a shelf worth walking, since
#: "потник" is a singlet as often as a sweatband -- but
#: `taxonomy._RULES` does now read it off the URL of products already
#: ingested, where it resolves to `other_accessories`. On this shop that
#: shelf holds Slazenger wristbands and Nike hair ties. Measured over 35 873
#: live offers: 9 products move, all of them out of the umbrella, and no
#: garment is touched.
_SR_ACCESSORY = (
    ("corapi", "socks", None),
    ("stucni", "socks", None),
    ("kapa", "caps_hats", None),
    ("kacket", "caps_hats", None),
    ("podkapa", "caps_hats", None),
    ("sal", "caps_hats", None),
    # With `traka-za-kosa` below, and for the same reason: a sweatband
    # is not headwear. The facet is read before `classify`, so both the
    # mapping and the keyword had to move.
    ("traka-za-glava", "other_accessories", None),
    ("grejac-za-vrat", "caps_hats", None),
    ("ranec", "bags_backpacks", None),
    ("torbi", "bags_backpacks", None),
    ("torbica", "bags_backpacks", None),
    ("kufer", "bags_backpacks", None),
    ("vreka-za-trening", "bags_backpacks", None),
    ("paricnik", "wallets", None),
    ("golmanski-rakavici", "gloves", None),
    ("rakavici", "gloves", None),
    ("kostobran", "protective_gear", None),
    ("stitnik", "protective_gear", None),
    ("stitnik-za-zabi", "protective_gear", None),
    ("bandazer", "protective_gear", None),
    ("stegac", "protective_gear", None),
    ("suspenzor", "protective_gear", None),
    ("kaciga", "protective_gear", None),
    ("naocari-za-skijanje", "protective_gear", None),
    ("topka", "balls_training", None),
    ("pumpa", "balls_training", None),
    ("jaze-za-skokanje", "balls_training", None),
    ("podloga", "balls_training", None),
    ("pomagalo-za-sklekovi", "balls_training", None),
    ("fitnes-rekvizit", "balls_training", None),
    ("sise-za-voda", "other_accessories", None),
    ("kapa-za-plivanje", "swim_gear", None),
    ("naocari-za-plivanje", "swim_gear", None),
    ("maska-i-perai", "swim_gear", None),
    ("cepovi-za-usi", "swim_gear", None),
    ("stipka-za-nos", "swim_gear", None),
    ("vloski", "other_accessories", None),
    ("sprej", "other_accessories", None),
    ("roleri", "skates_scooters", None),
    ("trotinet", "skates_scooters", None),
    ("ostrica-za-klizalki", "skates_scooters", None),
    ("ostanata-oprema", "accessories", None),
    # Last, so it picks up only what none of the above claimed.
    ("oprema", "accessories", None),
)

#: buzz, rebuilt from its own offers' URL sections after run 39.
#:
#: Its tree really is simpler than sportreality's -- 21 sections against 48,
#: and the catch-all held only 4.3 percent of the sweep rather than 54. But
#: the first list was still wrong about the biggest thing on the shop: it
#: named `kacketi-i-kapi`, which answers and holds almost nothing, while
#: `kapa` (138 offers) and `kacket` (45) are where the hats are.
_BUZZ_ACCESSORY = (
    ("corapi", "socks", None),
    ("kapa", "caps_hats", None),
    ("kacket", "caps_hats", None),
    ("kacketi-i-kapi", "caps_hats", None),
    # A hair tie, not headwear -- unlike its neighbour
    # `traka-za-glava`, which is a headband and stays. Both the facet
    # and the keyword had to move: this mapping is consulted before
    # `classify`, so changing only the rule left them here.
    ("traka-za-kosa", "other_accessories", None),
    ("ranec", "bags_backpacks", None),
    ("torbica", "bags_backpacks", None),
    ("torba", "bags_backpacks", None),
    ("kufer", "bags_backpacks", None),
    ("vreka-za-trening", "bags_backpacks", None),
    ("paricnik", "wallets", None),
    ("rakavici", "gloves", None),
    ("sise-za-voda", "other_accessories", None),
    ("sprej", "other_accessories", None),
    ("vloski", "other_accessories", None),
    ("vrvci", "other_accessories", None),
    ("oprema-za-cistenje", "other_accessories", None),
    ("ukras", "other_accessories", None),
    ("privezok", "other_accessories", None),
    ("ostanata-oprema", "accessories", None),
    # Last, so it picks up only what none of the above claimed. `set` and
    # `kapsuli` are deliberately unnamed -- both are ambiguous and this is
    # the honest answer for them. `pet-ogrlica` is excluded outright.
    ("oprema", "accessories", None),
)

#: megasport repeats the gender inside the slug -- the habit its apparel plan
#: already records -- so these are full paths rather than a slug crossed with
#: a suffix. Read off its own navigation, because it soft-404s: a slug that
#: cannot exist answers 200 with the same 54 products as a real one, so
#: nothing about this shop can be confirmed by asking whether a URL answers.
#:
#: `torbi-ranci-i-parichnici` is one facet for bags, backpacks *and* wallets.
#: It resolves to the broader leaf, and a title naming a wallet still wins --
#: see the `wallets` rule in `mkagg.taxonomy`.
_MEGA_ACCESSORY = (
    ("/kategorija/mazhi/oprema-mazhi/chorapi-oprema-mazhi/", "socks", "men"),
    ("/kategorija/mazhi/oprema-mazhi/kapi/", "caps_hats", "men"),
    ("/kategorija/mazhi/oprema-mazhi/ski-bandana/", "caps_hats", "men"),
    ("/kategorija/mazhi/oprema-mazhi/torbi-ranci-i-parichnici/",
     "bags_backpacks", "men"),
    # megasport suffixes its slugs with the department, so these three
     # escaped the V33 repointing that caught the bare `rakavici`. They are
     # the shop's glove shelves and they carried five gloves -- two Nike
     # goalkeeper pairs, two Brugi, one Icepeak -- on in `protective_gear`
     # long after the leaf existed, because `FACET_CATEGORY` is consulted
     # before `classify` and the taxonomy rule never got a say.
    ("/kategorija/mazhi/oprema-mazhi/rakavici-oprema-mazhi/",
     "gloves", "men"),
    ("/kategorija/mazhi/oprema-mazhi/kacigi-oprema-mazhi/",
     "protective_gear", "men"),
    ("/kategorija/mazhi/oprema-mazhi/naochari/", "protective_gear", "men"),
    ("/kategorija/zheni/oprema-zheni/torbici/", "bags_backpacks", "women"),
    ("/kategorija/zheni/oprema-zheni/rakavici-oprema-zheni/",
     "gloves", "women"),
    ("/kategorija/zheni/oprema-zheni/kacigi-oprema-zheni/",
     "protective_gear", "women"),
    ("/kategorija/zheni/oprema-zheni/ski-bandana-oprema-zheni/",
     "caps_hats", "women"),
    ("/kategorija/deca/oprema-deca/ranec/", "bags_backpacks", "kids"),
    ("/kategorija/deca/oprema-deca/rakavici/", "gloves", "kids"),
    ("/kategorija/deca/oprema-deca/kacigi-oprema-deca/",
     "protective_gear", "kids"),
    # Outside the gender tree entirely, and absent from recon. Sixteen
    # products, no department: the facet carries no gender rather than
    # guessing one.
    ("/kategorija/ski-oprema/naochari-za-skijane/", "protective_gear", None),
)

#: The department pages themselves, which hold most of the stock.
#:
#: Run 40 found 334 products against a recon count of 579, and enumerating
#: the subtree explained the gap rather than closing it: those fifteen paths
#: really are every child megasport publishes. The shop simply does not
#: subdivide most of its equipment -- `/oprema-mazhi/` carries far more than
#: its seven children do between them.
#:
#: `label=None` is the load-bearing part, and it is not an oversight. A
#: labelled facet feeds `FACET_CATEGORY`, and `derive_category` takes a facet
#: over a title every time -- so an umbrella label would pin all 245 of these
#: to the parent and no later pass could improve on it. Without one, the
#: offer still carries `category_hint="accessories"` (which is what picks the
#: run kind, and must be right) while the *leaf* is left to the title.
#:
#: That is worth doing only because megasport's titles are unusually good:
#: they lead with the Macedonian category word, as this shop's entries in
#: `mkagg.taxonomy.classify` have documented since V17 -- "GH0331 Чорапи ACT
#: CORE MID CREW SOCK 3P - Megasport". The Sport Vision family's titles do
#: not, which is why their umbrellas stay labelled.
_MEGA_ACCESSORY_UMBRELLAS = (
    ("/kategorija/mazhi/oprema-mazhi/", "accessories", "men"),
    ("/kategorija/zheni/oprema-zheni/", "accessories", "women"),
    ("/kategorija/deca/oprema-deca/", "accessories", "kids"),
    # A second kids tree lives beside the first. Its two children duplicate
    # `oprema-deca`'s, but the department page is distinct and the URL
    # dedupe in discovery handles any overlap.
    ("/kategorija/deca/oprema/", "accessories", "kids"),
    ("/kategorija/ski-oprema/", "accessories", None),
)

#: The aspnet subgroup dictionary, accessory half. Both shops publish the
#: whole list on every catalogue page, so these codes were read rather than
#: guessed.
#:
#: Four codes are deliberately absent -- 798 pets, 742 Funko, 649 bicycles,
#: 740 watches. Leaving them out of the walk is half the exclusion; the other
#: half is `mkagg.taxonomy.is_excluded`, because the Спецификации parser
#: reads subgroups off the product page and would otherwise let them in by a
#: different door.
_PODGRUPA_ACCESSORY = {
    "096": ("protective_gear", "Наочари"),
    "106": ("skates_scooters", "Ролери"),
    "107": ("skates_scooters", "Скироли"),
    "111": ("skates_scooters", "Тротинети"),
    "277": ("swim_gear", "Капи за пливање"),
    "487": ("gloves", "Голмански ракавици"),
    "489": ("other_accessories", "Друго"),
    "493": ("caps_hats", "Капи"),
    "494": ("protective_gear", "Костобрани"),
    "497": ("swim_gear", "Наочари за пливање"),
    "507": ("bags_backpacks", "Ранци"),
    "512": ("bags_backpacks", "Торби"),
    "518": ("socks", "Чорапи"),
    "519": ("other_accessories", "Шишиња"),
    "548": ("other_accessories", "Средство за заштита од влага"),
    "550": ("other_accessories", "Средство за отстранување на миризби"),
    "560": ("other_accessories", "Комбинирана четка за велур кожа"),
    "591": ("caps_hats", "Бандани"),
    "607": ("other_accessories", "Врвки"),
    "628": ("balls_training", "Држачи за склекови"),
    "638": ("other_accessories", "Средство за чистење на обувки"),
    "667": ("balls_training", "Баланс топка"),
    "678": ("other_accessories", "Термос"),
    "704": ("other_accessories", "Заштитна маска за лице"),
    "761": ("bags_backpacks", "Торбички"),
    "782": ("caps_hats", "Зимски капи"),
}


def _sv_accessory_facets(categories, genders) -> tuple[Facet, ...]:
    """Slug crossed with department, umbrella last."""
    return tuple(
        Facet(path=f"/mk/{cat}/{suffix}", category=canonical, gender=gender,
              label=cat)
        for cat, canonical, only in categories
        for gender, suffix in genders
        if only is None or gender in only)


def _aspnet_accessory_facets(departments) -> tuple[Facet, ...]:
    """Subgroups first, then each department as a catch-all.

    ``gender=None`` is a real entry here, not an oversight. Sport-M sells its
    Опрема at `Segment=06` with no department anywhere in the URL -- 758
    articles -- and the Спецификации table on each product page is what
    genders them. A facet claiming a gender it cannot see would be worse than
    none, because `resolve_departments` would then have two answers to
    reconcile instead of one to find.
    """
    out = []
    for segment, gender, codes in departments:
        for code in codes:
            canonical, label = _PODGRUPA_ACCESSORY[code]
            out.append(Facet(
                path=f"/ProductCatalog?Segment={segment}&Grupa=03"
                     f"&PodGrupa={code}",
                category=canonical, gender=gender, label=label))
    for segment, gender, _codes in departments:
        out.append(Facet(
            path=f"/ProductCatalog?Segment={segment}&Grupa=03",
            category="accessories", gender=gender, label="Додатоци"))
    return tuple(out)


#: Every code either shop publishes. Walking one with nothing in it costs a
#: single request and returns an empty page, which is cheaper than keeping a
#: per-segment list correct as the shops restock.
_ASPNET_ACC_CODES = tuple(sorted(_PODGRUPA_ACCESSORY))

ACCESSORY_FACET_PLANS: dict[str, PaginatedPlan] = {
    "sportvision": PaginatedPlan(
        categories=_sv_accessory_facets(_SV_ACCESSORY, _SV_ACC_GENDERS)),
    "sportreality": PaginatedPlan(
        categories=_sv_accessory_facets(_SR_ACCESSORY, _SV_ACC_GENDERS)),
    "buzz": PaginatedPlan(
        categories=_sv_accessory_facets(_BUZZ_ACCESSORY, _BUZZ_ACC_GENDERS)),
    "megasport": PaginatedPlan(
        categories=(
            tuple(Facet(path=path, category=cat, gender=gender,
                        label=path.rstrip("/").rsplit("/", 1)[-1])
                  for path, cat, gender in _MEGA_ACCESSORY)
            # Umbrellas last, and unlabelled. Discovery keeps the first facet
            # to claim a URL, so every child above wins first.
            + tuple(Facet(path=path, category=cat, gender=gender)
                    for path, cat, gender in _MEGA_ACCESSORY_UMBRELLAS)),
        page_suffix="page/{page}/"),
    "sizeer": PaginatedPlan(categories=_aspnet_accessory_facets((
        ("51", "men", _ASPNET_ACC_CODES),
        ("52", "women", _ASPNET_ACC_CODES),
        ("53", "kids", _ASPNET_ACC_CODES),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
    "sportm": PaginatedPlan(categories=_aspnet_accessory_facets((
        ("03", "men", _ASPNET_ACC_CODES),
        ("04", "women", _ASPNET_ACC_CODES),
        ("05", "kids", _ASPNET_ACC_CODES),
        # The standalone Опрема section. No gender in any URL, so none is
        # claimed; `mkagg.adapters.aspnet_mk.spec_gender` fills it in from
        # the product page.
        ("06", None, _ASPNET_ACC_CODES),
    )), page_suffix="&Page={page}", walk_until_empty=True, max_pages=120),
}

#: Folded into the same label mapping the other two verticals use.
#: `setdefault`, because a label shared with an earlier vertical must keep
#: its first meaning -- "Капи" and "Чорапи" appear in both aspnet
#: dictionaries and mean the same thing in each.
for _plan in ACCESSORY_FACET_PLANS.values():
    for _facet in as_facets(_plan.categories):
        if _facet.label and _facet.category:
            FACET_CATEGORY.setdefault(_facet.label, _facet.category)


# -----------------------------------------------------------------------------
# Fragrances (V27)
# -----------------------------------------------------------------------------
#: e-elixir, walked through its own Store API rather than its category
#: pages. Two facets, not one, and the overlap is the point: Женски мириси
#: holds 661 products and Машки мириси 516, which is 1 177 against a
#: Мириси root of 987. The 190 counted twice are the unisex ones, and
#: membership of both departments is the only evidence any shop here
#: publishes for unisex -- the same inference `resolve_departments` already
#: draws on the Sport Vision shops.
#:
#: Walking the 987-product root instead would be one request in three
#: cheaper and would lose that, leaving every fragrance to be read as men's
#: or women's by its shelf alone.
#:
#: `per_page=100` is the Store API's maximum. Category ids rather than
#: slugs because the endpoint takes ids; they are stable and were read from
#: /products/categories.
_EELIXIR_FRAGRANCE = (
    ("/wp-json/wc/store/v1/products?category=4419&per_page=100",
     "perfume", "women", "zhenski-mirisi"),
    ("/wp-json/wc/store/v1/products?category=4420&per_page=100",
     "perfume", "men", "mashki-mirisi"),
)

#: schatze walks one shelf, not four.
#:
#: Its /parfemi listing is the whole fragrance catalogue -- 53 pages -- and
#: it is the only listing on the shop that is guaranteed to hold nothing
#: else. The gendered shelves look tempting and are not: /men-2 renders
#: Clinique lotions under a heading that says "men", and the /women listing
#: mixes in /niche-fragrances URLs. Walking those would drag cosmetics into
#: a fragrance run and file them as perfume.
#:
#: Nothing is lost by it. e-elixir needs two facets because membership of
#: both departments is the only evidence it publishes for unisex; schatze
#: states Унисекс outright in each product's own breadcrumb, which the
#: adapter reads into `category_path`.
_SCHATZE_FRAGRANCE = (("/parfemi", "perfume", None, "parfemi"),)

FRAGRANCE_FACET_PLANS: dict[str, PaginatedPlan] = {
    "schatze": PaginatedPlan(
        categories=tuple(Facet(path=path, category=cat, gender=gender,
                               label=label)
                         for path, cat, gender, label in _SCHATZE_FRAGRANCE),
        page_suffix="?pagenumber={page}",
        # Walked to exhaustion rather than trusting a total.
        #
        # The paginator does render every page up to 53, so the number is
        # there -- but `parse_last_page_link` reads `/page/N` and this shop
        # writes `?pagenumber=N`, so it comes back None and the driver
        # would crawl page 1 and stop. A silent one-page crawl of a
        # 53-page shelf is a far worse failure than one extra request:
        # verified that ?pagenumber=60 returns no products at all, so the
        # empty page is a real stop signal.
        walk_until_empty=True, max_pages=80),
    "eelixir": PaginatedPlan(
        categories=tuple(Facet(path=path, category=cat, gender=gender,
                               label=label)
                         for path, cat, gender, label in _EELIXIR_FRAGRANCE),
        # The Store API paginates on `page`, and the listing is already a
        # query string, so the suffix joins with & rather than opening one.
        page_suffix="&page={page}",
        # The endpoint advertises no total in its body -- the count is in a
        # header this driver never sees -- so the only honest stop is a page
        # that comes back with nothing on it.
        walk_until_empty=True, max_pages=20),
}

for _plan in FRAGRANCE_FACET_PLANS.values():
    for _facet in as_facets(_plan.categories):
        if _facet.label and _facet.category:
            FACET_CATEGORY.setdefault(_facet.label, _facet.category)


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
    #: product URL -> gender implied by the department it was found in.
    gender_hints: dict = field(default_factory=dict)
    #: product URL -> the shop's own name for that facet, verbatim.
    merchant_paths: dict = field(default_factory=dict)
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


def sweep_plan(merchant_slug: str, adapter: str,
               vertical: str = "footwear"
               ) -> SitemapPlan | PaginatedPlan | SampledPlan | None:
    """The plan a *sweep* walks: the one that decides what gets fetched.

    Not the same thing as :func:`facet_plan`, and the difference is worth
    keeping straight. A footwear sweep walks the coarse `Grupa=01`-style
    branches, because its job is to find every product once; the fine
    gender-by-category facets exist to *label* products the sweep already
    brought in, and walking them for a sweep would fetch the same pages
    several times over.

    Apparel has no such split: its facet plans already cover the whole
    vertical exactly once, so a sweep and a walk read the same list -- and
    the sweep gets the category and gender hints for free, which is why
    apparel products arrive labelled where footwear ones needed a second
    pass.
    """
    if vertical == "apparel":
        return APPAREL_FACET_PLANS.get(merchant_slug)
    if vertical == "accessory":
        return ACCESSORY_FACET_PLANS.get(merchant_slug)
    if vertical == "fragrance":
        return FRAGRANCE_FACET_PLANS.get(merchant_slug)
    if vertical != "footwear":
        return None
    # The shop's own plan first: on a white-label platform the adapter says
    # how to read a page, not what this installation calls its departments.
    return MERCHANT_PLANS.get(merchant_slug) or DISCOVERY_PLANS.get(adapter)


def facet_plan(merchant_slug: str,
               vertical: str = "footwear") -> PaginatedPlan | None:
    """The plan a *labelling walk* reads. See :func:`sweep_plan`."""
    if vertical == "apparel":
        return APPAREL_FACET_PLANS.get(merchant_slug)
    if vertical == "accessory":
        return ACCESSORY_FACET_PLANS.get(merchant_slug)
    if vertical == "fragrance":
        return FRAGRANCE_FACET_PLANS.get(merchant_slug)
    if vertical != "footwear":
        return None
    return FACET_PLANS.get(merchant_slug)


def discover(fetcher, merchant_slug: str, adapter: str, base_url: str, *,
             priority: Priority = Priority.COLD,
             max_requests: int = 400,
             limit: int | None = None,
             plan: SitemapPlan | PaginatedPlan | SampledPlan | None = None,
             vertical: str = "footwear",
             ) -> DiscoveryReport:
    """Enumerate product URLs for one merchant.

    Uses the fetcher, so every request still passes through the rate limiter,
    the robots check and the circuit breaker. Discovery runs at ``COLD`` by
    default: it is the most preemptible work in the system.
    """
    report = DiscoveryReport(merchant_slug=merchant_slug, adapter=adapter)
    # An explicit plan wins -- that is how the facet walk reuses this driver
    # without becoming a sweep. Otherwise the sweep plan for the vertical.
    plan = plan or sweep_plan(merchant_slug, adapter, vertical)
    if plan is None:
        report.notes.append(
            f"no {vertical} discovery plan for {merchant_slug!r} "
            f"(adapter {adapter!r})")
        return report
    report.strategy = plan.strategy

    pattern = PRODUCT_URL_PATTERNS.get(adapter)
    if pattern is None:
        report.notes.append(f"no product URL pattern for adapter {adapter!r}")
        return report

    found: dict[str, None] = {}
    hints: dict[str, str] = {}
    # A *set* per URL, not a first-wins value. The men's and women's facets
    # on the Sport Vision shops both contain every unisex article, and that
    # membership of both is the only evidence any of them publishes for
    # unisex. Keeping the first one measured 19 unisex products in a
    # catalogue where buzz alone has 279.
    genders: dict[str, set] = {}
    labels: dict[str, str] = {}

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

    def note(url: str, facet: Facet | None) -> None:
        if facet is None:
            return
        # Category is first-wins: a product in two category facets of one
        # shop is rare and either reading is defensible. Gender accumulates,
        # because overlapping departments are not an accident to be resolved
        # away -- they are the finding.
        if facet.category:
            hints.setdefault(url, facet.category)
        if facet.gender:
            genders.setdefault(url, set()).add(facet.gender)
        if facet.label or facet.path:
            labels.setdefault(url, facet.label or facet.path)

    def harvest(text: str, facet: Facet | None = None) -> int:
        before = len(found)
        canonical = adapter in CANONICALISE_MATCH
        for url in extract_links(text, pattern, base_url, canonical):
            found.setdefault(url, None)
            note(url, facet)
        # Sitemaps carry <loc> rather than href.
        for loc, _lastmod in parse_sitemap_urls(text):
            match = pattern.search(loc)
            if match:
                link = urljoin(base_url, match.group(0)) if canonical else loc
                found.setdefault(link, None)
                note(link, facet)
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
        for facet in as_facets(plan.categories):
            category = facet.path
            if done():
                break
            first = fetch(urljoin(base_url, category))
            if not first:
                continue
            harvest(first, facet)
            if plan.walk_until_empty:
                page = 2
                while page <= plan.max_pages and not done():
                    body = fetch(urljoin(base_url, f"{category}"
                                         f"{plan.page_suffix.format(page=page)}"))
                    if body is None:
                        break
                    # Emptiness is the only honest stop signal here. "No new
                    # products" is not: facets overlap, so a page of entirely
                    # familiar products is still a page, and stopping on it
                    # would truncate the facet at the first repeat.
                    if not extract_links(body, pattern, base_url):
                        break
                    harvest(body, facet)
                    page += 1
                report.notes.append(f"{category}: {page - 1} pages (walked)")
                continue
            # The advertised total when there is one, the paginator's own last
            # link when there is not. A category that answers neither is one
            # page, which is also what a one-page category looks like.
            total = parse_total_pages(first) or parse_last_page_link(first) or 1
            total = min(total, plan.max_pages)
            report.notes.append(f"{category}: {total} pages")
            for page in range(2, total + 1):
                if done():
                    break
                body = fetch(urljoin(base_url, f"{category}"
                                     f"{plan.page_suffix.format(page=page)}"))
                if body is None:
                    break
                harvest(body, facet)

    # --- sampled facets ---------------------------------------------------
    else:
        for facet in as_facets(plan.facets):
            if done():
                break
            url = urljoin(base_url, facet.path)
            empty_rounds = 0
            for attempt in range(plan.max_requests):
                body = fetch(url)
                if body is None:
                    break
                new = harvest(body, facet)
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
                report.notes.append(f"facet not saturated: {facet.path}")

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
    report.gender_hints = {
        u: resolve_departments(genders[u]) for u in report.product_urls
        if u in genders and resolve_departments(genders[u])}
    report.merchant_paths = {u: labels[u] for u in report.product_urls
                             if u in labels}
    return report


def store_api_url(product_url: str) -> str:
    """The Store API record for a product whose public page is this URL.

    e-elixir is discovered through its API and its products are *addressed*
    by their shop page -- that is what `permalink` states, and what a
    shopper has to be sent to. The two are not interchangeable: fetching
    the shop page returns HTML to an adapter that parses JSON.

    So the public URL is what the catalogue stores, and this is what the
    crawler asks for. The adapter closes the loop by reading `permalink`
    back out of the payload, so the offer still carries the clickable
    address rather than the endpoint we happened to use.
    """
    slug = urlsplit(product_url).path.rstrip("/").rsplit("/", 1)[-1]
    return urljoin(product_url, f"/wp-json/wc/store/v1/products?slug={slug}")


#: Adapters whose product jobs address an endpoint rather than the page.
PRODUCT_FETCH_REWRITES = {"woocommerce": store_api_url}


def product_jobs(report: DiscoveryReport, kind: str = "catalog_parse",
                 priority: Priority = Priority.COLD) -> list[FetchJob]:
    """Turn discovered URLs into fetch jobs for the worker."""
    rewrite = PRODUCT_FETCH_REWRITES.get(report.adapter)
    return [FetchJob(merchant_slug=report.merchant_slug,
                     url=rewrite(url) if rewrite else url, kind=kind,
                     priority=priority,
                     category_hint=report.category_hints.get(url),
                     gender_hint=report.gender_hints.get(url))
            for url in report.product_urls]
