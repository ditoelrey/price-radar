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
from urllib.parse import urljoin

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


def discover(fetcher, merchant_slug: str, adapter: str, base_url: str, *,
             priority: Priority = Priority.COLD,
             max_requests: int = 400,
             limit: int | None = None,
             plan: SitemapPlan | PaginatedPlan | SampledPlan | None = None,
             ) -> DiscoveryReport:
    """Enumerate product URLs for one merchant.

    Uses the fetcher, so every request still passes through the rate limiter,
    the robots check and the circuit breaker. Discovery runs at ``COLD`` by
    default: it is the most preemptible work in the system.
    """
    report = DiscoveryReport(merchant_slug=merchant_slug, adapter=adapter)
    # An explicit plan wins -- that is how the facet walk reuses this driver
    # without becoming a sweep. Otherwise the shop's own plan, because on a
    # white-label platform the adapter says how to read a page, not what this
    # installation calls its departments.
    plan = (plan or MERCHANT_PLANS.get(merchant_slug)
            or DISCOVERY_PLANS.get(adapter))
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
        for url in extract_links(text, pattern, base_url):
            found.setdefault(url, None)
            note(url, facet)
        # Sitemaps carry <loc> rather than href.
        for loc, _lastmod in parse_sitemap_urls(text):
            if pattern.search(loc):
                found.setdefault(loc, None)
                note(loc, facet)
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


def product_jobs(report: DiscoveryReport, kind: str = "catalog_parse",
                 priority: Priority = Priority.COLD) -> list[FetchJob]:
    """Turn discovered URLs into fetch jobs for the worker."""
    return [FetchJob(merchant_slug=report.merchant_slug, url=url, kind=kind,
                     priority=priority,
                     category_hint=report.category_hints.get(url),
                     gender_hint=report.gender_hints.get(url))
            for url in report.product_urls]
