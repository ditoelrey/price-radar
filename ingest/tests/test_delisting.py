"""Retiring offers a sweep no longer sees, without retiring the other vertical.

Delisting has existed since the loader was written and has never been turned
on: every one of the catalogue's 13,046 offers is `active`, including a
Sport-M listing for EG2655 that the shop has since removed and which was
still being shown as the best price three days later.

Turning it on safely needed one change first. The delist statement was
scoped to the merchant alone, so a complete *footwear* sweep would have
retired every *apparel* offer that shop has -- a correct run quietly
destroying a correct catalogue, and the kind of failure that looks like data
loss rather than a bug.
"""
from __future__ import annotations

import os

import pytest

from mkagg.load import APPAREL_KIND, CATALOG_KIND
from mkagg.load.promote import APPAREL_RUN_KIND

DSN = os.environ.get(
    "MKAGG_TEST_DSN",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg_test")


def test_the_two_kind_constants_never_drift():
    """`promote` names the apparel kind locally to avoid an import cycle."""
    assert APPAREL_RUN_KIND == APPAREL_KIND


@pytest.fixture(scope="module")
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        connection = psycopg.connect(DSN, connect_timeout=3)
    except Exception as exc:               # pragma: no cover
        pytest.skip(f"no database at {DSN}: {exc}")
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def clean_db(conn):
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE stage_offer, stage_variant, ingest_run, price_point,
                     click_event, verification_event, match_candidate,
                     user_price_report, product_price_summary, offer_variant,
                     merchant_offer, product_identifier, product
            RESTART IDENTITY CASCADE""")
    conn.commit()
    return conn


def _product(conn, slug, category):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO product (brand_id, category_id, model_name,
                                    canonical_name, primary_mpn, slug)
               VALUES ((SELECT id FROM brand LIMIT 1),
                       (SELECT id FROM category WHERE slug = %s),
                       %s, %s, %s, %s) RETURNING id""",
            (category, slug, slug, slug, slug))
        return cur.fetchone()[0]


def _offer(conn, product_id, sku, merchant="sportm"):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO merchant_offer (merchant_id, product_id,
                        merchant_sku, raw_title, product_url, status)
               VALUES ((SELECT id FROM merchant WHERE slug = %s), %s, %s,
                       %s, %s, 'active') RETURNING id""",
            (merchant, product_id, sku, sku, f"https://x/{sku}"))
        return cur.fetchone()[0]


def _statuses(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT merchant_sku, status FROM merchant_offer
                        ORDER BY merchant_sku""")
        return dict(cur.fetchall())


def _delist(conn, kind, seen_skus, merchant="sportm"):
    """Run the delist statement exactly as promote_run does."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM merchant WHERE slug = %s", (merchant,))
        merchant_id = cur.fetchone()[0]
        cur.execute(
            """UPDATE merchant_offer mo
                  SET status = 'delisted'
                 FROM product p
                 JOIN category c ON c.id = p.category_id
                WHERE mo.product_id = p.id
                  AND mo.merchant_id = %s
                  AND mo.status = 'active'
                  AND mo.merchant_sku <> ALL(%s)
                  AND c.kind::text = %s
              RETURNING mo.product_id""",
            (merchant_id, seen_skus,
             "apparel" if kind == APPAREL_KIND else "footwear"))
        conn.commit()
        return cur.rowcount


class TestDelistingStaysInItsVertical:
    def test_a_footwear_sweep_never_touches_apparel(self, clean_db):
        """The reason this had to be fixed before full_sweep could be used.

        sportm sells 2,047 pairs of shoes and 2,851 garments. A footwear
        sweep legitimately sees none of the garments.
        """
        conn = clean_db
        shoe_kept = _product(conn, "shoe-kept", "sneakers")
        shoe_gone = _product(conn, "shoe-gone", "sneakers")
        shirt = _product(conn, "shirt", "tshirts")
        _offer(conn, shoe_kept, "SHOE-1")
        _offer(conn, shoe_gone, "SHOE-2")
        _offer(conn, shirt, "SHIRT-1")
        conn.commit()

        _delist(conn, CATALOG_KIND, ["SHOE-1"])

        assert _statuses(conn) == {
            "SHOE-1": "active",      # seen
            "SHOE-2": "delisted",    # not seen, same vertical
            "SHIRT-1": "active",     # other vertical, not this run's business
        }

    def test_an_apparel_sweep_never_touches_footwear(self, clean_db):
        conn = clean_db
        shoe = _product(conn, "shoe", "sneakers")
        shirt_kept = _product(conn, "shirt-kept", "tshirts")
        shirt_gone = _product(conn, "shirt-gone", "hoodies")
        _offer(conn, shoe, "SHOE-1")
        _offer(conn, shirt_kept, "SHIRT-1")
        _offer(conn, shirt_gone, "SHIRT-2")
        conn.commit()

        _delist(conn, APPAREL_KIND, ["SHIRT-1"])

        assert _statuses(conn) == {
            "SHOE-1": "active",
            "SHIRT-1": "active",
            "SHIRT-2": "delisted",
        }

    def test_an_unclassified_product_is_left_alone_by_both(self, clean_db):
        """203 products have no category, and most of them are shoes.

        Delisting on an absence of evidence is how a live offer vanishes for
        a reason nobody can reconstruct afterwards.
        """
        conn = clean_db
        unknown = _product(conn, "mystery", None)
        _offer(conn, unknown, "MYST-1")
        conn.commit()

        _delist(conn, CATALOG_KIND, ["SOMETHING-ELSE"])
        assert _statuses(conn) == {"MYST-1": "active"}

        _delist(conn, APPAREL_KIND, ["SOMETHING-ELSE"])
        assert _statuses(conn) == {"MYST-1": "active"}

    def test_accessories_and_equipment_belong_to_neither_sweep(self,
                                                               clean_db):
        """Caught by counting before running, not by a test first.

        megasport has 80 accessory and 13 equipment offers that its footwear
        facets never visit. A first attempt scoped delisting to "everything
        that is not apparel", which swept all 93 of them up -- and no sweep
        walks those trees, so nothing would ever have restored them.
        """
        conn = clean_db
        shoe = _product(conn, "shoe", "sneakers")
        sock = _product(conn, "sock", "socks")          # kind = accessory
        ball = _product(conn, "ball", "equipment")
        _offer(conn, shoe, "SHOE-1")
        _offer(conn, sock, "SOCK-1")
        _offer(conn, ball, "BALL-1")
        conn.commit()

        _delist(conn, CATALOG_KIND, ["NOTHING-SEEN"])

        assert _statuses(conn) == {
            "SHOE-1": "delisted",   # footwear run, footwear offer, not seen
            "SOCK-1": "active",     # accessory: not this run's vertical
            "BALL-1": "active",     # equipment: likewise
        }

    def test_another_merchant_is_never_in_scope(self, clean_db):
        conn = clean_db
        shoe = _product(conn, "shoe", "sneakers")
        _offer(conn, shoe, "SHARED-SKU", merchant="sportm")
        _offer(conn, shoe, "SHARED-SKU", merchant="sizeer")
        conn.commit()

        _delist(conn, CATALOG_KIND, ["NOTHING"], merchant="sportm")

        with conn.cursor() as cur:
            cur.execute("""SELECT m.slug, mo.status FROM merchant_offer mo
                             JOIN merchant m ON m.id = mo.merchant_id
                            ORDER BY m.slug""")
            assert dict(cur.fetchall()) == {"sportm": "delisted",
                                            "sizeer": "active"}
