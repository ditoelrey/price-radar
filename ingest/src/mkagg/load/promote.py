"""Promotion: staged rows -> the live catalogue, in one short transaction.

Only runs that passed the gate get here. Promotion does the interpretation
that staging deliberately avoided:

1. resolve each staged offer to a product (exact MPN first, then a blocked
   fuzzy fallback, then leave it unmatched);
2. upsert ``merchant_offer`` and ``offer_variant``;
3. append to ``price_point`` **only where a value actually moved**;
4. rebuild ``product_price_summary`` for the touched products.

Unmatched offers are kept, never discarded. They routinely match later, when
another store reveals the same article code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..matching import match_offer
from ..models import MatchResult, ProductCandidate, RawOffer, RawVariant
from ..normalize import normalize_sku, slugify, translit_mk


@dataclass
class PromotionReport:
    offers_promoted: int = 0
    offers_unmatched: int = 0
    variants_written: int = 0
    price_points_written: int = 0
    products_created: int = 0
    products_touched: set[int] = field(default_factory=set)
    candidates_queued: int = 0
    offers_delisted: int = 0
    images_backfilled: int = 0


# -----------------------------------------------------------------------------
# Reading staged rows back out
# -----------------------------------------------------------------------------

STAGED_SQL = """
SELECT so.id, so.merchant_sku, so.raw_mpn, so.raw_title, so.raw_brand,
       so.product_url, so.image_url, so.currency_code, so.extractors
  FROM stage_offer so
 WHERE so.ingest_run_id = %(run)s
 ORDER BY so.id
"""

STAGED_VARIANTS_SQL = """
SELECT size_label, size_eu, size_uk, size_cm, merchant_variant_id,
       price_minor, list_price_minor, currency_code, shipping_cost_minor,
       in_stock, stock_qty
  FROM stage_variant
 WHERE stage_offer_id = %(offer)s
 ORDER BY size_eu NULLS LAST, size_label
"""


def _staged_offers(conn, run_id: int, merchant_slug: str):
    with conn.cursor() as cur:
        cur.execute(STAGED_SQL, {"run": run_id})
        rows = cur.fetchall()
        for (stage_id, sku, mpn, title, brand, url, image, currency,
             extractors) in rows:
            cur.execute(STAGED_VARIANTS_SQL, {"offer": stage_id})
            variants = [
                RawVariant(
                    size_label=v[0], size_eu=v[1], size_uk=v[2], size_cm=v[3],
                    merchant_variant_id=v[4], price_minor=v[5],
                    list_price_minor=v[6], currency_code=v[7],
                    shipping_cost_minor=v[8], in_stock=v[9], stock_qty=v[10])
                for v in cur.fetchall()
            ]
            yield RawOffer(
                merchant_slug=merchant_slug, merchant_sku=sku, raw_mpn=mpn,
                raw_title=title, raw_brand=brand, product_url=url,
                image_url=image, currency_code=currency, variants=variants,
                extractors=extractors or {})


# -----------------------------------------------------------------------------
# Brand and product resolution
# -----------------------------------------------------------------------------

def resolve_brand(conn, raw_brand: str | None, title: str = "") -> int | None:
    """Resolve a shop's brand string to a catalogue brand.

    Checks the alias list, which is where the Cyrillic forms live -- MK shops
    and MK shoppers both write "Најк" and "Nike". Falls back to looking for a
    known brand token inside the product title, since several stores put the
    brand only there.
    """
    with conn.cursor() as cur:
        if raw_brand:
            needle = translit_mk(raw_brand).strip()
            cur.execute(
                """SELECT id FROM brand
                    WHERE lower(name) = %(n)s
                       OR slug = %(slug)s
                       OR EXISTS (SELECT 1 FROM unnest(aliases) a
                                   WHERE lower(a) = %(n)s
                                      OR lower(a) = %(raw)s)
                    LIMIT 1""",
                {"n": needle, "slug": slugify(raw_brand),
                 "raw": raw_brand.strip().lower()})
            row = cur.fetchone()
            if row:
                return row[0]

        if title:
            hay = f" {translit_mk(title)} "
            cur.execute("SELECT id, slug, name, aliases FROM brand")
            for brand_id, slug, name, aliases in cur.fetchall():
                for token in {slug, name, *(aliases or [])}:
                    token = translit_mk(str(token)).strip()
                    if len(token) >= 3 and f" {token} " in hay:
                        return brand_id
    return None


#: A brand name we are willing to create on demand: one to three words of
#: letters, digits, apostrophes or hyphens. Deliberately narrow, because this
#: only ever runs on a merchant's own brand *field* -- never on a token guessed
#: out of a title, which would fill the table with rubbish.
_BRAND_NAME = re.compile(r"^[\w''&.-]+(?: [\w''&.-]+){0,2}$", re.UNICODE)


def ensure_brand(conn, raw_brand: str | None, title: str = "") -> int | None:
    """Resolve a brand, creating it if the name looks legitimate.

    Brand is a long tail here and the matcher *blocks* on brand, so an
    unseeded brand means an offer is kept but can never join a product. The
    first live run lost "Mont" and "Hoka" to exactly that.
    """
    brand_id = resolve_brand(conn, raw_brand, title)
    if brand_id is not None or not raw_brand:
        return brand_id

    name = " ".join(raw_brand.split()).strip()
    if not (2 <= len(name) <= 40) or not _BRAND_NAME.match(name):
        return None

    slug = slugify(name)
    if not slug:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO brand (slug, name, aliases)
                    VALUES (%s, %s, %s)
               ON CONFLICT (slug) DO UPDATE SET name = brand.name
                 RETURNING id""",
            (slug, name, [name.lower(), translit_mk(name)]))
        return cur.fetchone()[0]


