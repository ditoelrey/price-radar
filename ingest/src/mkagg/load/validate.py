"""Run validation: the gate between a parser and the public site.

The single rule this module exists to enforce:

    An ingest run that fails its checks is not promoted.

A parser rarely breaks loudly. It starts returning ``None`` for a field, or
half the sizes, or a tenth of the catalogue, and everything downstream keeps
working on the reduced data. Nothing raises. So the only reliable detector is
*shape*: compare this run against what this merchant's runs normally look like,
and refuse the ones that don't fit.

The comparison is always against the merchant's own seven-day median for the
same kind of run -- never a global constant. 600 sneakers is normal for
megasport and would be alarming for a store with 60.

Rejecting a good run costs a few hours of freshness. Promoting a bad one puts
a confidently wrong price in front of a shopper, which is the one failure the
whole product cannot survive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"   # promote, but flag it
    REJECTED = "rejected"   # do not promote


@dataclass(frozen=True)
class Thresholds:
    """Tuned to be strict about fields and tolerant about catalogue size.

    A missing price is always a bug. A catalogue that shrank 30% might be a
    bug or might be end-of-season, so that case is rejected and looked at by a
    human rather than guessed at.
    """

    #: Absolute floors, applied to every run including the first.
    min_price_fill: float = 0.95
    min_offers: int = 1

    #: Relative to the merchant's 7-day median.
    sku_fill_ratio: float = 0.90      # reject below 90% of normal
    price_fill_ratio: float = 0.98
    size_fill_ratio: float = 0.85
    offers_delta: float = 0.20        # reject outside +/-20% of normal

    #: HTTP error share: above `degraded` flag it, above `reject` refuse it.
    degraded_error_rate: float = 0.02
    reject_error_rate: float = 0.20

    #: Runs needed before the relative checks switch on.
    min_baseline_runs: int = 3


@dataclass
class RunMetrics:
    """What a run produced. Computed from the staged rows, not from the parser."""

    offers_seen: int = 0
    variants_seen: int = 0
    http_errors: int = 0
    requests: int = 0

    offers_with_mpn: int = 0
    offers_with_price: int = 0
    offers_with_size: int = 0
    #: Offers the shop publishes no price for because they are sold out.
    #: Held apart so they do not count against the fill rates: they are
    #: complete offers, not failures to extract anything.
    offers_sold_out_unpriced: int = 0

    #: field -> {tier: count}
    extractor_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    quality_issues: dict[str, int] = field(default_factory=dict)

    @property
    def sku_fill_rate(self) -> float | None:
        return self.offers_with_mpn / self.offers_seen if self.offers_seen else None

    @property
    def priceable_offers(self) -> int:
        """Offers that ought to carry a price.

        A sold-out offer whose shop publishes no price is not one of them.
        Counting it as a miss is what makes the denominator the right place to
        fix this: the alternative, counting it as a hit, would put a number in
        the metric that is not in the data. Before this, 32 sold-out megasport
        products were enough to pull a 500-offer run's price fill to 94% and
        put it under the 95% floor -- rejecting 468 good offers over 32 that
        were never going to have a price.
        """
        return self.offers_seen - self.offers_sold_out_unpriced

    @property
    def price_fill_rate(self) -> float | None:
        """None when nothing in the run could have had a price."""
        return (self.offers_with_price / self.priceable_offers
                if self.priceable_offers else None)

    @property
    def size_fill_rate(self) -> float | None:
        return (self.offers_with_size / self.priceable_offers
                if self.priceable_offers else None)

    @property
    def error_rate(self) -> float:
        return self.http_errors / self.requests if self.requests else 0.0


@dataclass
class Baseline:
    """The merchant's own recent normal, from ``ingest_run_baseline``."""

    runs: int = 0
    median_offers: float | None = None
    median_sku_fill: float | None = None
    median_price_fill: float | None = None
    median_size_fill: float | None = None

    @property
    def is_established(self) -> bool:
        return self.runs > 0


@dataclass
class Check:
    name: str
    passed: bool
    value: float | None
    limit: float | None
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "value": self.value,
                "limit": self.limit, "note": self.note}


