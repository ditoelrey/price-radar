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
from ..sizing import read_size
from ..taxonomy import APPAREL_SLUGS
from ..models import MatchResult, ProductCandidate, RawOffer, RawVariant
from ..normalize import normalize_sku, slugify, translit_mk


@dataclass(frozen=True)
class DelistCandidate:
    """An active offer this sweep did not see, and where to go and ask.

    Not a verdict. A shop that hides a product from category browse while
    keeping its page live and in stock produces exactly this, and retiring
    it on the listing's silence alone is unrecoverable: `enqueue_due`
    filters `status = 'active'`, so a delisted offer stops being probed
    too, and no later sweep walks a page it cannot find a link to.
    """

    offer_id: int
    merchant_sku: str
    product_url: str | None
    product_id: int | None


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
    #: Active offers the sweep did not see, awaiting a direct fetch.
    delist_candidates: list = field(default_factory=list)
    #: Candidates whose own page answered: still a listing, so still active.
    delist_kept: int = 0
    #: Candidates nobody confirmed either way -- no confirmer was supplied,
    #: or the shop was unreachable. Left active on purpose.
    delist_unchecked: int = 0


# -----------------------------------------------------------------------------
# Reading staged rows back out
# -----------------------------------------------------------------------------

STAGED_SQL = """
SELECT so.id, so.merchant_sku, so.raw_mpn, so.raw_title, so.raw_brand,
       so.product_url, so.image_url, so.currency_code, so.extractors,
       so.category_hint, so.gender_hint, so.category_path
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
             extractors, category_hint, gender_hint, category_path) in rows:
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
                extractors=extractors or {}, category_hint=category_hint,
                gender_hint=gender_hint, category_path=category_path)


# -----------------------------------------------------------------------------
# Brand and product resolution
# -----------------------------------------------------------------------------

#: Words that are never a brand on their own, whichever field a shop puts
#: them in. "Women" reached the brand table from one sizeer offer titled
#: "WOMEN MELODY cropped top", and from there matched the "for women" that
#: ends hundreds of fragrance titles.
#:
#: Narrow on purpose: only words that cannot be a brand by themselves. "New"
#: and "Sport" are NOT here, because New Era and Sport Ring are real brands
#: whose names begin with them -- that collision is fixed by preferring the
#: longest match, not by banning the word.
NOT_A_BRAND = frozenset({
    "women", "woman", "men", "man", "kids", "kid", "unisex", "uniseks",
    "boys", "girls", "her", "him", "female", "male", "ladies", "gents",
    "zhenski", "mashki", "deca", "decaci", "devojcica",
})

def resolve_brand(conn, raw_brand: str | None, title: str = "") -> int | None:
    """Resolve a shop's brand string to a catalogue brand.

    Checks the alias list, which is where the Cyrillic forms live -- MK shops
    and MK shoppers both write "Најк" and "Nike". Falls back to looking for a
    known brand token inside the product title, since several stores put the
    brand only there.
    """
    with conn.cursor() as cur:
        # A gender word is not a brand in any field. Blocked here as well as
        # in the title scan, because this is the branch that put "Women" to
        # work in the first place: sizeer sent it as the brand of a cropped
        # top, and once the row existed every "for women" title could find
        # it.
        if raw_brand and (raw_brand.strip().lower() in NOT_A_BRAND
                          or translit_mk(raw_brand).strip().lower()
                          in NOT_A_BRAND):
            raw_brand = None
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
            # The LONGEST matching token wins, not the first one the table
            # happens to return. Row order is arbitrary, and a short brand
            # name that is also a common word was quietly beating the real
            # one: 450 New Era products filed under a brand called "New",
            # 36 Sport Ring ones under "Sport", and 23 fragrances under
            # "Women" because their titles end "for women".
            #
            # A longer match is strictly more evidence -- it is the same
            # token plus more of it -- so there is no case where preferring
            # the shorter one is right.
            best: tuple[int, int] | None = None
            for brand_id, slug, name, aliases in cur.fetchall():
                for token in {slug, name, *(aliases or [])}:
                    token = translit_mk(str(token)).strip()
                    if len(token) < 3 or token.lower() in NOT_A_BRAND:
                        continue
                    if f" {token} " in hay and (best is None
                                                or len(token) > best[0]):
                        best = (len(token), brand_id)
            if best:
                return best[1]
    return None


#: A brand name we are willing to create on demand: up to five words of
#: letters, digits, apostrophes, hyphens, ampersands and exclamation marks.
#:
#: Narrow, because this only ever runs on a merchant's own brand *field* --
#: never on a token guessed out of a title, which would fill the table with
#: rubbish. But it was too narrow, and perfumery is what showed it: the first
#: Schatze crawl lost 70 offers to brands this pattern refused.
#:
#:     Joop!                    an exclamation mark
#:     Women’Secret            a curly apostrophe, not the straight one
#:     The Merchant of Venice   four words
#:     Van Cleef & Arpels       four words
#:
#: Sportswear brands are one or two words and plain ASCII; perfume houses are
#: neither. Three words and a straight quote was a rule written from the
#: catalogue we had rather than the one we were going to get.
_BRAND_NAME = re.compile(r"^[\w'’!&.-]+(?: [\w'’!&.-]+){0,4}$",
                         re.UNICODE)


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
    # A shop labelling its department as the brand must not mint one.
    if name.lower() in NOT_A_BRAND or translit_mk(name).lower() in NOT_A_BRAND:
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


def fragrance_identity(conn, offer: RawOffer,
                       brand_id: int | None) -> tuple[str, str | None] | None:
    """A fragrance's identity as words: its line name and its strength.

    Returns None for anything that is not a fragrance, or whose title names
    no fragrance at all -- there is nothing to key on then, and a product
    keyed on an empty line name would collect every unreadable title the
    shop has.

    The brand is passed in rather than read from the title again, because
    stripping it is half the job: Schatze writes "Pour Homme - edt" with
    Versace only in a Manufacturer field, e-elixir writes "Versace Pour
    Homme Eau de toilette", and both have to reduce to ("pour homme", EDT).
    """
    from ..fragrance import line_name, read_concentration
    from ..taxonomy import FRAGRANCE_SLUGS

    if offer.category_hint not in FRAGRANCE_SLUGS or brand_id is None:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM brand WHERE id = %s", (brand_id,))
        row = cur.fetchone()
    brand_name = row[0] if row else None

    line = line_name(offer.raw_title, brand_name)
    if not line:
        return None
    concentration, _ = read_concentration(offer.raw_title)
    return line, concentration


def genders_conflict(a: str | None, b: str | None) -> bool:
    """Whether two genders describe different articles.

    Only an explicit men-versus-women pair does. `unisex`, `kids` and NULL
    conflict with nothing, and that asymmetry is the whole point.

    **Why conflict and not equality.** Requiring the genders to match would
    split a fragrance the two shops shelve differently, and they will:
    e-elixir marks a bottle `unisex` when it appears in both its
    departments -- 218 of 690 -- while Schatze files most things under one.
    Requiring equality there would make two product pages out of one bottle
    for nearly a third of the catalogue.

    Ignoring gender entirely has the opposite failure, and it is worse: the
    Arabic houses sell one line in a men's and a women's version, and
    "Ajmal Amaze Eau de parfum for women" at 2 145 den is not "Ajmal Amaze
    Eau de parfum for men" at 3 065. Seven products merged that way, each
    quoting a shopper one bottle's price for a different bottle.

    Conflict refuses exactly those and nothing else.
    """
    return {a, b} == {"men", "women"}


def find_product_by_identity(conn, brand_id: int, model: str,
                             concentration: str | None,
                             gender: str | None = None) -> int | None:
    """The product this brand, line, strength and audience already name.

    `IS NOT DISTINCT FROM` on the concentration, not `=`: five live
    e-elixir products state no strength ("Giorgio Armani Code Elixir"), and
    SQL equality would make every one of them a new product on every crawl.
    The partial unique index cannot constrain those either -- NULL is never
    equal to NULL -- so this lookup is the only thing keeping them single.

    Gender is applied as a veto rather than a key, so a candidate is taken
    unless it conflicts outright. See :func:`genders_conflict`; it is also
    what keeps this lookup stable while `derive` revises a gender, which it
    may do on any later crawl.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, gender::text FROM product
                WHERE brand_id = %s
                  AND lower(model_name) = lower(%s)
                  AND concentration IS NOT DISTINCT FROM %s
                ORDER BY id""",
            (brand_id, model, concentration))
        rows = cur.fetchall()
    for product_id, candidate_gender in rows:
        if not genders_conflict(candidate_gender, gender):
            return product_id
    return None


def create_product(conn, offer: RawOffer, brand_id: int,
                   mpn_norm: str | None,
                   identity: tuple[str, str | None] | None = None) -> int:
    """Create a catalogue product from an offer that matched nothing.

    This is how the catalogue bootstraps: the first store to be crawled
    creates the products, and every later store matches into them on the
    article code. No manual data entry at any point.

    ``identity`` is the fragrance case, and it changes both the name and the
    slug. A shoe is named from its title and slugged with its article code,
    because two colourways of one silhouette share a name and must stay
    apart. A fragrance is the opposite: its identity IS brand, line and
    strength, and the two shops that sell it give it *different* internal
    codes -- e-elixir says "278", Schatze says 4976. Slugging by code would
    guarantee they never meet.
    """
    from ..derive import OfferEvidence, derive_category, derive_gender
    from ..normalize import clean_model_name

    with conn.cursor() as cur:
        cur.execute("SELECT name FROM brand WHERE id = %s", (brand_id,))
        brand_name = cur.fetchone()[0]

        # The shop's display name, so a "- Megasport" suffix can be stripped
        # from the title instead of becoming part of the product name.
        cur.execute("SELECT name FROM merchant WHERE slug = %s",
                    (offer.merchant_slug,))
        row = cur.fetchone()
        merchant_name = row[0] if row else None

        # Creation and re-derivation read the same evidence through the same
        # functions, so they cannot drift. That drift was the bug: this
        # function used to stamp a category once and no later sweep could
        # revise it, which left 2,767 products in the generic footwear bucket
        # and made the uncategorised count unfixable by re-crawling.
        #
        # Only this one offer exists yet -- the product is being created from
        # it -- so a single-offer derivation is all there is to do here. When
        # the second shop's offer arrives, `mkagg.derive.rederive` sees both.
        evidence = [OfferEvidence(
            merchant_slug=offer.merchant_slug,
            merchant_category_path=None,
            merchant_gender=offer.gender_hint,
            raw_title=offer.raw_title,
            product_url=offer.product_url)]
        category_slug, category_source = derive_category(evidence)
        # The staged hint is facet evidence that has not reached
        # merchant_offer yet, so it is applied here rather than thrown away.
        if category_slug is None and offer.category_hint:
            category_slug, category_source = offer.category_hint, "facet"
        gender, gender_source = derive_gender(evidence)

        category_id = None
        if category_slug:
            cur.execute("SELECT id FROM category WHERE slug = %s",
                        (category_slug,))
            row = cur.fetchone()
            category_id = row[0] if row else None
        if category_id is None:
            category_source = None

        concentration = None
        if identity is not None:
            model, concentration = identity
            # Title-cased for a human reader, same as the shoe path.
            model = " ".join(w.capitalize() if w[:1].isalpha() else w
                             for w in model.split()).strip()[:200]
            # The strength belongs in the displayed name. "Valentino Donna"
            # alone would appear twice in a listing -- once as the Eau de
            # Parfum and once as the Eau de Toilette, at different prices
            # and with nothing on screen to tell them apart.
            canonical = " ".join(
                x for x in (brand_name, model, concentration) if x).strip()
            # No code in the slug: brand, line and strength ARE the
            # identity, so this is the string both shops must agree on.
            #
            # The audience is appended, though, and it has to be. One line
            # sold to two audiences is two products -- Ajmal Amaze for women
            # and for men -- and they would otherwise compete for the single
            # slug `ajmal-amaze-edp`. `ON CONFLICT (slug)` would then hand
            # the second one the first one's id and silently merge them,
            # which is exactly the wrong merge the audience veto exists to
            # prevent: the veto refuses the match and then the slug undoes
            # the refusal.
            #
            # Unconditionally rather than only on collision, so the slug a
            # product gets does not depend on which shop was crawled first.
            slug = slugify(" ".join(x for x in (canonical, gender) if x))[:200]
        else:
            model = clean_model_name(offer.raw_title, brand_name,
                                     mpn=offer.raw_mpn,
                                     merchant=merchant_name) or offer.raw_title
            # clean_model_name lowercases for comparison; the catalogue name
            # is read by people, so title-case it ("caven 2.0" -> "Caven 2.0").
            model = " ".join(w.capitalize() if w[:1].isalpha() else w
                             for w in model.split())
            model = model.strip()[:200] or mpn_norm
            canonical = f"{brand_name} {model}".strip()
            # The MPN keeps the slug unique across colourways of one
            # silhouette.
            slug = f"{slugify(canonical)}-{slugify(mpn_norm)}"[:200]

        cur.execute(
            """INSERT INTO product (brand_id, category_id, category_source,
                                    gender, gender_source, model_name,
                                    canonical_name, primary_mpn, image_url,
                                    slug, concentration)
                    VALUES (%s, %s, %s, %s::gender_t, %s, %s, %s, %s, %s, %s,
                            %s)
               ON CONFLICT (slug) DO UPDATE SET updated_at = now()
                 RETURNING id""",
            (brand_id, category_id, category_source, gender, gender_source,
             model, canonical, mpn_norm, offer.image_url, slug,
             concentration))
        product_id = cur.fetchone()[0]

        # An identifier only when the code can carry one. A fragrance's
        # parent sku is the shop's own row number -- e-elixir sends "278",
        # "160", "1319" -- and filing that as an MPN would let any other
        # shop's row 278 match this perfume. Identity is what joins
        # fragrances; a short internal code joins nothing and risks
        # everything.
        identifier_ok = bool(mpn_norm) and (identity is None
                                            or len(mpn_norm) >= 8)
        if identifier_ok:
            cur.execute(
                """INSERT INTO product_identifier (product_id, id_type,
                                                   value_norm, source)
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

    # -- Fragrances: identity is words, not a code -----------------------
    # Every other vertical here is matched on a manufacturer code that both
    # shops print. The two perfumeries print different ones -- an internal
    # row number each -- so a fragrance is joined on what it IS: brand, line
    # and strength, matched exactly.
    #
    # Exactly, and never fuzzily. These shops stock "Born in Roma", "Born in
    # Roma Intense", "Born in Roma Extradose" and "Born in Roma Ruby" side
    # by side at four prices, and a similarity score cannot be trusted to
    # keep them apart. A near miss here quotes a shopper a price for a
    # bottle they cannot buy.
    #
    # This also rescues the offers no code could reach: 13 live e-elixir
    # fragrances carry no sku at all, and under the code-only path they
    # stayed attached to no product.
    from ..taxonomy import FRAGRANCE_SLUGS
    if offer.category_hint in FRAGRANCE_SLUGS:
        identity = fragrance_identity(conn, offer, brand_id)
        if identity is None:
            # A fragrance whose title names no fragrance, or whose brand we
            # cannot place. The code path below would still mint a product
            # -- named from the raw title and slugged with the shop's row
            # number -- and that product would be unfindable, uncomparable
            # and permanent. An unmatched offer is recoverable; a junk
            # product in the catalogue is not.
            return None, MatchResult(None, "identity", 0.0,
                                     {"reason": "no readable identity"})
        model, concentration = identity
        # The audience, read the same way `mkagg.fragrance` reads it for the
        # catalogue: an explicit "for men" in the title overrides the shelf,
        # because 2 of 672 Schatze products sit on the wrong one.
        from ..fragrance import read_gender
        audience = (read_gender(offer.category_path, offer.raw_title)
                    or offer.gender_hint)
        existing = find_product_by_identity(conn, brand_id, model,
                                            concentration, audience)
        if existing:
            return existing, MatchResult(existing, "identity", 0.99,
                                         {"line": model,
                                          "concentration": concentration})
        if create_missing:
            product_id = create_product(conn, offer, brand_id, mpn_norm,
                                        identity=identity)
            if report is not None:
                report.products_created += 1
            return product_id, MatchResult(product_id, "identity", 0.99,
                                           {"line": model,
                                            "concentration": concentration,
                                            "created": True})
        return None, MatchResult(None, "identity", 0.0,
                                 {"reason": "creation disabled"})

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
                            merchant_category_path,
                            match_method, match_confidence, status, last_seen_at)
     VALUES (%(merchant)s, %(product)s, %(sku)s, %(mpn)s, %(title)s, %(brand)s,
             %(url)s, %(image)s, %(category_path)s,
             %(method)s, %(confidence)s, %(status)s, now())