def find_product_by_mpn(conn, mpn_norm: str) -> int | None:
    """Exact identifier lookup -- the path ~70%+ of offers take.

    Done in SQL rather than by loading candidates into Python: with every MK
    store publishing article codes, this is a primary-key hit and there is no
    reason to pay for anything cleverer.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT product_id FROM product_identifier
                WHERE id_type IN ('MPN', 'GTIN13', 'UPC') AND value_norm = %s
                LIMIT 1""",
            (mpn_norm,))
        row = cur.fetchone()
    return row[0] if row else None


def find_learned_merchant_sku(conn, merchant_id: int,
                              merchant_sku: str) -> int | None:
    """A pair a human already confirmed. Never scored again."""
    norm = normalize_sku(merchant_sku)
    if not norm:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT product_id FROM product_identifier
                WHERE id_type = 'MERCHANT_SKU' AND merchant_id = %s
                  AND value_norm = %s LIMIT 1""",
            (merchant_id, norm))
        row = cur.fetchone()
    return row[0] if row else None


def fuzzy_candidates(conn, brand_id: int, limit: int = 200
                     ) -> list[ProductCandidate]:
    """Blocked candidate set: same brand only, never across brands."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.id, b.slug, p.model_name, p.canonical_name,
                      p.primary_mpn, p.colorway, p.gender
                 FROM product p JOIN brand b ON b.id = p.brand_id
                WHERE p.brand_id = %s
                ORDER BY p.updated_at DESC
                LIMIT %s""",
            (brand_id, limit))
        return [
            ProductCandidate(product_id=r[0], brand_slug=r[1], model_name=r[2],
                             canonical_name=r[3], primary_mpn=r[4],
                             colorway=r[5], gender=r[6],
                             identifiers={normalize_sku(r[4])} if r[4] else set())
            for r in cur.fetchall()
        ]


def create_product(conn, offer: RawOffer, brand_id: int,
                   mpn_norm: str) -> int:
    """Create a catalogue product from an offer that matched nothing.

    This is how the catalogue bootstraps: the first store to be crawled
    creates the products, and every later store matches into them on the
    article code. No manual data entry at any point.
    """
    from ..normalize import clean_model_name
    from ..taxonomy import classify

    with conn.cursor() as cur:
        cur.execute("SELECT name FROM brand WHERE id = %s", (brand_id,))
        brand_name = cur.fetchone()[0]

        # The shop's display name, so a "- Megasport" suffix can be stripped
        # from the title instead of becoming part of the product name.
        cur.execute("SELECT name FROM merchant WHERE slug = %s",
                    (offer.merchant_slug,))
        row = cur.fetchone()
        merchant_name = row[0] if row else None

        # Classify, and accept NULL when the title does not say. Defaulting to
        # 'sneakers' here is what filed a pack of socks as footwear.
        category_slug = classify(offer.raw_title, url=offer.product_url)
        category_id = None
        if category_slug:
            cur.execute("SELECT id FROM category WHERE slug = %s",
                        (category_slug,))
            row = cur.fetchone()
            category_id = row[0] if row else None

        model = clean_model_name(offer.raw_title, brand_name,
                                 mpn=offer.raw_mpn,
                                 merchant=merchant_name) or offer.raw_title
        # clean_model_name lowercases for comparison; the catalogue name is
        # read by people, so title-case it ("caven 2.0" -> "Caven 2.0").
        model = " ".join(w.capitalize() if w[:1].isalpha() else w
                         for w in model.split())
        model = model.strip()[:200] or mpn_norm
        canonical = f"{brand_name} {model}".strip()
        # The MPN keeps the slug unique across colourways of one silhouette.
        slug = f"{slugify(canonical)}-{slugify(mpn_norm)}"[:200]

        cur.execute(
            """INSERT INTO product (brand_id, category_id, model_name,
                                    canonical_name, primary_mpn, image_url, slug)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (slug) DO UPDATE SET updated_at = now()
                 RETURNING id""",
            (brand_id, category_id, model, canonical, mpn_norm,
             offer.image_url, slug))
        product_id = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO product_identifier (product_id, id_type, value_norm,
                                               source)
                    VALUES (%s, 'MPN', %s, %s)
               ON CONFLICT DO NOTHING""",
            (product_id, mpn_norm,
             offer.extractors.get("mpn", "unknown")))
    return product_id


