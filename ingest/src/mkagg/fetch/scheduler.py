"""What to fetch, how often, and what to do with the answer.

Three ideas, in the order they matter:

**Refresh on predicted change, not on a clock.** A shoe whose price has not
moved in 90 days does not need checking every 15 minutes; one that moved four
times this week does. Each probe adjusts that variant's own TTL -- back off
when nothing changed, lean in when something did. This is the single biggest
efficiency lever in the fetcher, and it is four lines of arithmetic.

**Tier by demand, measured from our own traffic.** Attention is Zipf
distributed: a small hot set will carry most page views. That set gets minutes
of latency, everything else gets hours or a day.

**Write history only on change.** 50k products x ~3 merchants x ~8 sizes
probed hourly is ~100M rows a year if written blindly. Writing only when a
value actually moves (~2% of observations) makes it ~2M, which Postgres does
not notice. :func:`record_observation` is where that rule lives, and a 304
counts as a confirmed no-change.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..adapters import aspnet_mk
from ..adapters.magento import size_probe_query
from .queue import FetchJob
from .ratelimit import Priority

# -----------------------------------------------------------------------------
# Tiers
# -----------------------------------------------------------------------------

#: (min_ttl, max_ttl, priority) per freshness tier, in seconds.
TIERS: dict[str, tuple[int, int, Priority]] = {
    "S": (900, 1_800, Priority.HOT),       # hot:  15-30 min
    "A": (7_200, 14_400, Priority.WARM),   # warm: 2-4 h
    "B": (43_200, 86_400, Priority.COLD),  # cold: 12-24 h
}

#: Target hot-set size. Deliberately small: the budget is better spent
#: re-checking the few offers users actually look at.
HOT_SET_SIZE = 2_000
WARM_SET_SIZE = 8_000

BACKOFF_FACTOR = 1.5   # unchanged -> wait longer
LEAN_IN_DIVISOR = 3.0  # changed   -> check sooner


def next_ttl(current_ttl: int, changed: bool, tier: str = "B") -> int:
    """Adapt one variant's check interval from the outcome of a probe.

    Bounded by its tier so a single quiet week cannot push a hot product out
    to daily checks, and a volatile one cannot probe faster than its tier's
    politeness floor.
    """
    low, high, _ = TIERS.get(tier, TIERS["B"])
    if changed:
        return int(max(low, current_ttl / LEAN_IN_DIVISOR))
    return int(min(high, max(low, current_ttl * BACKOFF_FACTOR)))


# -----------------------------------------------------------------------------
# Demand tiering
# -----------------------------------------------------------------------------

# Outbound clicks are the demand signal we actually record today. Page views
# would be the better one -- they are ~10x more numerous and lead clicks -- so
# a product_view table is the obvious next addition; the weights below leave
# room for it. Volatility is the other half: price movement predicts price
# movement, so a variant that changed recently earns a faster cadence even
# without traffic.
ASSIGN_TIERS_SQL = """
WITH demand AS (
    SELECT ov.id AS variant_id,
           count(ce.id) FILTER (
               WHERE ce.occurred_at > now() - interval '7 days') AS clicks_7d
      FROM offer_variant ov
      JOIN merchant_offer mo ON mo.id = ov.offer_id
      LEFT JOIN click_event ce ON ce.offer_variant_id = ov.id
     WHERE mo.status = 'active'
     GROUP BY ov.id
),
volatility AS (
    SELECT offer_variant_id AS variant_id, count(*) AS changes_30d
      FROM price_point
     WHERE observed_at > now() - interval '30 days'
     GROUP BY offer_variant_id
),
top_offers AS (
    -- The cheapest offer per product is the one the listing page advertises,
    -- so being wrong about it is the most expensive kind of staleness.
    SELECT DISTINCT ON (mo.product_id) ov.id AS variant_id
      FROM offer_variant ov
      JOIN merchant_offer mo ON mo.id = ov.offer_id
     WHERE mo.status = 'active' AND mo.product_id IS NOT NULL
     ORDER BY mo.product_id, ov.price_minor
),
scored AS (
    SELECT d.variant_id,
             coalesce(d.clicks_7d, 0) * 10.0
           + coalesce(v.changes_30d, 0) * 2.0
           + CASE WHEN t.variant_id IS NOT NULL THEN 25.0 ELSE 0 END AS score
      FROM demand d
      LEFT JOIN volatility v ON v.variant_id = d.variant_id
      LEFT JOIN top_offers t ON t.variant_id = d.variant_id
),
ranked AS (
    SELECT variant_id, score,
           row_number() OVER (ORDER BY score DESC, variant_id) AS rn
      FROM scored
)
UPDATE offer_variant ov
   SET freshness_tier = CASE
           WHEN r.score <= 0 THEN 'B'
           WHEN r.rn <= %(hot)s THEN 'S'
           WHEN r.rn <= %(warm)s THEN 'A'
           ELSE 'B' END,
       check_ttl_seconds = least(
           ov.check_ttl_seconds,
           CASE WHEN r.score <= 0 THEN 86400
                WHEN r.rn <= %(hot)s THEN 1800
                WHEN r.rn <= %(warm)s THEN 14400
                ELSE 86400 END)
  FROM ranked r
 WHERE r.variant_id = ov.id
