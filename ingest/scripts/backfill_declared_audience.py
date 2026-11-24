#!/usr/bin/env python
"""Recover the audience the shops published, from snapshots we already hold.

Sport Vision and sport-m print `Пол` and `Возраст` on every product page.
Nothing read Sport Vision's at all, and nothing persisted either shop's: the
gender reached `create_product`, was stamped on the product once, and then
evaporated, because `merchant_offer.merchant_gender` was written only by the
facet walk. Where that walk had not been -- the socks shelf, for both shops
-- the catalogue held a gender that `derive` could neither confirm nor
revise, kept alive only by a clause that declines to clear what it cannot
see.

Measured over Опрема -> Чорапи: 339 Sport Vision offers and 138 sport-m
offers in exactly that state, all 477 of them with both rows readable.

No crawling. `snapshot_key` is ``sha256(url)[:16]``, so every stored page is
addressable from `merchant_offer.product_url`, and this reads them off disk.

**Fills gaps only.** An offer that already carries a gender is left alone:
that value came from the facet walk, which sees a *set* of departments and
is the only evidence that can say unisex at all. This is the weaker source
for men/women/unisex and the stronger one for kids, which is why
`read_declared_audience` lets Возраст decide and Пол only fill in.

Writes `merchant_offer.merchant_gender` and nothing else. Run
`scripts/run_pipeline.py derive` afterwards to let the products take it up;
this script does not, so the two steps can be inspected apart.

    python scripts/backfill_declared_audience.py --dry-run
    python scripts/backfill_declared_audience.py
    python scripts/backfill_declared_audience.py --kind accessory
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402

from mkagg.adapters.aspnet_mk import (parse_specifications,  # noqa: E402
                                      spec_gender)
from mkagg.adapters.sportvision import spec_attr  # noqa: E402
from mkagg.taxonomy import read_declared_audience  # noqa: E402

DSN = os.environ.get(
    "MKAGG_DSN", "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")
SNAPSHOTS = os.environ.get(
    "MKAGG_SNAPSHOTS",
    os.path.join(os.path.dirname(__file__), "..", "..", "raw_snapshots"))

#: Which reader each platform needs. Both already exist in the adapters, so
#: this script cannot drift from what a live crawl would now record.
SV_GROUP = {"sportvision", "buzz", "sportreality"}
ASPNET = {"sportm", "sizeer"}

LOAD_SQL = """
SELECT mo.id, m.slug, mo.product_url, mo.raw_title, c.slug
  FROM merchant_offer mo
  JOIN merchant m ON m.id = mo.merchant_id
  LEFT JOIN product p ON p.id = mo.product_id
  LEFT JOIN category c ON c.id = p.category_id
 WHERE mo.status = 'active'
   AND mo.merchant_gender IS NULL
   AND m.slug = ANY(%(shops)s)
   AND (CAST(%(kind)s AS text) IS NULL
        OR c.kind::text = CAST(%(kind)s AS text))
 ORDER BY mo.id
"""


def snapshot_for(shop: str, url: str) -> str | None:
    """The newest stored page for this URL, or None."""
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    hits = sorted(glob.glob(os.path.join(
        SNAPSHOTS, shop, "*", f"{digest}-*.html.gz")))
    return hits[-1] if hits else None


def audience_from(shop: str, html: str) -> str | None:
    if shop in SV_GROUP:
        return read_declared_audience(spec_attr(html, "pol"),
                                      spec_attr(html, "vozrast"))
    if shop in ASPNET:
        return spec_gender(parse_specifications(html))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--kind", default=None,
                    help="limit to one category kind, e.g. accessory")
    ap.add_argument("--shops", default=",".join(sorted(SV_GROUP | ASPNET)),
                    help="comma-separated merchant slugs")
    args = ap.parse_args()

    shops = [s.strip() for s in args.shops.split(",") if s.strip()]
    found: collections.Counter = collections.Counter()
    missing: collections.Counter = collections.Counter()
    silent: collections.Counter = collections.Counter()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(LOAD_SQL, {"shops": shops, "kind": args.kind})
        rows = cur.fetchall()
        print(f"offers with no gender, in {len(shops)} shops"
              f"{' (' + args.kind + ')' if args.kind else ''}: {len(rows)}")

        updates: list[tuple[str, int]] = []
        for offer_id, shop, url, title, cat in rows:
            path = snapshot_for(shop, url)
            if not path:
                missing[shop] += 1
                continue
            try:
                html = gzip.open(path, "rb").read().decode("utf-8", "replace")
            except OSError:
                missing[shop] += 1
                continue
            audience = audience_from(shop, html)
            if audience:
                found[(shop, audience)] += 1
                updates.append((audience, offer_id))
            else:
                silent[shop] += 1

        print(f"\n  pages on disk and readable : {len(updates) + sum(silent.values())}")
        print(f"  no snapshot stored         : {sum(missing.values())}")
        print(f"  page states no audience    : {sum(silent.values())}")
        print(f"  audience recovered         : {len(updates)}\n")
        for (shop, audience), n in sorted(found.items()):
            print(f"    {shop:14} {audience:8} {n:5}")
        if missing:
            print("\n  missing snapshots per shop:")
            for shop, n in sorted(missing.items()):
                print(f"    {shop:14} {n:5}")

        if args.dry_run:
            print("\ndry run. nothing was changed.")
            return 0
        if not updates:
            print("nothing to write.")
            return 0

        # `IS NULL` again in the predicate: the rows were selected before
        # this loop, and a crawl running alongside it may have filled one.
        # The facet walk's answer is the better one and must win.
        cur.executemany(
            """UPDATE merchant_offer SET merchant_gender = %s
                WHERE id = %s AND merchant_gender IS NULL""", updates)
        conn.commit()
        print(f"\nwrote merchant_gender on {len(updates)} offers.")
        print("now run: python scripts/run_pipeline.py derive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
