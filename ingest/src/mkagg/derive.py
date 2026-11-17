"""Deriving a product's category and gender from the offers that sell it.

The defect this replaces: ``create_product`` set ``category_id`` once, from
``classify(title) or hint``, and nothing ever revised it. So a product created
before its shop's footwear facet existed stayed uncategorised for ever, and
re-sweeping could not repair it -- sportm's uncategorised count moved 221 to
223 across a full re-sweep of 2,069 listings, because only the 1,348 *new*
products were ever classified.

Deriving instead of stamping also answers a question stamping could not. A
canonical product is shared: 1,935 of them carry two or more shops' offers,
42 carry four. Each shop has its own opinion about what the shoe is and who it
is for, and a single stamped value is whichever shop we happened to meet
first -- so re-running the sweeps in a different order would give a different
catalogue. These functions read all the evidence at once and resolve it by
rule, which gives the same answer whatever the discovery order.

Precedence, for both fields:

1. **The facet** -- the department the shop itself filed the product under.
   Strong. Recorded per offer by the ``facets`` command.
2. **The title** -- a keyword in the product name. Weak: four of the six
   shops put no category word in their titles at all, and gender words reach
   4.9 percent of men's titles.
3. **Nothing.** NULL, and ``category_source``/``gender_source`` NULL with it.

A value is never *downgraded*: a facet-derived category is not replaced by a
title guess, even when a later walk missed the facet that produced it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .discover import FACET_CATEGORY
from .taxonomy import (FOOTWEAR_SLUGS, classify, classify_gender,
                       resolve_departments)

#: What a tie resolves to when every candidate is a footwear leaf. The parent
#: row means "a shoe, kind unspecified", which is exactly true of a product
#: two shops file under different leaves.
UNSPECIFIED_FOOTWEAR = "footwear"


@dataclass(frozen=True)
class OfferEvidence:
    """What one shop's offer says about the product it points at."""
    merchant_slug: str
    merchant_category_path: str | None = None
    merchant_gender: str | None = None
    raw_title: str | None = None
    product_url: str | None = None

    @property
    def facet_category(self) -> str | None:
        """The canonical category this shop's own facet implies, if any."""
        if not self.merchant_category_path:
            return None
        return FACET_CATEGORY.get(self.merchant_category_path)

    @property
    def title_category(self) -> str | None:
        return classify(self.raw_title, url=self.product_url)

    @property
    def title_gender(self) -> str | None:
        return classify_gender(self.raw_title, url=self.product_url)


def _majority(values: list[str]) -> str | None:
    """The single most common value, or ``None`` when two or more tie."""
    if not values:
        return None
    counts = Counter(values)
    top, n = counts.most_common(1)[0]
    if sum(1 for v in counts.values() if v == n) > 1:
        return None
    return top


def derive_category(offers: list[OfferEvidence]) -> tuple[str | None, str | None]:
    """Return ``(category_slug, source)`` for a product's offers.

    ::

        two shops' facets agree on cleats        -> ("cleats", "facet")
        one says sneakers, one says shoes_boots  -> ("footwear", "facet")
        no facet, two titles say slides          -> ("slides_sandals", "title")
        nothing says                             -> (None, None)

    A tie between footwear leaves resolves to the parent rather than to one
    of them: "we know it is a shoe and the shops disagree on which kind" is a
    true statement, and picking a side is not.
    """
    facets = [o.facet_category for o in offers if o.facet_category]
    if facets:
        winner = _majority(facets)
        if winner:
            return winner, "facet"
        # The facets tie. Before giving up on a leaf, ask the title: two
        # shops shelving a shoe differently does not make the shoe
        # unknowable, and 15 products in the live catalogue sat in the parent
        # bucket while their own titles said "Predator" or "Terrex". A tie is
        # the one place the weaker source gets to decide.
        from_title = _majority([o.title_category for o in offers
                                if o.title_category])
        if from_title in FOOTWEAR_SLUGS:
            return from_title, "title"
        # Nothing to break the tie with. The parent is honest only while
        # every candidate really is footwear.
        if all(f in FOOTWEAR_SLUGS for f in facets):
            return UNSPECIFIED_FOOTWEAR, "facet"
        return None, None

    titles = [o.title_category for o in offers if o.title_category]
    if titles:
        winner = _majority(titles)
        if winner:
            return winner, "title"
        if all(t in FOOTWEAR_SLUGS for t in titles):
            return UNSPECIFIED_FOOTWEAR, "title"
        # Shops disagree about whether this is even a shoe. That is a question
        # for a human, not something to average.
        return None, None

    return None, None