ON CONFLICT (merchant_id, merchant_sku) DO UPDATE
        SET product_id       = COALESCE(EXCLUDED.product_id,
                                        merchant_offer.product_id),
            -- The page's own shelf, when it states one. COALESCE and not
            -- assignment: adapters that read no shelf send NULL, and a NULL
            -- must never wipe what the facet walk wrote.
            merchant_category_path = COALESCE(
                                        EXCLUDED.merchant_category_path,
                                        merchant_offer.merchant_category_path),
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
            size_system, size_alpha, size_alpha_max, size_height_cm,
            size_age_min_months, size_age_max_months, size_ml,
            merchant_variant_id, price_minor, list_price_minor, currency_code,
            shipping_cost_minor, in_stock, stock_qty,
            last_checked_at, last_changed_at)
         VALUES (%(offer)s, %(label)s, %(eu)s, %(uk)s, %(cm)s,
                 %(system)s::size_system, %(alpha)s, %(alpha_max)s,
                 %(height)s,
                 %(age_lo)s, %(age_hi)s, %(ml)s, %(vid)s,
                 %(price)s, %(list)s, %(currency)s, %(ship)s, %(in_stock)s,
                 %(qty)s, now(), now())
    ON CONFLICT (offer_id, size_label) DO UPDATE
            SET size_eu             = EXCLUDED.size_eu,
                size_uk             = EXCLUDED.size_uk,
                size_cm             = EXCLUDED.size_cm,
                size_system         = EXCLUDED.size_system,
                size_alpha          = EXCLUDED.size_alpha,
                size_alpha_max      = EXCLUDED.size_alpha_max,
                size_height_cm      = EXCLUDED.size_height_cm,
                size_age_min_months = EXCLUDED.size_age_min_months,
                size_age_max_months = EXCLUDED.size_age_max_months,
                size_ml             = EXCLUDED.size_ml,
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
      JOIN merchant m        ON m.id = mo.merchant_id
     -- m.is_active matters as much as mo.status, and leaving it out was a
     -- real bug. Deactivating dsport (its edge blocks our crawler) left its
     -- products advertising "from 8 599 ден." on the listing while the
     -- serving query -- which does filter m.is_active -- returned no offers
     -- at all. The site was quoting a price nobody could buy, which is the
     -- one failure this whole project exists to prevent.
     WHERE mo.product_id = %(pid)s
       AND mo.status = 'active'
       AND m.is_active
)
INSERT INTO product_price_summary (
        product_id, country_code, min_price_minor, min_price_variant_id,
        max_price_minor, currency_code, offer_count, merchant_count,
        in_stock_offer_count, available_sizes_eu, available_sizes_alpha,
        available_volumes_ml, max_discount_pct, updated_at)