# -----------------------------------------------------------------------------
# Matching one staged offer
# -----------------------------------------------------------------------------

def resolve_offer(conn, offer: RawOffer, merchant_id: int, *,
                  create_missing: bool = True,
                  report: PromotionReport | None = None
                  ) -> tuple[int | None, MatchResult]:
    learned = find_learned_merchant_sku(conn, merchant_id, offer.merchant_sku)
    if learned:
        return learned, MatchResult(learned, "merchant_sku", 1.0,
                                    {"source": "learned"})

    mpn_norm = normalize_sku(offer.raw_mpn)
    if mpn_norm:
        existing = find_product_by_mpn(conn, mpn_norm)
        if existing:
            return existing, MatchResult(existing, "mpn", 0.99,
                                         {"mpn": mpn_norm})

    brand_id = ensure_brand(conn, offer.raw_brand, offer.raw_title)

    # No identifier: try a blocked fuzzy match before giving up.
    if not mpn_norm:
        if brand_id is None:
            return None, MatchResult(None, "fuzzy", 0.0,
                                     {"reason": "brand unresolved"})
        result = match_offer(offer, fuzzy_candidates(conn, brand_id))
        if result.is_auto:
            return result.product_id, result
        if result.needs_review and result.product_id and report is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO match_candidate (offer_id, product_id, score,
                                                    features)
                       SELECT mo.id, %(pid)s, %(score)s, %(features)s
                         FROM merchant_offer mo
                        WHERE mo.merchant_id = %(merchant)s
                          AND mo.merchant_sku = %(sku)s
                       ON CONFLICT DO NOTHING""",
                    {"pid": result.product_id, "score": result.confidence,
                     "features": __import__("json").dumps(result.features),
                     "merchant": merchant_id, "sku": offer.merchant_sku})
            report.candidates_queued += 1
        return None, result

    # Has an MPN but no product yet: create one.
    if create_missing and brand_id is not None:
        product_id = create_product(conn, offer, brand_id, mpn_norm)
        if report is not None:
            report.products_created += 1
        return product_id, MatchResult(product_id, "mpn", 0.99,
                                       {"mpn": mpn_norm, "created": True})

    return None, MatchResult(None, "mpn", 0.0,
                             {"mpn": mpn_norm, "reason": "brand unresolved"})


# -----------------------------------------------------------------------------
# Upserting into the live tables
# -----------------------------------------------------------------------------

UPSERT_OFFER_SQL = """
INSERT INTO merchant_offer (merchant_id, product_id, merchant_sku, raw_mpn,
                            raw_title, raw_brand, product_url, image_url,
                            match_method, match_confidence, status, last_seen_at)
     VALUES (%(merchant)s, %(product)s, %(sku)s, %(mpn)s, %(title)s, %(brand)s,
             %(url)s, %(image)s, %(method)s, %(confidence)s, %(status)s, now())
