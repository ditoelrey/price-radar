"""Writing parsed offers into the staging tables.

Staging is the cheap half of the loader: append what the adapter saw, with no
interpretation and no foreign keys into the catalogue. Matching, upserting and
summary refreshing all happen later, in :mod:`mkagg.load.promote`, and only
once the run has passed its gate.

Keeping them apart is what allows a long catalogue crawl to run for minutes
without holding a transaction open over the live tables.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..models import RawOffer


@dataclass(slots=True)
class StagedRun:
    run_id: int
    merchant_id: int
    kind: str
    offers_staged: int = 0
    variants_staged: int = 0
    requests: int = 0
    http_errors: int = 0


def open_run(conn, merchant_id: int, kind: str = "catalog_parse") -> int:
    """Open an ``ingest_run`` row and return its id."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ingest_run (merchant_id, kind, status)
                    VALUES (%s, %s, 'running') RETURNING id""",
            (merchant_id, kind))
        return cur.fetchone()[0]


def merchant_id_for(conn, slug: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM merchant WHERE slug = %s", (slug,))
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"no merchant with slug {slug!r}")
    return row[0]


def stage_offers(conn, run: StagedRun, offers: list[RawOffer], *,
                 snapshot_keys: dict[str, str] | None = None) -> StagedRun:
    """Append offers and their variants to staging.

    Idempotent per run: re-staging the same ``merchant_sku`` within one run
    updates it rather than erroring, because a catalogue sweep can legitimately
    encounter the same product on two category pages.
    """
    snapshot_keys = snapshot_keys or {}
    with conn.cursor() as cur:
        for offer in offers:
            if not offer or not offer.merchant_sku:
                continue
            cur.execute(
                """
                INSERT INTO stage_offer (
                        ingest_run_id, merchant_id, merchant_sku, raw_mpn,
                        raw_title, raw_brand, product_url, image_url,
                        currency_code, extractors, quality_issues, snapshot_key,
                        category_hint)
                     VALUES (%(run)s, %(merchant)s, %(sku)s, %(mpn)s, %(title)s,
                             %(brand)s, %(url)s, %(image)s, %(currency)s,
                             %(extractors)s, %(issues)s, %(snapshot)s,
                             %(hint)s)
                ON CONFLICT (ingest_run_id, merchant_id, merchant_sku) DO UPDATE
                        SET raw_mpn        = EXCLUDED.raw_mpn,
                            raw_title      = EXCLUDED.raw_title,
                            raw_brand      = EXCLUDED.raw_brand,
                            product_url    = EXCLUDED.product_url,
                            image_url      = EXCLUDED.image_url,
                            extractors     = EXCLUDED.extractors,
                            quality_issues = EXCLUDED.quality_issues,
                            category_hint  = COALESCE(EXCLUDED.category_hint,
                                                      stage_offer.category_hint)
                  RETURNING id
                """,
                {"run": run.run_id, "merchant": run.merchant_id,
                 "sku": offer.merchant_sku, "mpn": offer.raw_mpn,
                 "title": offer.raw_title[:500], "brand": offer.raw_brand,
                 "url": offer.product_url, "image": offer.image_url,
                 "currency": offer.currency_code,
                 "extractors": json.dumps(offer.extractors),
                 "issues": offer.quality_issues(),
                 "snapshot": snapshot_keys.get(offer.merchant_sku),
                 "hint": offer.category_hint})
            stage_offer_id = cur.fetchone()[0]
            run.offers_staged += 1

            for variant in offer.variants:
                cur.execute(
                    """
                    INSERT INTO stage_variant (
                            stage_offer_id, size_label, size_eu, size_uk,
                            size_cm, merchant_variant_id, price_minor,
                            list_price_minor, currency_code,
                            shipping_cost_minor, in_stock, stock_qty)
                         VALUES (%(offer)s, %(label)s, %(eu)s, %(uk)s, %(cm)s,
                                 %(vid)s, %(price)s, %(list)s, %(currency)s,
                                 %(ship)s, %(in_stock)s, %(qty)s)
                    ON CONFLICT (stage_offer_id, size_label) DO UPDATE
                            SET price_minor      = EXCLUDED.price_minor,
                                list_price_minor = EXCLUDED.list_price_minor,
                                in_stock         = EXCLUDED.in_stock,
                                stock_qty        = EXCLUDED.stock_qty
                    """,
                    {"offer": stage_offer_id, "label": variant.size_label,
                     "eu": variant.size_eu, "uk": variant.size_uk,
                     "cm": variant.size_cm,
                     "vid": variant.merchant_variant_id,
                     "price": variant.price_minor,
                     "list": variant.list_price_minor,
                     "currency": variant.currency_code,
                     "ship": variant.shipping_cost_minor,
                     "in_stock": variant.in_stock, "qty": variant.stock_qty})
                run.variants_staged += 1
    return run


def record_decision(conn, run: StagedRun, metrics, result) -> None:
    """Write the gate's verdict and every metric it weighed onto the run."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ingest_run
                  SET status          = %(status)s,
                      finished_at     = now(),
                      offers_seen     = %(offers)s,
                      variants_seen   = %(variants)s,
                      http_errors     = %(errors)s,
                      sku_fill_rate   = %(sku)s,
                      price_fill_rate = %(price)s,
                      size_fill_rate  = %(size)s,
                      extractor_stats = %(extractors)s,
                      decision_detail = %(detail)s,
                      rejected_reason = %(reason)s
                WHERE id = %(id)s""",
            {"status": result.decision.value,
             "offers": metrics.offers_seen,
             "variants": metrics.variants_seen,
             "errors": metrics.http_errors,
             "sku": metrics.sku_fill_rate,
             "price": metrics.price_fill_rate,
             "size": metrics.size_fill_rate,
             "extractors": json.dumps({
                 "tiers": metrics.extractor_stats,
                 "quality_issues": metrics.quality_issues}),
             "detail": json.dumps(result.as_dict()),
             "reason": result.reason if not result.promote else None,
             "id": run.run_id})


def clear_stage(conn, run_id: int) -> None:
    """Drop a run's staged rows.

    Called for promoted runs only. A **rejected** run keeps its rows on
    purpose: they are the evidence for diagnosing what the parser did, and
    they are what a fixed parser replays.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM stage_offer WHERE ingest_run_id = %s", (run_id,))
