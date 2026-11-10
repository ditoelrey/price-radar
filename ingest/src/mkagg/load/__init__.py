"""Loader: staged rows -> validated -> live catalogue.

    adapter.parse_*  ->  stage_offer/stage_variant  ->  validate_run
                                                     ->  promote_run  (live)
                                                     ->  rejected     (kept)

The one invariant: a run that fails its gate is never promoted. A parser
quietly returning half the sizes, or "0 MKD", must not be able to publish
that, because a confidently wrong price costs more trust than a stale one and
is much harder to notice.
"""
from .promote import (PromotionReport, ensure_brand, promote_run,
                      refresh_summary, resolve_brand, resolve_offer)
from .run import IngestOutcome, ingest
from .staging import (StagedRun, clear_stage, merchant_id_for, open_run,
                      record_decision, stage_offers)
from .validate import (Baseline, Check, Decision, RunMetrics, Thresholds,
                       ValidationResult, baseline_for, metrics_from_stage,
                       validate_run)

__all__ = [
    "Baseline", "Check", "Decision", "IngestOutcome", "PromotionReport",
    "RunMetrics", "StagedRun", "Thresholds", "ValidationResult",
    "baseline_for", "clear_stage", "ensure_brand", "ingest",
    "merchant_id_for",
    "metrics_from_stage", "open_run", "promote_run", "record_decision",
    "refresh_summary", "resolve_brand", "resolve_offer", "stage_offers",
    "validate_run",
]
