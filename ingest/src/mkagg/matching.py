"""Offer -> product matching.

Order matters, and the cheap exact paths come first because recon proved they
carry the load: **all seven MK stores expose the manufacturer code**, so the
fuzzy stage is a long-tail fallback rather than the engine.

=========================  ==========  ============================================
stage                      confidence  notes
=========================  ==========  ============================================
GTIN-13 (checksum valid)   1.00        strongest signal; none of the MK stores
                                       publish it yet, kept for feeds later
MERCHANT_SKU (learned)     1.00        written by a human decision; never re-scored
MPN exact                  0.99        the workhorse: "392290-02", "M20325"
MPN base (colourway drop)  0.80        same silhouette, different colour -> review
fuzzy brand+name+price     0.00-0.95   blocked by brand+gender; needs review
=========================  ==========  ============================================

Thresholds: ``>= 0.92`` links automatically, ``[0.75, 0.92)`` goes to the
``match_candidate`` review queue, below that is rejected and the offer stays
unmatched (kept, not discarded -- it often matches once another store reveals
the SKU).
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, Sequence

from .models import MatchResult, ProductCandidate, RawOffer
from .normalize import clean_model_name, normalize_sku, sku_base

AUTO_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.75

# Price sanity band. An offer 5x cheaper than the catalogue consensus is
# usually a different article (a kids' size, a single sock, an accessory),
# so price proximity is a *guard*, never a positive signal on its own.
PRICE_TOLERANCE = 0.25


# -----------------------------------------------------------------------------
# String similarity
# -----------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def token_set_ratio(a: str, b: str) -> float:
    """Order-insensitive similarity, mirroring rapidfuzz's token_set_ratio.

    Implemented on stdlib ``difflib`` so the scaffold runs with zero
    dependencies. Swap in ``rapidfuzz.fuzz.token_set_ratio`` for production --
    it is the same metric, roughly 50x faster, and the thresholds carry over.
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = sorted(ta & tb)
    s_inter = " ".join(inter)
    s_a = " ".join(inter + sorted(ta - tb)).strip()
    s_b = " ".join(inter + sorted(tb - ta)).strip()
    if not s_inter:
        return _ratio(s_a, s_b)
    return max(_ratio(s_inter, s_a), _ratio(s_inter, s_b), _ratio(s_a, s_b))


def gtin13_is_valid(value: str) -> bool:
    """EAN-13 checksum. Guards against treating a random 13-digit id as a GTIN."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 13:
        return False
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == digits[12]


# -----------------------------------------------------------------------------
# The matcher
# -----------------------------------------------------------------------------

def match_offer(offer: RawOffer,
                candidates: Iterable[ProductCandidate],
                *, known_merchant_skus: dict[str, int] | None = None,
                catalog_price_minor: dict[int, int] | None = None
                ) -> MatchResult:
    """Resolve one scraped offer to a catalogue product.

    ``known_merchant_skus`` maps a normalised merchant SKU to a product id and
    represents past human decisions -- checked first so a confirmed pair is
    never scored again. ``catalog_price_minor`` supplies the known price per
    product for the sanity guard.
    """
    candidates = list(candidates)

    # 1. A learned merchant SKU wins outright.
    if known_merchant_skus:
        key = normalize_sku(offer.merchant_sku)
        if key and key in known_merchant_skus:
            return MatchResult(known_merchant_skus[key], "merchant_sku", 1.0,
                               {"source": "learned"})

    offer_mpn = normalize_sku(offer.raw_mpn)

    # 2. GTIN-13, when a feed ever gives us one.
    if offer_mpn and gtin13_is_valid(offer_mpn):
        for cand in candidates:
            if offer_mpn in cand.identifiers:
                return MatchResult(cand.product_id, "gtin", 1.0,
                                   {"gtin": offer_mpn})

    # 3. MPN exact -- the workhorse.
    if offer_mpn:
        for cand in candidates:
            if offer_mpn in cand.identifiers or \
                    (cand.primary_mpn and normalize_sku(cand.primary_mpn) == offer_mpn):
                return MatchResult(cand.product_id, "mpn", 0.99,
                                   {"mpn": offer_mpn})

        # 4. Same silhouette, different colourway. Deliberately below the auto
        # threshold: "DH2987-001" and "DH2987-100" are genuinely not the same
        # product to a shopper comparing prices.
        base = sku_base(offer_mpn)
        if base:
            for cand in candidates:
                cand_base = sku_base(cand.primary_mpn) if cand.primary_mpn else None
                if cand_base and cand_base == base:
                    return MatchResult(cand.product_id, "mpn", 0.80,
                                       {"mpn_base": base, "note": "colourway differs"})

    # 5. Fuzzy fallback, blocked by brand (+gender where both sides declare it).
    best, best_score, best_features = None, 0.0, {}
    # Pass the MPN too: a shop that prefixes its titles with the article
    # code would otherwise have that code dominate the similarity score.
    offer_name = clean_model_name(offer.raw_title, offer.raw_brand,
                                  mpn=offer.raw_mpn)
    offer_price = offer.min_price_minor

    for cand in candidates:
        if offer.raw_brand and cand.brand_slug:
            if not _same_brand(offer.raw_brand, cand.brand_slug):
                continue

        name_score = token_set_ratio(
            offer_name, clean_model_name(cand.canonical_name, cand.brand_slug))

        features: dict = {"name": round(name_score, 3)}
        weighted, weight_total = name_score * 0.55, 0.55

        if cand.colorway and offer.raw_title:
            colour = token_set_ratio(clean_model_name(cand.colorway),
                                     clean_model_name(offer.raw_title))
            features["colour"] = round(colour, 3)
            weighted += colour * 0.25
            weight_total += 0.25

        if offer_price and catalog_price_minor and cand.product_id in catalog_price_minor:
            known = catalog_price_minor[cand.product_id]
            if known:
                delta = abs(offer_price - known) / known
                proximity = max(0.0, 1.0 - delta / PRICE_TOLERANCE)
                features["price_proximity"] = round(proximity, 3)
                weighted += proximity * 0.20
                weight_total += 0.20

        score = weighted / weight_total if weight_total else 0.0
        if score > best_score:
            best, best_score, best_features = cand, score, features

    if best is None:
        return MatchResult(None, "fuzzy", 0.0, {"reason": "no candidate in block"})

    # Never let fuzzy reach the auto-link threshold on its own: a wrong
    # auto-match merges two different shoes into one product page, which is
    # much harder to notice and to undo than an unmatched offer.
    confidence = min(best_score, 0.91)
    return MatchResult(
        best.product_id if confidence >= REVIEW_THRESHOLD else None,
        "fuzzy", round(confidence, 3), best_features)


def _same_brand(raw_brand: str, brand_slug: str) -> bool:
    a = normalize_sku(raw_brand) or ""
    b = normalize_sku(brand_slug) or ""
    return bool(a and b) and (a == b or a in b or b in a)


def group_by_mpn(offers: Sequence[RawOffer]) -> dict[str, list[RawOffer]]:
    """Group offers that share a normalised MPN.

    This is how a cold-start catalogue is built: run it over every store's
    first crawl and each group with two or more merchants is a unified product
    with a real price comparison, created with zero manual work.
    """
    groups: dict[str, list[RawOffer]] = {}
    for offer in offers:
        key = normalize_sku(offer.raw_mpn)
        if key:
            groups.setdefault(key, []).append(offer)
    return groups
