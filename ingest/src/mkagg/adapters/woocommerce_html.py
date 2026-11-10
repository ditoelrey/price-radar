"""WooCommerce product-page adapter: megasport, the robots-permitted route.

``megasportonlineshop.com/robots.txt`` forbids ``/wp-json/``, so the Store API
adapter cannot be used without permission. The product page is allowed and, as
it turns out, is the *better* source:

* JSON-LD carries a ``Product`` node inside ``@graph`` -- brand, name, ``sku``
  (the manufacturer code, e.g. ``392290-02``), image.
* ``data-product_variations`` holds the whole variation matrix as JSON:
  ``variation_id``, the size attribute, ``display_price``, ``is_in_stock`` and
  ``max_qty`` -- a real per-size remaining quantity.
* ``data-product_id`` gives the same listing id the Store API reports, so the
  two routes upsert the same ``merchant_offer`` rather than duplicating it.

Price accuracy, which is the reason to prefer this route even if permission
arrives: for the Puma Caven 2.0 the Store API reported ``prices.price = 3999``
while every variation on the page is ``display_price = 3199.2``. The parent
price missed a 20% reduction that applies to all sizes. The page reports what
a shopper would actually pay.
"""
from __future__ import annotations

import html as html_mod
import json
import re

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, parse_price_minor
from .base import (Adapter, as_text, jsonld_product, ld_offer, ld_text,
                   register)

_VARIATIONS = re.compile(r'data-product_variations=(["\'])(.*?)\1', re.S)
_PRODUCT_ID = re.compile(r'data-product_id="(\d+)"')
_SKU_CSS = re.compile(r'class="sku"[^>]*>([^<]+)<', re.I)
_OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', re.I)

#: Variation attribute keys that carry a shoe size on this store.
_SIZE_KEYS = ("golemina", "size", "velicina", "velicina")


def _size_from_attributes(attributes: dict) -> str | None:
    for key, value in (attributes or {}).items():
        if any(token in key.lower() for token in _SIZE_KEYS):
            text = str(value or "").strip()
            if text:
                return text
    return None


def parse_variations(html: str) -> list[dict]:
    """Decode the ``data-product_variations`` attribute.

    The JSON is HTML-escaped inside the attribute, so it must be unescaped
    before parsing. Woo also writes the literal ``false`` when a product has
    too many variations to inline, which is why a non-list result is tolerated.
    """
    m = _VARIATIONS.search(html)
    if not m:
        return []
    try:
        data = json.loads(html_mod.unescape(m.group(2)))
    except ValueError:
        return []
    return data if isinstance(data, list) else []


class WooCommerceHtmlAdapter(Adapter):
    slug = "woocommerce_html"
    is_api = False

    def parse_product(self, payload, url, merchant_slug) -> RawOffer | None:
        html = as_text(payload)
        extractors: dict[str, str] = {}

        node = jsonld_product(html)
        title = mpn = brand = image = None
        if node:
            offer = ld_offer(node)
            title = ld_text(node.get("name"))
            mpn = ld_text(node.get("sku")) or ld_text(node.get("mpn"))
            brand = ld_text(node.get("brand"))
            image = ld_text(node.get("image"))
            extractors.update(title="jsonld", mpn="jsonld")
            parent_price = parse_price_minor(offer.get("price"), minor_unit=0)
        else:
            parent_price = None

        if not mpn:
            m = _SKU_CSS.search(html)
            if m:
                mpn = m.group(1).strip()
                extractors["mpn"] = "css"

        if not image:
            m = _OG_IMAGE.search(html)
            if m:
                image = m.group(1)

        # The listing id the Store API also reports, so both routes agree on
        # merchant_sku and upsert the same offer.
        m = _PRODUCT_ID.search(html)
        merchant_sku = m.group(1) if m else (mpn or None)
        if not merchant_sku:
            return None
        extractors.setdefault("merchant_sku", "css")

        variants: list[RawVariant] = []
        seen: set[str] = set()
        for variation in parse_variations(html):
            label = _size_from_attributes(variation.get("attributes") or {})
            if not label:
                continue
            size_eu = normalize_size(label)
            key = str(size_eu) if size_eu is not None else label
            if key in seen:
                continue
            seen.add(key)

            price = parse_price_minor(variation.get("display_price"), minor_unit=0)
            list_price = parse_price_minor(
                variation.get("display_regular_price"), minor_unit=0)
            qty = variation.get("max_qty")
            variants.append(RawVariant(
                size_label=label,
                size_eu=size_eu,
                merchant_variant_id=str(variation.get("variation_id") or "") or None,
                price_minor=price if price is not None else (parent_price or 0),
                list_price_minor=list_price,
                currency_code="MKD",
                in_stock=bool(variation.get("is_in_stock")),
                stock_qty=int(qty) if isinstance(qty, (int, float)) else None))

        if variants:
            extractors["sizes"] = "embedded_json"
            extractors["price"] = "embedded_json"
        elif parent_price is not None:
            extractors["price"] = "jsonld"
            variants = [RawVariant(size_label="", price_minor=parent_price,
                                   currency_code="MKD", in_stock=None)]

        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=merchant_sku,
            raw_mpn=mpn,
            raw_title=title or merchant_sku,
            raw_brand=brand,
            product_url=url,
            image_url=image,
            currency_code="MKD",
            variants=variants,
            extractors=extractors)


adapter = register(WooCommerceHtmlAdapter())

__all__ = ["WooCommerceHtmlAdapter", "adapter", "parse_variations"]
