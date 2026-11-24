#!/usr/bin/env python
"""Fold together fragrance products the two perfumeries named differently.

One bottle became two product pages whenever e-elixir and Schatze printed
its name differently, and they disagree in three ways: a house prefix
("Emporio Armani Stronger With You" against "Stronger With You"), the brand
echoed mid-name ("Candy Prada", "Asad By Lattafa"), and an audience marker
("Eros" against "Eros Pour Homme"). Measured over 1,625 live products, 36
bottles were split for no other reason.

`mkagg.fragrance.identity_key` is what the matcher now reduces a name with,
and this script groups the existing catalogue by exactly that function --
imported, not reimplemented, so the cleanup and the matcher cannot drift. A
re-crawl would eventually join new offers on its own; it would not join the
products already created, which is what this does.

**The guard.** A reduced key may only join offers from different shops.
Where one shop lists both names separately it is telling us they are two
fragrances: e-elixir sells David Beckham "Classic" and "Classic Homme",
which are two real releases. Those groups are reported and skipped.

**Nothing is lost.** `offer_variant` hangs off `merchant_offer`, so moving
an offer carries its volumes and their prices with it. `product_identifier`
is moved too -- it has no unique constraint, so there is nothing to collide
-- and an image is backfilled onto the survivor where it has none. Only
then is the emptied product deleted, and `merchant_offer.product_id` is
`ON DELETE SET NULL`: deleting first would silently orphan the offers
instead of failing, which is why the order below is not negotiable.

Dry run by default, because this deletes rows. Nothing happens without
``--apply``.

    python scripts/merge_split_fragrances.py
    python scripts/merge_split_fragrances.py --apply
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg  # noqa: E402

from mkagg.fragrance import identity_key  # noqa: E402
from mkagg.load.promote import refresh_summary  # noqa: E402

DSN = os.environ.get(
    "MKAGG_DSN", "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg")

LOAD_SQL = """
SELECT p.id, p.brand_id, b.name, p.model_name, p.concentration,
       p.gender::text, p.slug, p.image_asset_id, p.image_url,
       (SELECT string_agg(DISTINCT m.slug, '+' ORDER BY m.slug)
          FROM merchant_offer mo JOIN merchant m ON m.id = mo.merchant_id
         WHERE mo.product_id = p.id AND mo.status = 'active'),
       (SELECT count(*) FROM merchant_offer WHERE product_id = p.id),
       (SELECT count(*) FROM offer_variant v
          JOIN merchant_offer mo ON mo.id = v.offer_id
         WHERE mo.product_id = p.id)
  FROM product p
  JOIN brand b ON b.id = p.brand_id
  JOIN category c ON c.id = p.category_id
 WHERE c.kind = 'fragrance'
 ORDER BY p.id
"""


def load(conn):
    with conn.cursor() as cur:
        cur.execute(LOAD_SQL)
        rows = cur.fetchall()
    out = []
    for (pid, bid, brand, model, conc, gender, slug, asset, image,
         shops, offers, variants) in rows:
        if not shops:
            # No active offer: nothing to compare and nothing to carry.
            continue
        out.append({
            "id": pid, "brand_id": bid, "brand": brand, "model": model or "",
            "conc": conc, "gender": gender, "slug": slug,
            "asset": asset, "image": image, "shops": set(shops.split("+")),
            "offers": offers, "variants": variants,
        })
    return out


def plan(products):
    """(groups to merge, groups the guard refuses)."""
    groups = collections.defaultdict(list)
    for p in products:
        groups[(p["brand_id"], identity_key(p["model"], p["brand"]),
                p["conc"], p["gender"])].append(p)

    merge, refused = [], []
    for members in groups.values():
        if len(members) < 2:
            continue
        shops = [m["shops"] for m in members]
        shares_a_shop = any(a & b for i, a in enumerate(shops)
                            for b in shops[i + 1:])
        (refused if shares_a_shop else merge).append(
            sorted(members, key=lambda m: m["id"]))
    return merge, refused


def fold(conn, group) -> None:
    """Move everything onto the lowest id, then delete the rest."""
    survivor, *losers = group
    with conn.cursor() as cur:
        for loser in losers:
            cur.execute("""UPDATE merchant_offer SET product_id = %s
                            WHERE product_id = %s""",
                        (survivor["id"], loser["id"]))
            cur.execute("""UPDATE product_identifier SET product_id = %s
                            WHERE product_id = %s""",
                        (survivor["id"], loser["id"]))
            # Whichever shop supplied a photo, the surviving page keeps one.
            cur.execute(
                """UPDATE product AS s
                      SET image_asset_id = COALESCE(s.image_asset_id,
                                                    l.image_asset_id),
                          image_url      = COALESCE(s.image_url, l.image_url),
                          updated_at     = now()
                     FROM product AS l
                    WHERE s.id = %s AND l.id = %s""",
                (survivor["id"], loser["id"]))
            # match_candidate and product_price_summary cascade; the offers
            # and identifiers were moved above, so this empties.
            cur.execute("DELETE FROM product WHERE id = %s", (loser["id"],))
    refresh_summary(conn, survivor["id"])


def show(group, prefix="  ") -> None:
    survivor, *losers = group
    key = identity_key(survivor["model"], survivor["brand"])
    print(f"{prefix}{survivor['brand']} / {survivor['conc'] or '-'} / "
          f"{survivor['gender'] or '-'}  ->  {key!r}")
    print(f"{prefix}  keep  {survivor['slug'][:52]:54} "
          f"{'+'.join(sorted(survivor['shops']))}")
    for loser in losers:
        print(f"{prefix}  fold  {loser['slug'][:52]:54} "
              f"{'+'.join(sorted(loser['shops']))}  "
              f"({loser['offers']} offers, {loser['variants']} variants)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the merges; without it nothing is changed")
    args = ap.parse_args()

    with psycopg.connect(DSN) as conn:
        products = load(conn)
        merge, refused = plan(products)

        both = sum(1 for p in products if len(p["shops"]) > 1)
        print(f"fragrance products with an active offer : {len(products)}")
        print(f"already sold by both shops              : {both}")
        print(f"groups to merge                         : {len(merge)}")
        print(f"groups the guard refuses                : {len(refused)}")
        print(f"products folded away                    : "
              f"{sum(len(g) - 1 for g in merge)}")
        print(f"offers they carry                       : "
              f"{sum(m['offers'] for g in merge for m in g[1:])}")
        print(f"variants under those offers             : "
              f"{sum(m['variants'] for g in merge for m in g[1:])}")
        print(f"comparable products afterwards          : {both + len(merge)}")

        if refused:
            print("\nrefused -- one shop lists both names:")
            for group in refused:
                show(group, prefix="  ")

        print("\nmerges:")
        for group in merge:
            show(group, prefix="  ")

        if not args.apply:
            print("\ndry run. nothing was changed. pass --apply to write.")
            return 0

        # One transaction per group: a surprise rolls back that merge, not
        # the other thirty-five.
        done = 0
        for group in merge:
            try:
                fold(conn, group)
                conn.commit()
                done += 1
            except Exception as exc:              # pragma: no cover
                conn.rollback()
                print(f"  FAILED {group[0]['slug']}: {exc}")
        print(f"\nmerged {done} of {len(merge)} groups.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
