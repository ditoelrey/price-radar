"""Orchestration: stage, validate, then promote or reject -- atomically.

One entry point, :func:`ingest`, and one invariant it exists to guarantee:

    nothing a parser produced reaches the live catalogue until the run's
    aggregate shape has been checked against that merchant's own history.

The commit boundaries matter and are deliberate:

* staging is committed on its own, so a long crawl does not hold a
  transaction open over the live tables;
* promotion is a single short transaction -- it either lands completely or
  not at all, so the site never serves a half-applied run;
* the run's verdict is committed either way, so a rejection is always
  visible even when nothing was published.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import RawOffer
from ..taxonomy import APPAREL_SLUGS
from .promote import PromotionReport, apply_delistings, promote_run
from .staging import (StagedRun, clear_stage, merchant_id_for, open_run,
                      record_decision, stage_offers)
from .validate import (Baseline, Decision, RunMetrics, Thresholds,
                       baseline_for, metrics_from_stage, validate_run)


@dataclass
class IngestOutcome:
    run_id: int
    merchant_slug: str
    kind: str
    decision: Decision
    reason: str | None = None
    metrics: RunMetrics = field(default_factory=RunMetrics)
    baseline: Baseline = field(default_factory=Baseline)
    promotion: PromotionReport | None = None
    checks: list = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.promotion is not None

    def summary(self) -> str:
        bits = [f"run {self.run_id} {self.merchant_slug}/{self.kind}",
                f"{self.decision.value.upper()}",
                f"offers={self.metrics.offers_seen}",
                f"variants={self.metrics.variants_seen}"]
        if self.metrics.sku_fill_rate is not None:
            bits.append(f"sku_fill={self.metrics.sku_fill_rate:.0%}")
        if self.promotion:
            bits.append(f"promoted={self.promotion.offers_promoted}")
            bits.append(f"unmatched={self.promotion.offers_unmatched}")
            bits.append(f"new_products={self.promotion.products_created}")
            bits.append(f"price_points={self.promotion.price_points_written}")
            if self.promotion.images_backfilled:
                bits.append(f"images={self.promotion.images_backfilled}")
            if self.promotion.offers_delisted:
                bits.append(f"delisted={self.promotion.offers_delisted}")
            if self.promotion.delist_kept:
                bits.append(f"still_live={self.promotion.delist_kept}")
            if self.promotion.delist_unchecked:
                bits.append(
                    f"unconfirmed={self.promotion.delist_unchecked}")
        if self.reason:
            bits.append(f"reason={self.reason}")
        return "  ".join(bits)


#: Run kinds, and the reason there is more than one.
#:
#: `ingest_run_baseline` is keyed on (merchant_id, kind), and every gate
#: check that compares a run to "normal" reads it: the offer-count band, the
#: fill-rate medians, and the delisting a full sweep would do. One kind for
#: both verticals would have judged sportvision's first apparel run -- some
#: 6,500 offers -- against its footwear median of roughly 3,800, which is far
#: outside the plus-or-minus 20 percent band and enforced, not provisional,
#: on a shop with that many promoted runs. Guaranteed rejection, and once
#: promoted the median would have become a blend that means nothing for
#: either vertical.
CATALOG_KIND = "catalog_parse"
APPAREL_KIND = "apparel_parse"


def run_kind_for(offer: RawOffer) -> str:
    """Which run an offer belongs to, from the facet it was found in.

    Taken from the offer rather than passed down from the command, so a
    drain holding both verticals splits into two runs instead of filing one
    under the other's name. A product with no hint -- dsport's sitemap, a
    stock probe -- stays with the catalogue default.
    """
    return (APPAREL_KIND if offer.category_hint in APPAREL_SLUGS
            else CATALOG_KIND)


def ingest(conn, merchant_slug: str, offers: list[RawOffer], *,
           kind: str = CATALOG_KIND,
           requests: int = 0, http_errors: int = 0,
           snapshot_keys: dict[str, str] | None = None,
           thresholds: Thresholds | None = None,
           create_missing_products: bool = True,
           full_sweep: bool = False,
           confirm_gone=None,
           keep_stage: bool = False) -> IngestOutcome:
    """Run the full stage -> validate -> promote cycle for one merchant.

    Returns an outcome describing what happened, including for a rejection.
    A rejected run keeps its staged rows so the parser can be diagnosed and
    the fix replayed over them.

    ``confirm_gone`` turns a full sweep's silence into a question. It is
    handed the run's :class:`DelistCandidate` list -- the active offers the
    sweep did not see -- and returns the subset whose own page proved they
    are gone. Without it nothing is retired: absence from a listing is not
    evidence of removal, and a shop that hides a near-sold-out product
    while still selling it produces exactly that absence.
    """
    merchant_id = merchant_id_for(conn, merchant_slug)
    run_id = open_run(conn, merchant_id, kind)
    run = StagedRun(run_id=run_id, merchant_id=merchant_id, kind=kind,
                    requests=requests, http_errors=http_errors)

    # --- stage (its own transaction) --------------------------------------
    stage_offers(conn, run, offers, snapshot_keys=snapshot_keys)
    conn.commit()

    # --- validate ---------------------------------------------------------
    metrics = metrics_from_stage(conn, run_id, requests=requests,
                                 http_errors=http_errors)
    baseline = baseline_for(conn, merchant_id, kind)
    result = validate_run(metrics, baseline, thresholds)

    outcome = IngestOutcome(
        run_id=run_id, merchant_slug=merchant_slug, kind=kind,
        decision=result.decision, reason=result.reason, metrics=metrics,
        baseline=baseline, checks=result.checks)

    if not result.promote:
        # Record the verdict and stop. The live catalogue is untouched, and
        # the staged rows stay as evidence.
        record_decision(conn, run, metrics, result)
        conn.commit()
        return outcome

    # --- promote (one short transaction) ----------------------------------
    try:
        outcome.promotion = promote_run(
            conn, run_id, merchant_id, merchant_slug,
            create_missing_products=create_missing_products,
            full_sweep=full_sweep, kind=kind)
        record_decision(conn, run, metrics, result)
        conn.commit()
    except Exception:
        # A half-applied run is worse than no run. Roll the whole promotion
        # back, then record the failure in its own transaction.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_run
                      SET status = 'failed', finished_at = now(),
                          rejected_reason = 'promotion raised; rolled back'
                    WHERE id = %s""", (run_id,))
        conn.commit()
        outcome.decision = Decision.REJECTED
        outcome.reason = "promotion raised; rolled back"
        outcome.promotion = None
        raise

    # --- confirm the delist candidates (outside the promotion txn) -------
    candidates = outcome.promotion.delist_candidates
    if candidates:
        if confirm_gone is None:
            outcome.promotion.delist_unchecked = len(candidates)
        else:
            confirmed = list(confirm_gone(candidates))
            outcome.promotion.offers_delisted = apply_delistings(
                conn, confirmed)
            outcome.promotion.delist_kept = len(candidates) - len(confirmed)
            conn.commit()

    if not keep_stage:
        clear_stage(conn, run_id)
        conn.commit()
    return outcome
