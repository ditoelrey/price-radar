#!/usr/bin/env python3
"""End-to-end smoke test across all seven merchants.

    golden fixtures -> adapters -> loader gate -> Postgres -> the real queries

Covers every store on its **robots-permitted** route, which since V7 means
dsport and megasport come in through their product pages rather than the APIs
their sites forbid.

Then it runs the queries the product actually needs:

* the offer list for a product, cheapest first   (detail page)
* the lowest price for one specific size          (size filter)
* the denormalised summary row                    (listing page)

and finishes by showing the gate refusing a broken run.

Idempotent. Usage::

    ./.venv/Scripts/python.exe -X utf8 scripts/smoke_load.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import psycopg  # noqa: E402
from conftest import load_bytes, load_json  # noqa: E402

from mkagg.adapters import get_adapter  # noqa: E402
from mkagg.load import Decision, ingest  # noqa: E402

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")

# merchant -> (adapter, fixture, url, extra sizes fixture)
SOURCES = [
    ("sportvision", "sportvision", "sportvision_caven20.html",
     "https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0", None),
    ("sportreality", "sportvision", "sportreality_caven20.html",
     "https://www.sportreality.mk/mk/patiki/51378-puma-caven-2-0", None),
    ("megasport", "woocommerce_html", "megasport_product_caven20.html",
     "https://megasportonlineshop.com/p/patiki-puma-caven-2-0-2/", None),
    ("buzz", "sportvision", "buzz_stansmith.html",
     "https://www.buzzsneakers.mk/mk/patiki/2011-adidas-patiki-stan-smith", None),
    ("sportm", "aspnet_mk", "sportm_stansmith.html",
     "https://www.sport-m.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
     "sportm_getvelicini_M20325.json"),
    ("sizeer", "aspnet_mk", "sizeer_stansmith.html",
     "https://sizeer.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
     "sizeer_getvelicini_M20325.json"),
    ("dsport", "magento_html", "dsport_product_kj8942.html",
     "https://www.dsport.mk/muskarci/obuca/cizme/"
     "adidas-terrex-skychaser-ax5-mid-gtx-za-mazhi-kj8942", None),
]


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def parse_offer(merchant: str, adapter_slug: str, fixture: str, url: str,
                sizes_fixture: str | None):
    adapter = get_adapter(adapter_slug)
    if adapter_slug == "aspnet_mk":
        return adapter.parse_product(
            load_bytes(fixture), url, merchant,
            sizes_payload=load_json(sizes_fixture),
            # sizeer returns Zaliha = null for every size.
            publishes_stock=(merchant == "sportm"))
    return adapter.parse_product(load_bytes(fixture), url, merchant)


OFFER_LIST_SQL = """
SELECT m.name, m.adapter,
       min(ov.price_minor)                                     AS from_price,
       count(*)                                                AS sizes,
       count(*) FILTER (WHERE ov.in_stock IS TRUE)             AS in_stock,
       count(*) FILTER (WHERE ov.in_stock IS NULL)             AS unknown
  FROM merchant_offer mo
  JOIN merchant m       ON m.id = mo.merchant_id
  JOIN offer_variant ov ON ov.offer_id = mo.id
 WHERE mo.product_id = %s AND mo.status = 'active'
 GROUP BY m.id, m.name, m.adapter
 ORDER BY from_price
"""

SIZE_FILTER_SQL = """
SELECT m.name, ov.size_label, ov.price_minor, ov.in_stock, ov.stock_qty
  FROM merchant_offer mo
  JOIN merchant m       ON m.id = mo.merchant_id
  JOIN offer_variant ov ON ov.offer_id = mo.id
 WHERE mo.product_id = %s AND ov.size_eu = %s
   AND ov.in_stock IS NOT FALSE        -- unknown counts as maybe, not no
 ORDER BY ov.price_minor