ON CONFLICT (merchant_id, merchant_sku) DO UPDATE
        SET product_id       = COALESCE(EXCLUDED.product_id,
                                        merchant_offer.product_id),
            raw_mpn          = EXCLUDED.raw_mpn,
            raw_title        = EXCLUDED.raw_title,
            raw_brand        = EXCLUDED.raw_brand,
            product_url      = EXCLUDED.product_url,
            image_url        = COALESCE(EXCLUDED.image_url,
                                        merchant_offer.image_url),
            match_method     = EXCLUDED.match_method,
            match_confidence = EXCLUDED.match_confidence,
            status           = EXCLUDED.status,
            last_seen_at     = now()
  RETURNING id
"""

#: Postgres allows EXCLUDED in the DO UPDATE SET clause but **not** in
#: RETURNING, so "did anything move?" cannot be computed there. The `prior`
#: CTE reads the row as it was before the insert (all CTEs in one statement
#: share a snapshot) and the comparison is made against the bound parameters,
#: which hold the same values EXCLUDED would. On a fresh insert `prior` is
#: empty, the scalar subqueries yield NULL, and IS DISTINCT FROM makes that a
#: change -- which is right: the first observation is worth recording.
UPSERT_VARIANT_SQL = """
WITH prior AS (
    SELECT price_minor, in_stock, stock_qty
      FROM offer_variant
     WHERE offer_id = %(offer)s AND size_label = %(label)s
),
upserted AS (
    INSERT INTO offer_variant (
            offer_id, size_label, size_eu, size_uk, size_cm,
            merchant_variant_id, price_minor, list_price_minor, currency_code,
            shipping_cost_minor, in_stock, stock_qty,
            last_checked_at, last_changed_at)
         VALUES (%(offer)s, %(label)s, %(eu)s, %(uk)s, %(cm)s, %(vid)s,
                 %(price)s, %(list)s, %(currency)s, %(ship)s, %(in_stock)s,
                 %(qty)s, now(), now())
    ON CONFLICT (offer_id, size_label) DO UPDATE
            SET size_eu             = EXCLUDED.size_eu,
                size_uk             = EXCLUDED.size_uk,
                size_cm             = EXCLUDED.size_cm,
                merchant_variant_id = COALESCE(EXCLUDED.merchant_variant_id,
                                               offer_variant.merchant_variant_id),
                price_minor         = EXCLUDED.price_minor,
                list_price_minor    = EXCLUDED.list_price_minor,
                shipping_cost_minor = EXCLUDED.shipping_cost_minor,
                in_stock            = EXCLUDED.in_stock,
                stock_qty           = EXCLUDED.stock_qty,
                last_checked_at     = now(),
                last_changed_at     = CASE
                    WHEN offer_variant.price_minor IS DISTINCT FROM EXCLUDED.price_minor
                      OR offer_variant.in_stock    IS DISTINCT FROM EXCLUDED.in_stock
                      OR offer_variant.stock_qty   IS DISTINCT FROM EXCLUDED.stock_qty
                    THEN now() ELSE offer_variant.last_changed_at END,
                consecutive_unchanged = CASE
                    WHEN offer_variant.price_minor IS DISTINCT FROM EXCLUDED.price_minor
                      OR offer_variant.in_stock    IS DISTINCT FROM EXCLUDED.in_stock
                    THEN 0
                    ELSE least(offer_variant.consecutive_unchanged + 1, 32767)
                END
      RETURNING id
)
SELECT upserted.id,
       ((SELECT price_minor FROM prior) IS DISTINCT FROM %(price)s::bigint
     OR (SELECT in_stock    FROM prior) IS DISTINCT FROM %(in_stock)s::boolean
     OR (SELECT stock_qty   FROM prior) IS DISTINCT FROM %(qty)s::integer
       ) AS changed
  FROM upserted
