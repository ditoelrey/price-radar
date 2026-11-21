#!/usr/bin/env python
"""Re-read the labels that name two letter sizes.

"M/L", "L/XL", "XS/S", "S/M" and "2XS/XS" are one article sold across a span
of the ladder. Until V26 there was nowhere to put the second letter, so they
read as ``numeric`` -- and the listing's letter rail and the ``size`` filter
both work from ``size_alpha``, which left those garments unreachable by any
letter, including the two on their own label.

The labels were always stored. This recomputes the reading from them, so no
crawl is needed and the shops' own words are untouched.

What it deliberately leaves alone, because the same punctuation means
something else on these shops::

    L/S  M/S  XL/S  S/S     a size and a *length* -- Short
    L-T  2XL-T  4XL-T       a size and a length -- Tall
    S A-C  XS A-C           a bra band and a cup range

``mkagg.sizing._alpha_span`` refuses all of them: a span has to climb the
ladder, and dashes are excluded outright. See V26 for the reasoning.

Safe to re-run.

    python scripts/backfill_alpha_spans.py --dry-run
    python scripts/backfill_alpha_spans.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402

from mkagg.sizing import read_size  # noqa: E402

DSN = os.environ.get(
    "MKAGG_DSN", "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, size_label, size_system::text,
                              size_alpha, size_alpha_max
                         FROM offer_variant
                        WHERE size_label LIKE '%/%'""")
        rows = cur.fetchall()

        moving = []
        for vid, label, system, alpha, alpha_max in rows:
            read = read_size(label)
            if read.alpha_max is None:
                continue
            if (system, alpha, alpha_max) == ("alpha", read.alpha,
                                              read.alpha_max):
                continue
            moving.append((vid, label, read.alpha, read.alpha_max))

        print(f"{len(rows)} slashed labels examined, {len(moving)} re-read "
              f"as a span")
        for (label, lo, hi), n in Counter(
                (m[1], m[2], m[3]) for m in moving).most_common():
            print(f"   {n:6d}  {label!r:10s} -> {lo}..{hi}")

        if args.dry_run or not moving:
            print("\n(dry run, nothing written)" if args.dry_run else "")
            return 0

        cur.executemany(
            """UPDATE offer_variant
                  SET size_system    = 'alpha'::size_system,
                      size_alpha     = %s,
                      size_alpha_max = %s
                WHERE id = %s""",
            [(lo, hi, vid) for vid, _, lo, hi in moving])
        conn.commit()
        print(f"\nwrote {len(moving)} rows")

        # The rail is denormalised, so a product whose variants just changed
        # letter is still advertising the old (empty) set until something
        # refreshes it.
        cur.execute("""
            WITH touched AS (
                SELECT DISTINCT mo.product_id
                  FROM offer_variant ov
                  JOIN merchant_offer mo ON mo.id = ov.offer_id
                 WHERE ov.size_alpha_max IS NOT NULL
            ), computed AS (
                SELECT t.product_id,
                       coalesce((
                           SELECT array_agg(a ORDER BY alpha_size_rank(a), a)
                             FROM (SELECT DISTINCT unnest(alpha_size_span(
                                              ov.size_alpha,
                                              ov.size_alpha_max)) AS a
                                     FROM offer_variant ov
                                     JOIN merchant_offer mo
                                       ON mo.id = ov.offer_id
                                     JOIN merchant m ON m.id = mo.merchant_id
                                    WHERE mo.product_id = t.product_id
                                      AND mo.status = 'active'
                                      AND m.is_active
                                      AND ov.size_alpha IS NOT NULL
                                      AND ov.in_stock IS NOT FALSE) x),
                           '{}') AS sizes
                  FROM touched t
            )
            UPDATE product_price_summary s
               SET available_sizes_alpha = c.sizes
              FROM computed c
             WHERE s.product_id = c.product_id
               AND s.available_sizes_alpha IS DISTINCT FROM c.sizes""")
        print(f"refreshed {cur.rowcount} summary rows")
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
