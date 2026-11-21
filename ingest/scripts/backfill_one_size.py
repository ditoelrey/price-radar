#!/usr/bin/env python
"""Re-type the universal sizes already in the catalogue.

``offer_variant.size_system`` is decided at promote time, from the label the
shop printed. Until 2026-11-21 the one-size vocabulary was eight spellings
short -- "Унив.", "Една големина", NS, OS, ONE, ONESZ, UNSZ -- so every one
of them landed as ``numeric``, the system that means "a number we could not
place". The storefront's size picker hides numeric rows on purpose, because
these shops' widgets carry twenty codes the shop never sells, so an article
whose only size was universal showed no size at all.

The labels were stored correctly throughout. Only the reading was wrong, so
this recovers them from the database rather than from the shops: no crawl,
no network, and the shops' own words are left exactly as they were.

Safe to re-run. ``read_size`` tests the one-size vocabulary before it looks
at anything else, so the apparel and kids flags a promote pass would supply
cannot change the answer for these rows -- which is what makes recomputing
them without their facet legitimate here, and nowhere else.

    python scripts/backfill_one_size.py --dry-run
    python scripts/backfill_one_size.py
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
    ap.add_argument("--dry-run", action="store_true",
                    help="count what would change and write nothing")
    args = ap.parse_args()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, size_label, size_system::text
                         FROM offer_variant
                        WHERE size_label IS NOT NULL
                          AND size_system::text IS DISTINCT FROM 'one_size'""")
        rows = cur.fetchall()

        moving = [(vid, label, was) for vid, label, was in rows
                  if read_size(label).system == "one_size"]

        by_label = Counter(label for _, label, _ in moving)
        by_from = Counter(was for _, _, was in moving)
        print(f"{len(rows)} variants examined, {len(moving)} re-typed "
              f"as one_size")
        for label, n in by_label.most_common():
            print(f"   {n:6d}  {label!r}")
        print("   from: " + ", ".join(f"{k}={v}" for k, v in
                                      sorted(by_from.items(), key=str)))

        if args.dry_run or not moving:
            print("\n(dry run, nothing written)" if args.dry_run else "")
            return 0

        # The alpha, height and age columns go with it: a universal size has
        # none of them, and a stale value left behind would put the article
        # back in a letter or age filter it does not belong in.
        cur.executemany(
            """UPDATE offer_variant
                  SET size_system         = 'one_size'::size_system,
                      size_alpha          = NULL,
                      size_height_cm      = NULL,
                      size_age_min_months = NULL,
                      size_age_max_months = NULL
                WHERE id = %s""",
            [(vid,) for vid, _, _ in moving])
        conn.commit()
        print(f"\nwrote {len(moving)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