def derive_gender(offers: list[OfferEvidence]) -> tuple[str | None, str | None]:
    """Return ``(gender, source)`` for a product's offers.

    ::

        found only in men's departments          -> ("men", "facet")
        found in men's AND women's               -> ("unisex", "facet")
        found in a kids' and an adult department -> (None, None)
        no facet, title says "за деца"           -> ("kids", "title")

    The kids-plus-adult case is left unresolved deliberately. It is not a
    product that is both; it is either a shop mis-shelving it or two different
    articles merged into one product, and both are worth seeing rather than
    smoothing over.
    """
    facets = {o.merchant_gender for o in offers if o.merchant_gender}
    if facets:
        # The same collapse the facet walk applies within one shop, applied
        # again across shops. A single offer can already say "unisex" -- that
        # shop listed it in both of its adult departments -- and two shops
        # disagreeing men/women say the same thing between them.
        resolved = resolve_departments(facets)
        return (resolved, "facet") if resolved else (None, None)

    titles = [o.title_gender for o in offers if o.title_gender]
    if titles:
        winner = _majority(titles)
        if winner:
            return winner, "title"
    return None, None


# -----------------------------------------------------------------------------
# Running it over the catalogue
# -----------------------------------------------------------------------------

@dataclass
class DeriveReport:
    products: int = 0
    category_set: int = 0
    category_cleared: int = 0
    gender_set: int = 0
    gender_conflicts: int = 0
    unchanged: int = 0
    kept_facet: int = 0

    def summary(self) -> str:
        return (f"products={self.products} category_set={self.category_set} "
                f"gender_set={self.gender_set} "
                f"unchanged={self.unchanged} "
                f"kept_facet={self.kept_facet} "
                f"gender_conflicts={self.gender_conflicts}")


_LOAD_SQL = """
    SELECT p.id,
           c.slug AS current_category,
           p.category_source,
           p.gender::text AS current_gender,
           p.gender_source,
           m.slug,
           o.merchant_category_path,
           o.merchant_gender,
           o.raw_title,
           o.product_url
      FROM product p
      LEFT JOIN category c ON c.id = p.category_id
      JOIN merchant_offer o ON o.product_id = p.id
      JOIN merchant m ON m.id = o.merchant_id
     ORDER BY p.id
"""