SELECT %(pid)s, 'MK',
       min(price_minor),
       (SELECT id FROM v ORDER BY price_minor LIMIT 1),
       max(price_minor), max(currency_code),
       count(DISTINCT offer_id), count(DISTINCT merchant_id),
       count(*) FILTER (WHERE in_stock IS TRUE),
       coalesce(array_agg(DISTINCT size_eu)
                FILTER (WHERE size_eu IS NOT NULL AND in_stock IS NOT FALSE),
                '{}'),
       -- The same thing for garments, which have no EU number at all. Built
       -- in a subquery rather than with a FILTER: the array has to come out
       -- in ladder order (XXS, XS, S ... 5XL), and DISTINCT inside
       -- array_agg will only order by the expression it is de-duplicating.
       -- A label naming two sizes contributes both, so "M/L" answers a
       -- shopper filtering M and one filtering L. `alpha_size_span` is the
       -- ladder walk; it returns just the one letter when there is no span.
       coalesce((SELECT array_agg(a ORDER BY alpha_size_rank(a), a)
                   FROM (SELECT DISTINCT unnest(
                                    alpha_size_span(size_alpha,
                                                    size_alpha_max)) AS a
                           FROM v
                          WHERE size_alpha IS NOT NULL
                            AND in_stock IS NOT FALSE) t), '{}'),
       -- And the third rail, for bottles. A FILTER is enough here where the
       -- letters needed a subquery: DISTINCT inside array_agg orders by the
       -- expression it de-duplicates, and for millilitres that is already
       -- the order a shopper reads -- 30, 50, 100.
       coalesce(array_agg(DISTINCT size_ml)
                FILTER (WHERE size_ml IS NOT NULL AND in_stock IS NOT FALSE),
                '{}'),
       -- The best saving any shop advertises on this product, so the listing
       -- can sort by discount without joining the variants. A maximum, not an
       -- average: a shopper asking "where is this most reduced" is asking
       -- about one shop's offer. NULL when nobody is discounting it, which is
       -- not the same as zero -- zero would claim a shop advertised a saving
       -- of nothing.
       --
       -- No percent sign anywhere in this string: psycopg reads one as a
       -- placeholder and refuses the whole statement, which is how this
       -- comment broke every database test the first time it was written.
       (SELECT max(round(100.0 * (list_price_minor - price_minor)
                               / list_price_minor))::smallint
          FROM v
         WHERE price_minor IS NOT NULL
           AND list_price_minor IS NOT NULL
           AND list_price_minor > price_minor
           AND round(100.0 * (list_price_minor - price_minor)
                           / list_price_minor) BETWEEN 1 AND 99),
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
        available_sizes_alpha = EXCLUDED.available_sizes_alpha,
        available_volumes_ml = EXCLUDED.available_volumes_ml,
        max_discount_pct     = EXCLUDED.max_discount_pct,
        updated_at           = now()
