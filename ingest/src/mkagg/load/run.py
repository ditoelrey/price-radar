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
from .promote import PromotionReport, promote_run
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
        if self.reason:
            bits.append(f"reason={self.reason}")
        return "  ".join(bits)


def ingest(conn, merchant_slug: str, offers: list[RawOffer], *,
           kind: str = "catalog_parse",
           requests: int = 0, http_errors: int = 0,
           snapshot_keys: dict[str, str] | None = None,
           thresholds: Thresholds | None = None,
           create_missing_products: bool = True,
           full_sweep: bool = False,
           keep_stage: bool = False) -> IngestOutcome:
    """Run the full stage -> validate -> promote cycle for one merchant.

    Returns an outcome describing what happened, including for a rejection.
    A rejected run keeps its staged rows so the parser can be diagnosed and
    the fix replayed over them.
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
            full_sweep=full_sweep)
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

    if not keep_stage:
        clear_stage(conn, run_id)
        conn.commit()
    return outcome