@dataclass
class ValidationResult:
    decision: Decision
    checks: list[Check]
    reason: str | None = None

    @property
    def promote(self) -> bool:
        return self.decision in (Decision.OK, Decision.DEGRADED)

    def as_dict(self) -> dict:
        return {"decision": self.decision.value, "reason": self.reason,
                "checks": [c.as_dict() for c in self.checks]}


def validate_run(metrics: RunMetrics, baseline: Baseline,
                 thresholds: Thresholds | None = None) -> ValidationResult:
    """Decide whether a staged run may be promoted."""
    t = thresholds or Thresholds()
    checks: list[Check] = []

    def add(name, passed, value, limit, note="") -> bool:
        checks.append(Check(name, passed, value, limit, note))
        return passed

    fatal: list[str] = []
    degraded: list[str] = []

    # -- absolute floors, always applied -----------------------------------

    if not add("offers_seen_min", metrics.offers_seen >= t.min_offers,
               metrics.offers_seen, t.min_offers,
               "a run that parsed nothing is a failure, not an empty catalogue"):
        fatal.append(f"parsed {metrics.offers_seen} offers")

    if metrics.price_fill_rate is None:
        # Every offer in the run is a sold-out one the shop prices nothing
        # for, so there is no fill rate to judge. `offers_seen_min` above
        # already caught the run that parsed nothing at all, which is the
        # failure this check would otherwise be standing in for.
        add("price_fill_min", True, None, t.min_price_fill,
            "no priceable offers in this run: every one is sold out")
    elif metrics.offers_seen:
        price_fill = metrics.price_fill_rate
        if not add("price_fill_min", price_fill >= t.min_price_fill,
                   round(price_fill, 4), t.min_price_fill,
                   "an offer without a price cannot be compared"):
            fatal.append(f"price fill {price_fill:.1%} below "
                         f"{t.min_price_fill:.0%} floor")

    if not add("error_rate_max", metrics.error_rate <= t.reject_error_rate,
               round(metrics.error_rate, 4), t.reject_error_rate):
        fatal.append(f"HTTP error rate {metrics.error_rate:.1%}")
    elif metrics.error_rate > t.degraded_error_rate:
        degraded.append(f"HTTP error rate {metrics.error_rate:.1%}")
        checks.append(Check("error_rate_degraded", False,
                            round(metrics.error_rate, 4), t.degraded_error_rate,
                            "elevated but tolerable"))

    # -- relative checks, once there is history to compare against ---------

    if not baseline.is_established:
        checks.append(Check("baseline", True, baseline.runs, t.min_baseline_runs,
                            "no history yet: relative checks skipped "
                            "(bootstrap run)"))
    else:
        provisional = baseline.runs < t.min_baseline_runs

        if baseline.median_offers:
            low = baseline.median_offers * (1 - t.offers_delta)
            high = baseline.median_offers * (1 + t.offers_delta)
            inside = low <= metrics.offers_seen <= high
            note = (f"7-day median {baseline.median_offers:.0f}, "
                    f"band {low:.0f}-{high:.0f}")
            if provisional:
                add("offers_delta", True, metrics.offers_seen, high,
                    note + " (provisional: too few runs to enforce)")
                if not inside:
                    degraded.append(
                        f"offers {metrics.offers_seen} outside provisional band")
            elif not add("offers_delta", inside, metrics.offers_seen, high, note):
                fatal.append(
                    f"offers {metrics.offers_seen} outside +/-"
                    f"{t.offers_delta:.0%} of median {baseline.median_offers:.0f}")

        for name, actual, median, ratio in (
            ("sku_fill", metrics.sku_fill_rate, baseline.median_sku_fill,
             t.sku_fill_ratio),
            ("price_fill", metrics.price_fill_rate, baseline.median_price_fill,
             t.price_fill_ratio),
            ("size_fill", metrics.size_fill_rate, baseline.median_size_fill,
             t.size_fill_ratio),
        ):
            if actual is None or not median:
                continue
            limit = median * ratio
            passed = actual >= limit
            note = f"7-day median {median:.1%}"
            if provisional:
                add(name, True, round(actual, 4), round(limit, 4),
                    note + " (provisional)")
                if not passed:
                    degraded.append(f"{name} {actual:.1%} below provisional floor")
            elif not add(name, passed, round(actual, 4), round(limit, 4), note):
                fatal.append(f"{name} {actual:.1%} below {limit:.1%} "
                             f"({ratio:.0%} of median)")

    if fatal:
        return ValidationResult(Decision.REJECTED, checks, reason="; ".join(fatal))
    if degraded:
        return ValidationResult(Decision.DEGRADED, checks,
                                reason="; ".join(degraded))
    return ValidationResult(Decision.OK, checks)


