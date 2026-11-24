#!/usr/bin/env python
"""Give a fragrance the audience its own title states.

`derive_gender` reads the shelf words every vertical shares. It does not
know that "Pour Femme", "for Woman" or "Uomo" names an audience, and both
perfumeries shelve their niche lines somewhere that states no gender --
e-elixir under Мириси, Schatze under `/niche-fragrances/`. So a bottle whose
own title says who it is for came out NULL.

Measured: 13 of 1,589 live fragrance products, every one of them on a niche
shelf, and all 13 say it outright ("La Fenice Pour Femme", "Rudis for Man",
"Venetian Blue intense - EDP For Man").

`promote.create_product` now fills this at creation. This recovers the
products created before it did, and it has to be a separate pass because
`derive.rederive` reads `derive_gender` too: a re-crawl would leave every
one of these NULL for good.

**Additive only.** A product that already has a gender is not touched, from
either source. The same decision `derive` makes about shelf gender: a
blanket rewrite there would have changed 392 products, 202 of them from
unisex to women.

**It matters beyond the badge.** This gender is the match veto, and the veto
is what holds "La Fenice Pour Femme" apart from "La Fenice Pour Homme" once
`mkagg.fragrance.identity_key` has reduced both to "la fenice".

Safe to re-run: it reads the shops' own stored titles and writes nothing
where the title is silent.

    python scripts/backfill_fragrance_audience.py --dry-run
    python scripts/backfill_fragrance_audience.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402

from mkagg.fragrance import read_gender  # noqa: E402

DSN = os.environ.get(
    "MKAGG_DSN", "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")

# Only products with no gender at all, and only their own offers' titles.
# `raw_title` rather than `model_name`, because `line_name` has already
# stripped "for Woman" out of the latter -- which is why this looks like 2
# products when measured on the model name and is 13 when measured on what
# the shop actually printed.
LOAD_SQL = """
SELECT p.id, p.slug, string_agg(DISTINCT mo.raw_title, E'\\n')
  FROM product p
  JOIN category c ON c.id = p.category_id
  JOIN merchant_offer mo ON mo.product_id = p.id AND mo.status = 'active'
 WHERE c.kind = 'fragrance' AND p.gender IS NULL
 GROUP BY p.id, p.slug
 ORDER BY p.id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    counts: Counter[str] = Counter()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(LOAD_SQL)
        rows = cur.fetchall()

        changes = []
        for product_id, slug, titles in rows:
            for title in (titles or "").split("\n"):
                gender = read_gender(None, title)
                if gender:
                    changes.append((product_id, slug, gender, title))
                    counts[gender] += 1
                    break

        print(f"fragrance products with no gender : {len(rows)}")
        print(f"whose own title states one        : {len(changes)}")
        for gender, n in sorted(counts.items()):
            print(f"    {gender:8} {n}")
        for _pid, slug, gender, title in changes:
            print(f"  {slug[:50]:52} -> {gender:6} ({title[:44]})")

        if args.dry_run:
            print("\ndry run. nothing was changed.")
            return 0

        for product_id, _slug, gender, _title in changes:
            cur.execute(
                """UPDATE product
                      SET gender = %s::gender_t,
                          gender_source = 'title',
                          updated_at = now()
                    WHERE id = %s AND gender IS NULL""",
                (gender, product_id))
        conn.commit()
        print(f"\nfilled {len(changes)} products.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