"""

REFRESH_SUMMARY_SQL = """
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
       max(price_minor), max(currency_code),
       count(DISTINCT offer_id), count(DISTINCT merchant_id),
       count(*) FILTER (WHERE in_stock IS TRUE),
       coalesce(array_agg(DISTINCT size_eu)
                FILTER (WHERE size_eu IS NOT NULL AND in_stock IS NOT FALSE),
                '{}'),
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
"""


def refresh_summary(conn, product_id: int) -> None:
    """Rebuild the denormalised row the listing page reads.

    The listing page must never aggregate over ``offer_variant`` at request
    time -- that is ~1.2M rows at current scale and grows with every merchant.
    """
    with conn.cursor() as cur:
        cur.execute(REFRESH_SUMMARY_SQL, {"pid": product_id})


def promote_run(conn, run_id: int, merchant_id: int, merchant_slug: str, *,
                create_missing_products: bool = True,
                full_sweep: bool = False) -> PromotionReport:
    """Move a validated run's staged rows into the live catalogue.

    ``full_sweep`` must only be true when the run covered the merchant's
    entire catalogue. It delists offers that were not seen, which would be
    catastrophic after a partial run such as a single-category crawl or a
    stock probe.
    """
    report = PromotionReport()
    seen_skus: list[str] = []

    with conn.cursor() as cur:
        for offer in _staged_offers(conn, run_id, merchant_slug):
            seen_skus.append(offer.merchant_sku)
            product_id, result = resolve_offer(
                conn, offer, merchant_id,
                create_missing=create_missing_products, report=report)

            cur.execute(UPSERT_OFFER_SQL, {
                "merchant": merchant_id, "product": product_id,
                "sku": offer.merchant_sku, "mpn": offer.raw_mpn,
                "title": offer.raw_title[:500], "brand": offer.raw_brand,
                "url": offer.product_url, "image": offer.image_url,
                "method": result.method if product_id else None,
                "confidence": result.confidence if product_id else None,
                "status": "active" if product_id else "unmatched"})
            offer_id = cur.fetchone()[0]

            if product_id:
                report.offers_promoted += 1
                report.products_touched.add(product_id)

                # Backfill the catalogue image from whichever shop supplies
                # one. The product takes its image at creation time, so a
                # product first seen through a shop with no photo stayed
                # blank for good, even once three other shops listed it.
                # COALESCE means the first real image wins and later crawls
                # do not churn it.
                if offer.image_url:
                    cur.execute(
                        """UPDATE product
                              SET image_url = %s, updated_at = now()
                            WHERE id = %s AND image_url IS NULL""",
                        (offer.image_url, product_id))
                    if cur.rowcount:
                        report.images_backfilled += 1
            else:
                report.offers_unmatched += 1

            for variant in offer.variants:
                cur.execute(UPSERT_VARIANT_SQL, {
                    "offer": offer_id, "label": variant.size_label,
                    "eu": variant.size_eu, "uk": variant.size_uk,
                    "cm": variant.size_cm,
                    "vid": variant.merchant_variant_id,
                    "price": variant.price_minor,
                    "list": variant.list_price_minor,
                    "currency": variant.currency_code,
                    "ship": variant.shipping_cost_minor,
                    "in_stock": variant.in_stock, "qty": variant.stock_qty})
                variant_id, changed = cur.fetchone()
                report.variants_written += 1

                # Write-on-change: a fresh insert counts, an identical
                # re-crawl does not. This is the rule that keeps price_point
                # at ~2M rows a year instead of ~100M.
                if changed:
                    cur.execute(
                        """INSERT INTO price_point (offer_variant_id,
                                                    observed_at, price_minor,
                                                    in_stock, stock_qty)
                                VALUES (%s, now(), %s, %s, %s)""",
                        (variant_id, variant.price_minor, variant.in_stock,
                         variant.stock_qty))
                    report.price_points_written += 1

        if full_sweep and seen_skus:
            cur.execute(
                """UPDATE merchant_offer
                      SET status = 'delisted'
                    WHERE merchant_id = %s
                      AND status = 'active'
                      AND merchant_sku <> ALL(%s)
                  RETURNING product_id""",
                (merchant_id, seen_skus))
            delisted = cur.fetchall()
            report.offers_delisted = len(delisted)
            report.products_touched.update(
                pid for (pid,) in delisted if pid is not None)

    for product_id in report.products_touched:
        refresh_summary(conn, product_id)

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ingest_run
                  SET promoted_at = now(), offers_promoted = %s
                WHERE id = %s""",
            (report.offers_promoted, run_id))
    return report