# -----------------------------------------------------------------------------
# Metrics from the staged rows
# -----------------------------------------------------------------------------

METRICS_SQL = """
SELECT count(*)                                                   AS offers_seen,
       count(*) FILTER (WHERE so.raw_mpn IS NOT NULL
                          AND so.raw_mpn <> '')                   AS with_mpn,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM stage_variant sv
                                       WHERE sv.stage_offer_id = so.id
                                         AND sv.price_minor > 0)) AS with_price,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM stage_variant sv
                                       WHERE sv.stage_offer_id = so.id
                                         AND sv.size_eu IS NOT NULL)) AS with_size,
       -- Sold out everywhere, with no price published anywhere: a complete
       -- offer, not a parse failure, and excluded from the fill denominators.
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM stage_variant sv
                                           WHERE sv.stage_offer_id = so.id
                                             AND (sv.price_minor IS NOT NULL
                                                  OR sv.in_stock IS NOT FALSE)))
                                                             AS sold_out,
       coalesce((SELECT count(*) FROM stage_variant sv
                   JOIN stage_offer so2 ON so2.id = sv.stage_offer_id
                  WHERE so2.ingest_run_id = %(run)s), 0)          AS variants_seen
  FROM stage_offer so
 WHERE so.ingest_run_id = %(run)s
"""

EXTRACTOR_SQL = """
SELECT kv.key AS field, kv.value #>> '{}' AS tier, count(*) AS n
  FROM stage_offer so, jsonb_each(so.extractors) AS kv
 WHERE so.ingest_run_id = %(run)s
 GROUP BY 1, 2
"""

ISSUES_SQL = """
SELECT issue, count(*) AS n
  FROM stage_offer so, unnest(so.quality_issues) AS issue
 WHERE so.ingest_run_id = %(run)s
 GROUP BY 1
"""

BASELINE_SQL = """
SELECT runs, median_offers, median_sku_fill, median_price_fill, median_size_fill
  FROM ingest_run_baseline
 WHERE merchant_id = %(merchant)s AND kind = %(kind)s
"""


def metrics_from_stage(conn, run_id: int, *, requests: int = 0,
                       http_errors: int = 0) -> RunMetrics:
    """Compute run metrics from what was actually staged.

    Deliberately read back out of the database rather than accumulated in
    Python: that way the numbers the gate judges are the rows that would be
    promoted, not a parallel tally that could drift from them.
    """
    with conn.cursor() as cur:
        cur.execute(METRICS_SQL, {"run": run_id})
        (offers_seen, with_mpn, with_price, with_size,
         sold_out, variants_seen) = cur.fetchone()

        metrics = RunMetrics(
            offers_seen=offers_seen, variants_seen=variants_seen,
            requests=requests or offers_seen, http_errors=http_errors,
            offers_with_mpn=with_mpn, offers_with_price=with_price,
            offers_with_size=with_size,
            offers_sold_out_unpriced=sold_out)

        cur.execute(EXTRACTOR_SQL, {"run": run_id})
        for field_name, tier, count in cur.fetchall():
            metrics.extractor_stats.setdefault(field_name, {})[tier or "none"] = count

        cur.execute(ISSUES_SQL, {"run": run_id})
        metrics.quality_issues = {issue: n for issue, n in cur.fetchall()}
    return metrics


def baseline_for(conn, merchant_id: int, kind: str) -> Baseline:
    with conn.cursor() as cur:
        cur.execute(BASELINE_SQL, {"merchant": merchant_id, "kind": kind})
        row = cur.fetchone()
    if row is None:
        return Baseline()
    runs, offers, sku, price, size = row
    return Baseline(runs=runs,
                    median_offers=float(offers) if offers is not None else None,
                    median_sku_fill=float(sku) if sku is not None else None,
                    median_price_fill=float(price) if price is not None else None,
                    median_size_fill=float(size) if size is not None else None)
