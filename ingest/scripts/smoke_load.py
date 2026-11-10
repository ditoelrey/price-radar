#!/usr/bin/env python3
"""End-to-end smoke test: golden fixtures -> adapters -> matcher -> Postgres.

This is the proof that the schema and the ingestion objects actually fit
together, rather than each being independently plausible. It loads the two
Phase 1 test cases and then runs the real queries the product needs:

* the offer list for a product, cheapest total first  (detail page)
* the lowest price for one specific size               (size filter)
* the denormalised summary row                         (listing page)

Idempotent -- safe to re-run. Usage::

    ./.venv/Scripts/python.exe -X utf8 scripts/smoke_load.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import psycopg  # noqa: E402
from conftest import TEST_CASE_A, TEST_CASE_B, load_bytes, load_json  # noqa: E402

from mkagg.adapters import get_adapter  # noqa: E402
from mkagg.matching import match_offer  # noqa: E402
from mkagg.models import ProductCandidate  # noqa: E402
from mkagg.normalize import normalize_sku, slugify  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")


# ---------------------------------------------------------------------------
# Parse the fixtures through the real adapters
# ---------------------------------------------------------------------------

def build_offers():
    """Return {case_key: [RawOffer, ...]} for both golden test cases."""
    sv, woo, asp = (get_adapter("sportvision"), get_adapter("woocommerce"),
                    get_adapter("aspnet_mk"))
    out: dict[str, list] = {"A": [], "B": []}

    for slug in ("sportvision", "sportreality"):
        fixture, url, _ = TEST_CASE_A["stores"][slug]
        out["A"].append(sv.parse_product(load_bytes(fixture), url, slug))

    megasport = woo.parse_many(
        load_json(TEST_CASE_A["stores"]["megasport"][0]),
        "https://megasportonlineshop.com", "megasport")
    out["A"].append(next(o for o in megasport
                         if normalize_sku(o.raw_mpn) == TEST_CASE_A["mpn_norm"]))

    fixture, url, _ = TEST_CASE_B["stores"]["buzz"]
    out["B"].append(sv.parse_product(load_bytes(fixture), url, "buzz"))

    for slug, sizes_fixture in (("sportm", "sportm_getvelicini_M20325.json"),
                                ("sizeer", "sizeer_getvelicini_M20325.json")):
        fixture, url, _ = TEST_CASE_B["stores"][slug]
        out["B"].append(asp.parse_product(
            load_bytes(fixture), url, slug,
            sizes_payload=load_json(sizes_fixture),
            # The flag that keeps sizeer's unknown stock out of the UI.
            publishes_stock=(slug == "sportm")))
    return out


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_case(cur, case: dict, offers: list) -> int:
    brand_slug = slugify(case["brand"])
    cur.execute("SELECT id FROM brand WHERE slug = %s", (brand_slug,))
    brand_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM category WHERE slug = 'sneakers'")
    category_id = cur.fetchone()[0]

    canonical = f"{case['brand']} {case['model']}"
    cur.execute(
        """
        INSERT INTO product (brand_id, category_id, model_name, canonical_name,
                             gender, primary_mpn, slug)
             VALUES (%s, %s, %s, %s, 'unisex', %s, %s)
        ON CONFLICT (slug) DO UPDATE SET updated_at = now()
          RETURNING id
        """,
        (brand_id, category_id, case["model"], canonical,
         case["mpn_norm"], slugify(canonical)))
    product_id = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO product_identifier (product_id, id_type, value_norm, source)
             VALUES (%s, 'MPN', %s, 'jsonld')
        ON CONFLICT DO NOTHING
        """,
        (product_id, case["mpn_norm"]))

    candidate = ProductCandidate(
        product_id=product_id, brand_slug=brand_slug,
        model_name=case["model"], canonical_name=canonical,
        primary_mpn=case["mpn_norm"], identifiers={case["mpn_norm"]})

    for offer in offers:
        result = match_offer(offer, [candidate])
        assert result.is_auto, (
            f"{offer.merchant_slug} failed to auto-match: {result}")

        cur.execute("SELECT id FROM merchant WHERE slug = %s",
                    (offer.merchant_slug,))
        merchant_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO merchant_offer (merchant_id, product_id, merchant_sku,
                                        raw_mpn, raw_title, raw_brand,
                                        product_url, match_method,
                                        match_confidence, status, last_seen_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', now())
            ON CONFLICT (merchant_id, merchant_sku) DO UPDATE
                    SET product_id = EXCLUDED.product_id,
                        last_seen_at = now(),
                        status = 'active'
              RETURNING id
            """,
            (merchant_id, product_id, offer.merchant_sku, offer.raw_mpn,
             offer.raw_title[:300], offer.raw_brand, offer.product_url,
             result.method, result.confidence))
        offer_id = cur.fetchone()[0]

        for variant in offer.variants:
            cur.execute(
                """
                INSERT INTO offer_variant (
                        offer_id, size_label, size_eu, size_uk, size_cm,
                        merchant_variant_id, price_minor, list_price_minor,
                        currency_code, in_stock, stock_qty, last_checked_at)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (offer_id, size_label) DO UPDATE
                        SET price_minor = EXCLUDED.price_minor,
                            in_stock = EXCLUDED.in_stock,
                            stock_qty = EXCLUDED.stock_qty,
                            last_checked_at = now()
                  RETURNING id
                """,
                (offer_id, variant.size_label, variant.size_eu, variant.size_uk,
                 variant.size_cm, variant.merchant_variant_id,
                 variant.price_minor, variant.list_price_minor,
                 variant.currency_code, variant.in_stock, variant.stock_qty))
            variant_id = cur.fetchone()[0]

            # Append-only history. Real ingest writes this ONLY when the value
            # changed; the smoke loader always writes one point.
            cur.execute(
                """
                INSERT INTO price_point (offer_variant_id, observed_at,
                                         price_minor, in_stock, stock_qty)
                     VALUES (%s, now(), %s, %s, %s)
                """,
                (variant_id, variant.price_minor, variant.in_stock,
                 variant.stock_qty))

    refresh_summary(cur, product_id)
    return product_id


def refresh_summary(cur, product_id: int) -> None:
    """Rebuild the denormalised read model the listing page uses.

    The listing page must never aggregate over offer_variant at request time.
    """
    cur.execute(
        """
        WITH v AS (
            SELECT ov.*, mo.merchant_id
              FROM offer_variant ov
              JOIN merchant_offer mo ON mo.id = ov.offer_id
             WHERE mo.product_id = %(pid)s AND mo.status = 'active'
        )
        INSERT INTO product_price_summary (
                product_id, country_code, min_price_minor, min_price_variant_id,
                max_price_minor, currency_code, offer_count, merchant_count,
                in_stock_offer_count, available_sizes_eu, updated_at)
        SELECT %(pid)s, 'MK',
               min(price_minor),
               (SELECT id FROM v ORDER BY price_minor LIMIT 1),
               max(price_minor),
               max(currency_code),
               count(DISTINCT offer_id),
               count(DISTINCT merchant_id),
               count(*) FILTER (WHERE in_stock IS TRUE),
               coalesce(array_agg(DISTINCT size_eu)
                        FILTER (WHERE size_eu IS NOT NULL
                                  AND in_stock IS NOT FALSE), '{}'),
               now()
          FROM v
        ON CONFLICT (product_id) DO UPDATE SET
                min_price_minor      = EXCLUDED.min_price_minor,
                min_price_variant_id = EXCLUDED.min_price_variant_id,
                max_price_minor      = EXCLUDED.max_price_minor,
                currency_code        = EXCLUDED.currency_code,
                offer_count          = EXCLUDED.offer_count,
                merchant_count       = EXCLUDED.merchant_count,
                in_stock_offer_count = EXCLUDED.in_stock_offer_count,
                available_sizes_eu   = EXCLUDED.available_sizes_eu,
                updated_at           = now()
        """,
        {"pid": product_id})


# ---------------------------------------------------------------------------
# The queries the product actually needs
# ---------------------------------------------------------------------------

OFFER_LIST_SQL = """
SELECT m.name,
       min(ov.price_minor) AS from_price,
       count(*)                                  AS sizes_listed,
       count(*) FILTER (WHERE ov.in_stock IS TRUE)  AS sizes_in_stock,
       count(*) FILTER (WHERE ov.in_stock IS NULL)  AS sizes_unknown,
       m.publishes_stock
  FROM merchant_offer mo
  JOIN merchant m       ON m.id = mo.merchant_id
  JOIN offer_variant ov ON ov.offer_id = mo.id
 WHERE mo.product_id = %s AND mo.status = 'active'
 GROUP BY m.id, m.name, m.publishes_stock
 ORDER BY from_price
"""

SIZE_FILTER_SQL = """
SELECT m.name, ov.size_label, ov.price_minor, ov.in_stock, ov.stock_qty
  FROM merchant_offer mo
  JOIN merchant m       ON m.id = mo.merchant_id
  JOIN offer_variant ov ON ov.offer_id = mo.id
 WHERE mo.product_id = %s
   AND ov.size_eu = %s
   AND ov.in_stock IS NOT FALSE          -- unknown counts as maybe, not no
 ORDER BY ov.price_minor
"""


def report(cur, label: str, product_id: int, size_eu: str) -> None:
    print(f"\n{'=' * 68}\n{label}  (product_id={product_id})\n{'=' * 68}")

    cur.execute("SELECT canonical_name, primary_mpn FROM product WHERE id = %s",
                (product_id,))
    name, mpn = cur.fetchone()
    print(f"  {name}   MPN {mpn}")

    cur.execute(
        """SELECT min_price_minor, max_price_minor, offer_count,
                  merchant_count, in_stock_offer_count,
                  array_length(available_sizes_eu, 1)
             FROM product_price_summary WHERE product_id = %s""",
        (product_id,))
    lo, hi, offers, merchants, in_stock, sizes = cur.fetchone()
    spread = f"{(hi - lo) / lo * 100:.0f}%" if lo else "n/a"
    # in_stock_offer_count counts variant ROWS across all shops, while
    # available_sizes_eu counts DISTINCT sizes -- they are different units and
    # labelling both "sizes" makes the summary look self-contradictory.
    print(f"  summary: from {lo:,} to {hi:,} MKD  (spread {spread}) | "
          f"{offers} offers / {merchants} shops | "
          f"{in_stock} buyable variants | {sizes} distinct sizes")

    print("\n  offers, cheapest first:")
    print(f"    {'shop':<16}{'from':>9}  {'sizes':>6}{'in stock':>10}"
          f"{'unknown':>9}  stock data")
    cur.execute(OFFER_LIST_SQL, (product_id,))
    for shop, price, listed, in_st, unknown, publishes in cur.fetchall():
        flag = "quantities" if publishes else "NOT PUBLISHED"
        print(f"    {shop:<16}{price:>9,}  {listed:>6}{in_st:>10}"
              f"{unknown:>9}  {flag}")

    print(f"\n  lowest price in EU size {size_eu}:")
    cur.execute(SIZE_FILTER_SQL, (product_id, size_eu))
    rows = cur.fetchall()
    if not rows:
        print("    no offer in this size")
    for shop, label_, price, in_stock_, qty in rows:
        state = ("in stock" if in_stock_ else
                 "listed, stock unknown" if in_stock_ is None else "sold out")
        qty_s = f" (qty {qty})" if qty else ""
        print(f"    {shop:<16}{price:>9,} MKD  size {label_:<9} {state}{qty_s}")


def main() -> int:
    offers = build_offers()
    with psycopg.connect(DSN, autocommit=False) as conn, conn.cursor() as cur:
        pid_a = load_case(cur, TEST_CASE_A, offers["A"])
        pid_b = load_case(cur, TEST_CASE_B, offers["B"])
        conn.commit()

        report(cur, "TEST CASE A -- Puma Caven 2.0", pid_a, "44")
        report(cur, "TEST CASE B -- Adidas Stan Smith", pid_b, "44")

        cur.execute("SELECT count(*) FROM price_point")
        print(f"\nprice_point rows written: {cur.fetchone()[0]}")
    print("\nsmoke load OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
