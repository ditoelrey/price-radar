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
                   ld_offer, ld_text, register, rescue_field)

_SIZE_CONTAINER = "product-size-tabs-new"
_SIZE_LI = re.compile(
    r'<li([^>]*?data-productsize-combid="(\d+)"[^>]*?)>(.*?)</li>', re.S)
_EUR_SIZE = re.compile(r'class="eur-size"[^>]*>([^<]*)', re.I)
_CM_SIZE = re.compile(r'class="cm-size"[^>]*>([^<]*)', re.I)
_ORIG_SIZE = re.compile(r'class="original-size"[^>]*>([^<]*)', re.I)
# /mk/patiki/8550245-puma-caven-2-0  ->  8550245
_URL_ID = re.compile(r"/(\d{3,12})-[^/]+/?$")


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
            image = ld_text(node.get("image"))
            for key in ("title", "mpn", "price"):
                extractors[key] = "jsonld"
        else:
            # buzzsneakers.mk lands here: broken JSON-LD, rescue by regex.
            title = rescue_field(html, "name")
            mpn = rescue_field(html, "sku") or rescue_field(html, "mpn")
            brand = rescue_field(html, "brand")
            store_id = rescue_field(html, "productID")
            price_raw = rescue_field(html, "price")
            currency = rescue_field(html, "priceCurrency") or "MKD"
            image = None
            for key in ("title", "mpn", "price"):
                extractors[key] = "regex"

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
        """Read the size grid.

        Regex rather than a DOM parser on purpose: the target is a flat run of
        sibling ``<li>`` elements inside one known container, which recon
        verified against all three stores. Swapping in selectolax here is a
        drop-in change if the markup ever gains nesting.
        """
        start = html.find(_SIZE_CONTAINER)
        if start < 0:
            return []
        block = re.sub(r">\s+<", "><", html[start:start + 20000])

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
