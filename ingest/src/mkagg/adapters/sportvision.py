"""Sport Vision group adapter: sportvision.mk, sportreality.mk, buzzsneakers.mk.

One codebase, three merchants, one OVH host. Verified in recon:

* ``<script type="application/ld+json">`` carries a Product node whose ``sku``
  is the **manufacturer** code and whose ``productID`` is the store's own id.
  Confirmed identical SKU ``392290-02`` for the Puma Caven 2.0 on both
  sportvision.mk and sportreality.mk, at the same price (2 863,00 MKD).
* buzzsneakers.mk ships that same block with HTML comment markers leaking into
  it, so its JSON-LD does not parse -- hence the rescue path.
* Per-size stock sits in ``<li data-productsize-combid="...">`` inside
  ``.product-size-tabs-new``. The CSS class ``disabled`` means **sold out**,
  and ``data-productsize-combid`` is a stable per-size variant id.

This is the only one of the four adapters with no price-only endpoint, so its
stock probe has to re-fetch the product page.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, normalize_sku, parse_price_minor
from .base import (Adapter, as_text, datalayer_product_codes, jsonld_product,
                   ld_image, ld_offer, ld_text, og_image, register,
                   rescue_field)

_SIZE_CONTAINER = "product-size-tabs-new"
# The product's own size run lives in exactly one <ul class="product-attributes
# ...">. Bounding extraction to that element's closing </ul> is essential:
# a fixed byte window either truncates the run (sportvision ships 23 size <li>
# spanning ~20.6 KB) or bleeds into the recommendation tiles further down the
# page, which carry size widgets of their own (160+ combids on sportreality).
_SIZE_UL = re.compile(r'<ul[^>]*class="[^"]*product-attributes[^"]*"[^>]*>', re.I)
_SIZE_LI = re.compile(
    r'<li([^>]*?data-productsize-combid="(\d+)"[^>]*?)>(.*?)</li>', re.S)
_EUR_SIZE = re.compile(r'class="eur-size"[^>]*>([^<]*)', re.I)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_OG_TITLE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)
_TAGS = re.compile(r"<[^>]+>")
_CM_SIZE = re.compile(r'class="cm-size"[^>]*>([^<]*)', re.I)
_ORIG_SIZE = re.compile(r'class="original-size"[^>]*>([^<]*)', re.I)
# /mk/patiki/8550245-puma-caven-2-0  ->  8550245
_URL_ID = re.compile(r"/(\d{3,12})-[^/]+/?$")


def _page_title(html: str) -> str | None:
    """The product's own title, from the page rather than from JSON-LD.

    Prefers ``<h1>``; falls back to ``og:title``, stripping the
    " | Buzz - Online Shop" style site suffix these themes append.
    """
    m = _H1.search(html)
    if m:
        text = re.sub(r"\s+", " ", _TAGS.sub(" ", m.group(1))).strip()
        if text:
            return text
    m = _OG_TITLE.search(html)
    if m:
        text = m.group(1).split("|")[0].strip()
        if text:
            return text
    return None


class SportVisionAdapter(Adapter):
    slug = "sportvision"
    is_api = False

    def parse_product(self, payload, url, merchant_slug) -> RawOffer | None:
        html = as_text(payload)
        extractors: dict[str, str] = {}

        node = jsonld_product(html)
        if node:
            offer = ld_offer(node)
            title = ld_text(node.get("name"))
            mpn = ld_text(node.get("sku")) or ld_text(node.get("mpn"))
            brand = ld_text(node.get("brand"))
            store_id = ld_text(node.get("productID"))
            price_raw = offer.get("price")
            currency = ld_text(offer.get("priceCurrency")) or "MKD"
            # `image` is a LIST of URLs on this platform, which a scalar
            # text helper silently dropped.
            image = ld_image(node) or og_image(html)
            for key in ("title", "mpn", "price"):
                extractors[key] = "jsonld"
        else:
            # buzzsneakers.mk lands here: broken JSON-LD, rescue by regex.
            # Deliberately NOT rescuing "name": the first "name" in the
            # document is the Organization's, so that path produced the
            # product title "Buzz - Online Shop". The <h1> is the real one.
            title = _page_title(html)
            mpn = rescue_field(html, "sku") or rescue_field(html, "mpn")
            brand = rescue_field(html, "brand")
            store_id = rescue_field(html, "productID")
            price_raw = rescue_field(html, "price")
            currency = rescue_field(html, "priceCurrency") or "MKD"
            # buzz ships no parseable JSON-LD at all; og:image is a real
            # product photo there, not the site logo.
            image = og_image(html)
            for key in ("mpn", "price"):
                extractors[key] = "regex"
            extractors["title"] = "css"

        # The store's own listing id: JSON-LD productID, else the URL segment.
        if not store_id:
            m = _URL_ID.search(url.split("?")[0])
            store_id = m.group(1) if m else None
            if store_id:
                extractors["merchant_sku"] = "url"

        # Last resort for the MPN: the dataLayer productCode list. Only usable
        # when the page offers exactly one code, otherwise we would be picking
        # a recommendation tile's product at random.
        if not mpn:
            codes = datalayer_product_codes(html)
            if len(codes) == 1:
                mpn = codes[0]
                extractors["mpn"] = "datalayer"

        if not store_id or not title:
            return None

        price_minor = parse_price_minor(price_raw, minor_unit=0)
        variants = self._parse_sizes(html, price_minor, currency)
        if variants:
            extractors["sizes"] = "css"

        # One-size / no size block: still emit a single priced row so the
        # offer is comparable, flagged with an empty label.
        if not variants and price_minor is not None:
            variants = [RawVariant(size_label="", price_minor=price_minor,
                                   currency_code=currency, in_stock=None)]

        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=str(store_id),
            raw_title=title,
            product_url=url,
            raw_mpn=mpn,
            raw_brand=brand,
            image_url=image,
            currency_code=currency,
            variants=variants,
            extractors=extractors,
        )

    @staticmethod
    def _parse_sizes(html: str, price_minor: int | None,
                     currency: str) -> list[RawVariant]:
        """Read the size grid, bounded by the size list's own ``</ul>``.

        Regex rather than a DOM parser on purpose: the target is a flat run of
        sibling ``<li>`` elements inside one known container, which recon
        verified against all three stores. The ``<li>`` items contain no
        nested lists, so the first ``</ul>`` after the opening tag is the
        correct terminator. Swapping in selectolax here is a drop-in change if
        the markup ever gains nesting.
        """
        anchor = html.find(_SIZE_CONTAINER)
        if anchor < 0:
            return []

        opening = _SIZE_UL.search(html, anchor)
        if not opening:
            # No size list on this page (one-size article, or markup changed).
            # Return nothing rather than guess: a wrong size run sends a
            # shopper to buy a size the shop does not have.
            return []
        closing = html.find("</ul>", opening.end())
        block = html[opening.end():closing if closing != -1 else len(html)]
        block = re.sub(r">\s+<", "><", block)

        variants: list[RawVariant] = []
        seen: set[str] = set()
        for attrs, combid, inner in _SIZE_LI.findall(block):
            eu = _EUR_SIZE.search(inner)
            orig = _ORIG_SIZE.search(inner)
            cm = _CM_SIZE.search(inner)

            label = (eu.group(1) if eu else (orig.group(1) if orig else "")).strip()
            if not label:
                continue
            # sportvision.mk lists the same physical size twice, once as
            # "35,5" and once as "35.5", with different combids. Deduplicate
            # on the NORMALISED number, not the label, or both survive and the
            # size filter shows 35.5 twice.
            size_eu = normalize_size(label)
            key = str(size_eu) if size_eu is not None else label
            if key in seen:
                continue
            seen.add(key)

            cm_val = None
            if cm and cm.group(1).strip():
                try:
                    cm_val = Decimal(cm.group(1).strip().replace(",", "."))
                except Exception:
                    cm_val = None

            variants.append(RawVariant(
                size_label=label,
                size_eu=size_eu,
                size_cm=cm_val,
                merchant_variant_id=combid,
                price_minor=price_minor if price_minor is not None else 0,
                currency_code=currency,
                # "disabled" on the <li> is the sold-out marker.
                in_stock="disabled" not in attrs,
            ))
        return variants


adapter = register(SportVisionAdapter())

__all__ = ["SportVisionAdapter", "adapter", "normalize_sku"]