"""


def report_product(cur, product_id: int, name: str, mpn: str,
                   size_eu: str) -> None:
    cur.execute("""SELECT min_price_minor, max_price_minor, offer_count,
                          merchant_count, in_stock_offer_count,
                          array_length(available_sizes_eu, 1)
                     FROM product_price_summary WHERE product_id = %s""",
                (product_id,))
    row = cur.fetchone()
    if not row:
        return
    lo, hi, offers, merchants, buyable, sizes = row
    spread = f"{(hi - lo) / lo * 100:.0f}%" if lo else "n/a"
    print(f"\n  {name}   MPN {mpn}")
    print(f"  from {lo:,} to {hi:,} MKD (spread {spread}) | {offers} offers / "
          f"{merchants} shops | {buyable} buyable variants | "
          f"{sizes or 0} distinct sizes")

    print(f"    {'shop':<16}{'route':<18}{'from':>8}{'sizes':>7}"
          f"{'in stock':>10}{'unknown':>9}")
    cur.execute(OFFER_LIST_SQL, (product_id,))
    for shop, adapter, price, sizes_n, in_stock, unknown in cur.fetchall():
        print(f"    {shop:<16}{adapter:<18}{price:>8,}{sizes_n:>7}"
              f"{in_stock:>10}{unknown:>9}")

    cur.execute(SIZE_FILTER_SQL, (product_id, size_eu))
    rows = cur.fetchall()
    print(f"    lowest in EU {size_eu}: ", end="")
    if not rows:
        print("no offer in this size")
        return
    print()
    for shop, label, price, in_stock, qty in rows:
        state = ("in stock" if in_stock else
                 "listed, stock unknown" if in_stock is None else "sold out")
        print(f"      {shop:<16}{price:>8,} MKD  size {label:<9} {state}"
              f"{f' (qty {qty})' if qty else ''}")


def main() -> int:
    rule("ingest: every merchant on its robots-permitted route")
    with psycopg.connect(DSN) as conn:
        for merchant, adapter_slug, fixture, url, sizes in SOURCES:
            offer = parse_offer(merchant, adapter_slug, fixture, url, sizes)
            if offer is None:
                print(f"  {merchant:<14} PARSE FAILED ({fixture})")
                continue
            outcome = ingest(conn, merchant, [offer], requests=1)
            flag = {Decision.OK: "ok", Decision.DEGRADED: "degraded",
                    Decision.REJECTED: "REJECTED"}[outcome.decision]
            created = (outcome.promotion.products_created
                       if outcome.promotion else 0)
            print(f"  {merchant:<14}{adapter_slug:<18}{flag:<10}"
                  f"sizes={len(offer.variants):<4}"
                  f"mpn={str(offer.raw_mpn):<12}new_product={created}")

        rule("the catalogue, as the site would read it")
        with conn.cursor() as cur:
            cur.execute("""SELECT p.id, p.canonical_name, p.primary_mpn
                             FROM product p
                             JOIN product_price_summary s ON s.product_id = p.id
                            ORDER BY s.merchant_count DESC, p.id""")
            for product_id, name, mpn in cur.fetchall():
                report_product(cur, product_id, name, mpn, "44")

        rule("the gate: a parser that started returning 0 MKD")
        broken = parse_offer(*SOURCES[0][:1], *SOURCES[0][1:])
        for variant in broken.variants:
            variant.price_minor = 0
        outcome = ingest(conn, "sportvision", [broken], requests=1)
        print(f"  decision: {outcome.decision.value.upper()}")
        print(f"  reason:   {outcome.reason}")
        print(f"  promoted: {outcome.promoted}")
        with conn.cursor() as cur:
            cur.execute("""SELECT min_price_minor FROM product_price_summary s
                             JOIN product p ON p.id = s.product_id
                            WHERE p.primary_mpn = '39229002'""")
            row = cur.fetchone()
            print(f"  live lowest price for the Caven 2.0 is still "
                  f"{row[0]:,} MKD" if row else "  (no summary row)")
            cur.execute("""SELECT count(*) FROM stage_offer
                            WHERE ingest_run_id = %s""", (outcome.run_id,))
            print(f"  staged rows kept as evidence: {cur.fetchone()[0]}")

        rule("run ledger")
        with conn.cursor() as cur:
            cur.execute("""SELECT m.slug, r.kind, r.status, r.offers_seen,
                                  r.variants_seen, r.sku_fill_rate,
                                  r.price_fill_rate, r.offers_promoted
                             FROM ingest_run r JOIN merchant m ON m.id = r.merchant_id
                            ORDER BY r.id""")
            print(f"  {'merchant':<14}{'status':<11}{'offers':>7}{'variants':>9}"
                  f"{'sku':>6}{'price':>7}{'promoted':>10}")
            for slug, kind, status, offers, variants, sku, price, promoted in cur.fetchall():
                print(f"  {slug:<14}{status:<11}{offers:>7}{variants:>9}"
                      f"{(f'{sku:.0%}' if sku is not None else '-'):>6}"
                      f"{(f'{price:.0%}' if price is not None else '-'):>7}"
                      f"{promoted:>10}")

    print("\nsmoke load OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