"""


def refresh_summary(conn, product_id: int) -> None:
    """Rebuild the denormalised row the listing page reads.

    The listing page must never aggregate over ``offer_variant`` at request
    time -- that is ~1.2M rows at current scale and grows with every merchant.
    """
    with conn.cursor() as cur:
        cur.execute(REFRESH_SUMMARY_SQL, {"pid": product_id})


#: Mirrors load.run.APPAREL_KIND. Named locally because run.py imports this
#: module, so importing the constant back would close the cycle; a test
#: asserts the two never drift apart.
APPAREL_RUN_KIND = "apparel_parse"
ACCESSORY_RUN_KIND = "accessory_parse"
FRAGRANCE_RUN_KIND = "fragrance_parse"

#: Which category kind a run may retire. The whole point of keeping the run
#: kinds apart: a complete equipment sweep must not be able to touch a shoe.
_RUN_KIND_VERTICAL = {
    APPAREL_RUN_KIND: "apparel",
    ACCESSORY_RUN_KIND: "accessory",
    FRAGRANCE_RUN_KIND: "fragrance",
}


def promote_run(conn, run_id: int, merchant_id: int, merchant_slug: str, *,
                create_missing_products: bool = True,
                full_sweep: bool = False,
                kind: str = "catalog_parse") -> PromotionReport:
    """Move a validated run's staged rows into the live catalogue.

    ``full_sweep`` must only be true when the run covered everything this
    merchant sells *in this vertical*. It delists the offers that were not
    seen, which would be catastrophic after a partial run such as a
    single-category crawl or a stock probe.

    ``kind`` is what makes that promise keepable now that a merchant can
    have two verticals. Delisting used to be scoped to the merchant alone,
    so a complete footwear sweep would have retired every apparel offer the
    shop has -- a correct run quietly destroying a correct catalogue. The
    offers considered are now only those whose own category sits in the
    same vertical as the run.

    Promotion no longer retires anything itself. It collects
    :class:`DelistCandidate` rows into the report, and a caller that can
    reach the network decides -- see :func:`apply_delistings`. Confirming a
    candidate means fetching its page, and this is a single short
    transaction that must not be held open across the network.
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
                "category_path": offer.category_path,
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

            # The facet is what makes a number readable. An offer found in
            # an apparel department has clothing sizes, and "38" there is a
            # dress size however much it looks like a shoe size; one found
            # in a kids' department writes "7" and means seven years old.
            # Both facts are already on the offer, carried from discovery.
            apparel = offer.category_hint in APPAREL_SLUGS
            kids = offer.gender_hint == "kids"

            for variant in offer.variants:
                size = read_size(variant.size_label, apparel=apparel,
                                 kids=kids)
                cur.execute(UPSERT_VARIANT_SQL, {
                    "offer": offer_id, "label": variant.size_label,
                    # An apparel offer has no shoe size, whatever the number
                    # looks like. The adapter cannot know -- it sees "38" and
                    # a bound that 38 passes -- so the claim is dropped here,
                    # where the facet is known. Without this the 176 rows
                    # V18 repaired would come straight back on the next run.
                    "eu": None if apparel else variant.size_eu,
                    "uk": None if apparel else variant.size_uk,
                    "cm": None if apparel else variant.size_cm,
                    "system": size.system, "alpha": size.alpha,
                    "alpha_max": size.alpha_max,
                    "height": size.height_cm or variant.size_height_cm,
                    "age_lo": size.age_min_months,
                    "age_hi": size.age_max_months,
                    "ml": size.volume_ml,
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
                #
                # A variant with no price is skipped entirely. price_point is
                # the price history, and "this shop published no price" is not
                # an observation of a price -- writing a row for it would put
                # a hole in the series that every later chart and trend has to
                # special-case. The variant itself still records the sold-out
                # state, which is where that fact belongs.
                if changed and variant.price_minor is not None:
                    cur.execute(
                        """INSERT INTO price_point (offer_variant_id,
                                                    observed_at, price_minor,
                                                    in_stock, stock_qty)
                                VALUES (%s, now(), %s, %s, %s)""",
                        (variant_id, variant.price_minor, variant.in_stock,
                         variant.stock_qty))
                    report.price_points_written += 1

        if full_sweep and seen_skus:
            # The run's own vertical, named explicitly. "Everything that is
            # not apparel" was the first attempt and it was wrong: there are
            # four kinds, and accessories and equipment belong to neither
            # sweep. megasport carries 80 accessory and 13 equipment offers
            # that its footwear facets never visit, so a footwear full sweep
            # would have retired all 93 of them as "not seen" -- and nothing
            # would ever have brought them back, because no sweep walks
            # those trees.
            #
            # A product with no category is excluded by the inner join, and
            # that is deliberate too: 203 products are unclassified, most of
            # them shoes, and delisting on an absence of evidence is how a
            # live offer disappears for a reason nobody can reconstruct.
            vertical_kind = _RUN_KIND_VERTICAL.get(kind, "footwear")
            cur.execute(
                """SELECT mo.id, mo.merchant_sku, mo.product_url,
                          mo.product_id
                     FROM merchant_offer mo
                     JOIN product p ON p.id = mo.product_id
                     JOIN category c ON c.id = p.category_id
                    WHERE mo.merchant_id = %s
                      AND mo.status = 'active'
                      AND mo.merchant_sku <> ALL(%s)
                      AND c.kind::text = %s
                    ORDER BY mo.id""",
                (merchant_id, seen_skus, vertical_kind))
            report.delist_candidates = [
                DelistCandidate(offer_id=row[0], merchant_sku=row[1],
                                product_url=row[2], product_id=row[3])
                for row in cur.fetchall()]

    for product_id in report.products_touched:
        refresh_summary(conn, product_id)

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ingest_run
                  SET promoted_at = now(), offers_promoted = %s
                WHERE id = %s""",
            (report.offers_promoted, run_id))
    return report


def apply_delistings(conn, confirmed) -> int:
    """Retire the candidates a direct fetch proved are gone.

    Separate from promotion for two reasons. Confirming means going to the
    network, which promotion's one short transaction must not wait on; and
    the decision belongs to whoever can fetch, not to the loader, which
    only has a database handle.

    Takes the confirmed subset, never the candidate list: passing the whole
    list back is how "we could not reach the shop" would turn into "the
    shop removed everything".
    """
    ids = [c.offer_id for c in confirmed]
    if not ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE merchant_offer SET status = 'delisted'
                WHERE id = ANY(%s) AND status = 'active'
             RETURNING product_id""", (ids,))
        rows = cur.fetchall()
    for product_id in {pid for (pid,) in rows if pid is not None}:
        refresh_summary(conn, product_id)
    return len(rows)