def rederive(conn, *, dry_run: bool = False,
             limit: int | None = None) -> DeriveReport:
    """Recompute category and gender for every product, from its offers.

    Pure in the sense that matters: the answer depends only on the offers, so
    running it twice changes nothing the second time, and running it after a
    facet walk improves exactly the products the walk learned about.
    """
    report = DeriveReport()
    rows_by_product: dict[int, list] = {}
    state: dict[int, tuple] = {}

    with conn.cursor() as cur:
        cur.execute(_LOAD_SQL)
        for (pid, cur_cat, cat_src, cur_gender, gender_src, merchant,
             path, gender, title, url) in cur.fetchall():
            state.setdefault(pid, (cur_cat, cat_src, cur_gender, gender_src))
            rows_by_product.setdefault(pid, []).append(OfferEvidence(
                merchant_slug=merchant, merchant_category_path=path,
                merchant_gender=gender, raw_title=title, product_url=url))

    updates: list[tuple] = []
    for pid, offers in rows_by_product.items():
        if limit is not None and report.products >= limit:
            break
        report.products += 1
        cur_cat, cat_src, cur_gender, gender_src = state[pid]

        category, category_source = derive_category(offers)
        gender, gender_source = derive_gender(offers)

        # Never downgrade -- but the test is whether this pass could *see*
        # any facet evidence, not which source happened to decide. A walk
        # that did not cover this product must not cost it what an earlier
        # one found; a pass that did see the facets and used the title to
        # break a tie between them has not lost anything, and blocking that
        # was keeping 16 products in the parent bucket whose own titles said
        # "Terrex".
        if cat_src == "facet" and not any(o.facet_category for o in offers):
            category, category_source = cur_cat, cat_src
            report.kept_facet += 1
        if gender_src == "facet" and not any(o.merchant_gender
                                             for o in offers):
            gender, gender_source = cur_gender, gender_src

        if (category, category_source, gender, gender_source) == \
                (cur_cat, cat_src, cur_gender, gender_src):
            report.unchanged += 1
            continue

        if category != cur_cat:
            if category is None:
                report.category_cleared += 1
            else:
                report.category_set += 1
        if gender != cur_gender and gender is not None:
            report.gender_set += 1
        if gender is None and any(o.merchant_gender for o in offers):
            report.gender_conflicts += 1

        updates.append((category, category_source, gender, gender_source, pid))

    if updates and not dry_run:
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE product
                      SET category_id = (SELECT id FROM category
                                          WHERE slug = %s),
                          category_source = %s,
                          gender = %s::gender_t,
                          gender_source = %s,
                          updated_at = now()
                    WHERE id = %s""", updates)
        conn.commit()
    return report


# -----------------------------------------------------------------------------
# The facet walk
# -----------------------------------------------------------------------------

@dataclass
class FacetReport:
    merchant_slug: str
    facets: int = 0
    requests: int = 0
    urls: int = 0
    matched: int = 0
    unmatched: int = 0
    notes: list = None

    def summary(self) -> str:
        return (f"{self.merchant_slug}: {self.facets} facets, "
                f"{self.requests} requests, {self.urls} urls, "
                f"{self.matched} offers labelled, {self.unmatched} urls "
                f"matched no offer")


def walk_facets(conn, fetcher, merchant_slug: str, adapter: str,
                base_url: str, *, max_requests: int = 400,
                limit: int | None = None,
                vertical: str = "footwear") -> FacetReport:
    """Record which department each offer was found in, without fetching it.

    This is the cheap half of the whole exercise. The facet is carried by the
    *listing* page; the product page adds nothing to it. Gender x category
    partitions a shop's catalogue, so the page count is set by the product
    count and does not change -- the overhead over the sweep's own discovery
    is one partial last page per facet. Against re-sweeping six shops to
    recover the same information: roughly 600 listing requests instead of
    10,700 product fetches.

    Nothing here writes a product. It writes what the shop said, next to the
    offer that said it, and leaves the conclusions to :func:`rederive`.
    """
    from .discover import as_facets, discover, facet_plan

    report = FacetReport(merchant_slug=merchant_slug, notes=[])
    plan = facet_plan(merchant_slug, vertical)
    if plan is None:
        report.notes.append(
            f"no {vertical} facet plan for {merchant_slug!r}")
        return report
    report.facets = len(as_facets(plan.categories))

    walk = discover(fetcher, merchant_slug, adapter, base_url, plan=plan,
                    max_requests=max_requests, limit=limit)
    report.requests = walk.requests
    report.urls = walk.count
    report.notes.extend(walk.notes[:6])

    # Every URL this walk actually saw in a facet, including the ones whose
    # departments contradicted each other. Those get NULL written over
    # whatever they said before -- a product the shop lists in both a kids'
    # and an adult department has no honest gender, and leaving the previous
    # walk's arbitrary answer in place would be worse than saying so.
    rows = [(walk.merchant_paths.get(url), walk.gender_hints.get(url), url)
            for url in walk.product_urls
            if url in walk.merchant_paths or url in walk.gender_hints]
    if not rows:
        return report

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM merchant WHERE slug = %s",
                    (merchant_slug,))
        merchant_id = cur.fetchone()[0]
        for path, gender, url in rows:
            # A later walk overwrites what an earlier one said: the shop's
            # current shelf is the answer, not the first one we ever saw.
            # Gender is assigned outright rather than COALESCEd, so an
            # unresolved department really does clear; the category keeps its
            # previous value when this walk found no label for it, since a
            # product can leave one category facet without leaving the shop.
            # Neither can clear a label for a product that has left every
            # facet -- that row keeps where we last saw it, which is a weaker
            # claim than it looks.
            cur.execute(
                """UPDATE merchant_offer
                      SET merchant_category_path = COALESCE(%s,
                              merchant_category_path),
                          merchant_gender = %s
                    WHERE merchant_id = %s AND product_url = %s""",
                (path, gender, merchant_id, url))
            if cur.rowcount:
                report.matched += cur.rowcount
            else:
                report.unmatched += 1
    conn.commit()
    return report