"""


def assign_tiers(conn, hot: int = HOT_SET_SIZE,
                 warm: int = WARM_SET_SIZE) -> int:
    """Re-tier every active variant. Cheap enough to run hourly."""
    with conn.cursor() as cur:
        cur.execute(ASSIGN_TIERS_SQL, {"hot": hot, "warm": warm})
        return cur.rowcount


# -----------------------------------------------------------------------------
# Due work
# -----------------------------------------------------------------------------

DUE_SQL = """
SELECT ov.id, ov.freshness_tier, ov.price_minor, ov.size_label,
       mo.id AS offer_id, mo.merchant_sku, mo.product_url,
       m.slug AS merchant_slug, m.adapter, m.base_url, m.publishes_stock,
       m.api_requires_permission
  FROM offer_variant ov
  JOIN merchant_offer mo ON mo.id = ov.offer_id
  JOIN merchant m        ON m.id = mo.merchant_id
 WHERE mo.status = 'active'
   AND m.is_active
   AND ov.last_checked_at < now() - make_interval(secs => ov.check_ttl_seconds)
 ORDER BY ov.freshness_tier, ov.last_checked_at
 LIMIT %(limit)s
"""


@dataclass(slots=True)
class DueVariant:
    variant_id: int
    tier: str
    price_minor: int
    size_label: str
    offer_id: int
    merchant_sku: str
    product_url: str
    merchant_slug: str
    adapter: str
    base_url: str
    publishes_stock: bool
    #: True when this merchant's structured endpoint is forbidden by its
    #: robots.txt (dsport /graphql, megasport /wp-json/). The API adapters stay
    #: in the codebase and stay correct -- they become usable the moment
    #: permission or a feed arrives -- but the scheduler must not queue them.
    api_requires_permission: bool = False


def due_variants(conn, limit: int = 500) -> list[DueVariant]:
    with conn.cursor() as cur:
        cur.execute(DUE_SQL, {"limit": limit})
        return [DueVariant(*row) for row in cur.fetchall()]


# -----------------------------------------------------------------------------
# Building a stock probe per platform
# -----------------------------------------------------------------------------
# This is where the catalog_parse / stock_probe split pays off. Three of the
# four adapters have a small price-and-availability endpoint; one does not and
# has to re-fetch the product page.

def _job_sportvision(due: DueVariant, priority: Priority) -> FetchJob:
    # No price-only endpoint on this platform: the product page is the probe.
    return FetchJob(merchant_slug=due.merchant_slug, url=due.product_url,
                    kind="stock_probe", priority=priority,
                    offer_id=due.offer_id, offer_variant_id=due.variant_id)


def _job_magento(due: DueVariant, priority: Priority) -> FetchJob:
    import json

    payload = json.dumps(size_probe_query([due.merchant_sku])).encode()
    return FetchJob(
        merchant_slug=due.merchant_slug,
        url=f"{due.base_url.rstrip('/')}/graphql",
        kind="stock_probe", priority=priority, method="POST", body=payload,
        headers={"Content-Type": "application/json"},
        offer_id=due.offer_id, offer_variant_id=due.variant_id)


def _job_woocommerce(due: DueVariant, priority: Priority) -> FetchJob:
    url = (f"{due.base_url.rstrip('/')}/wp-json/wc/store/products"
           f"?type=variation&parent={due.merchant_sku}&per_page=100")
    return FetchJob(merchant_slug=due.merchant_slug, url=url,
                    kind="stock_probe", priority=priority,
                    offer_id=due.offer_id, offer_variant_id=due.variant_id)


def _job_aspnet_mk(due: DueVariant, priority: Priority) -> FetchJob:
    # POST only: a GET on this endpoint returns 404.
    url, body, headers = aspnet_mk.sizes_request(due.base_url, due.merchant_sku)
    return FetchJob(merchant_slug=due.merchant_slug, url=url,
                    kind="stock_probe", priority=priority, method="POST",
                    body=body, headers=headers,
                    offer_id=due.offer_id, offer_variant_id=due.variant_id)


def _job_product_page(due: DueVariant, priority: Priority) -> FetchJob:
    """The robots-permitted route for dsport and megasport.

    Their structured endpoints are forbidden, but their product pages are not,
    and both carry the full size matrix inline -- so this costs one request
    per offer rather than per size.
    """
    return FetchJob(merchant_slug=due.merchant_slug, url=due.product_url,
                    kind="stock_probe", priority=priority,
                    offer_id=due.offer_id, offer_variant_id=due.variant_id)


JOB_BUILDERS = {
    "sportvision": _job_sportvision,
    "magento_html": _job_product_page,
    "woocommerce_html": _job_product_page,
    "magento": _job_magento,
    "woocommerce": _job_woocommerce,
    "aspnet_mk": _job_aspnet_mk,
}


#: Adapters whose stock probe uses a structured endpoint rather than a page
#: the site permits. For these, ``api_requires_permission`` is a hard block.
API_ROUTE_ADAPTERS = frozenset({"magento", "woocommerce"})


class RobotsBlocked(LookupError):
    """The only probe route for this merchant is forbidden by its robots.txt."""


def build_stock_probe(due: DueVariant,
                      priority: Priority | None = None) -> FetchJob:
    builder = JOB_BUILDERS.get(due.adapter)
    if builder is None:
        raise LookupError(f"no job builder for adapter {due.adapter!r}")
    if due.api_requires_permission and due.adapter in API_ROUTE_ADAPTERS:
        raise RobotsBlocked(
            f"{due.merchant_slug}: the {due.adapter} probe endpoint is "
            "disallowed by robots.txt; use the permitted HTML route or obtain "
            "permission (see merchant.robots_notes)")
    if priority is None:
        priority = TIERS.get(due.tier, TIERS["B"])[2]
    return builder(due, priority)


@dataclass(slots=True)
class EnqueueReport:
    pushed: int = 0
    deduped: int = 0
    blocked: int = 0
    blocked_merchants: frozenset = frozenset()

    def __int__(self) -> int:
        return self.pushed


def enqueue_due(conn, queue, limit: int = 500) -> EnqueueReport:
    """Fill the queue with due probes.

    Deduplication matters here: several sizes of one offer resolve to the same
    probe URL, and one request answers all of them, so the queue collapses
    them. Robots-blocked merchants are counted rather than silently dropped --
    a merchant quietly producing no probes is exactly the kind of thing that
    should show up on a dashboard, not be discovered months later.
    """
    report = EnqueueReport()
    blocked: set[str] = set()
    for due in due_variants(conn, limit):
        try:
            job = build_stock_probe(due)
        except RobotsBlocked:
            report.blocked += 1
            blocked.add(due.merchant_slug)
            continue
        if queue.push(job):
            report.pushed += 1
        else:
            report.deduped += 1
    report.blocked_merchants = frozenset(blocked)
    return report


# -----------------------------------------------------------------------------
# Recording an observation
# -----------------------------------------------------------------------------

def record_observation(conn, variant_id: int, *, price_minor: int | None,
                       in_stock: bool | None, stock_qty: int | None = None,
                       unchanged: bool = False) -> bool:
    """Persist one probe outcome. Returns True when something changed.

    ``unchanged=True`` is the 304 path: the resource is byte-identical, so no
    parse happened and no values are supplied, but the observation is still
    real and still backs the TTL off.

    A ``price_point`` row is written only when a value actually moved -- that
    is the rule that keeps the history table small enough to be boring.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT price_minor, in_stock, stock_qty, check_ttl_seconds,
                      freshness_tier, consecutive_unchanged
                 FROM offer_variant WHERE id = %s FOR UPDATE""",
            (variant_id,))
        row = cur.fetchone()
        if row is None:
            return False
        old_price, old_stock, old_qty, ttl, tier, unchanged_count = row

        if unchanged:
            changed = False
            price_minor, in_stock, stock_qty = old_price, old_stock, old_qty
        else:
            changed = (price_minor != old_price
                       or in_stock != old_stock
                       or stock_qty != old_qty)

        cur.execute(
            """UPDATE offer_variant
                  SET price_minor           = %(price)s,
                      in_stock              = %(in_stock)s,
                      stock_qty             = %(qty)s,
                      last_checked_at       = now(),
                      last_changed_at       = CASE WHEN %(changed)s
                                                   THEN now()
                                                   ELSE last_changed_at END,
                      check_ttl_seconds     = %(ttl)s,
                      consecutive_unchanged = CASE WHEN %(changed)s
                                                   THEN 0
                                                   ELSE least(%(prev)s + 1, 32767)
                                              END
                WHERE id = %(id)s""",
            {"price": price_minor, "in_stock": in_stock, "qty": stock_qty,
             "changed": changed, "ttl": next_ttl(ttl, changed, tier),
             "prev": unchanged_count, "id": variant_id})

        if changed:
            cur.execute(
                """INSERT INTO price_point (offer_variant_id, observed_at,
                                            price_minor, in_stock, stock_qty)
                        VALUES (%s, now(), %s, %s, %s)""",
                (variant_id, price_minor, in_stock, stock_qty))
    return changed


def mark_checked(conn, variant_ids: list[int]) -> None:
    """Record that a probe was attempted but produced no usable answer.

    Pushes ``last_checked_at`` forward so one unreachable merchant cannot
    monopolise the queue, but deliberately leaves the stored values and the
    TTL alone -- a failure is not evidence about the price.
    """
    if not variant_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE offer_variant SET last_checked_at = now() WHERE id = ANY(%s)",
            (variant_ids,))
