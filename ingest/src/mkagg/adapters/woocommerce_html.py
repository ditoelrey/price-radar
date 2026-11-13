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
from .base import (Adapter, as_text, jsonld_product, ld_image, ld_offer,
                   ld_text, og_image, register)

_VARIATIONS = re.compile(r'data-product_variations=(["\'])(.*?)\1', re.S)
_PRODUCT_ID = re.compile(r'data-product_id="(\d+)"')
_SKU_CSS = re.compile(r'class="sku"[^>]*>([^<]+)<', re.I)
_OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', re.I)

_TAGS = re.compile(r"<[^>]+>")

#: Woo's own sold-out marker on the product wrapper. Checked rather than
#: inferred from an empty variations list: "[]" on its own could equally mean
#: the markup changed or the inline blob was suppressed, and inventing a
#: sold-out offer out of a parser failure is exactly the wrong way round.
_OUT_OF_STOCK = re.compile(r'class="stock out-of-stock"', re.I)

#: Option texts that are placeholders rather than sizes. Woo renders its
#: "pick one" entry as a dash on this shop; storing it would put a variant
#: labelled "-" in the comparison table next to a real price.
_NOT_A_SIZE = {"-", "–", "—", "", "Изберете опција"}

#: Variation attribute keys that carry a shoe size on this store.
_SIZE_KEYS = ("golemina", "size", "velicina", "velicina")

#: The size dropdown, whose <option> elements map each attribute slug to the
#: text the shop actually displays.
_SIZE_SELECT = re.compile(
    r'<select[^>]*name="attribute_[^"]*"[^>]*>(.*?)</select>', re.S | re.I)
_OPTION = re.compile(
    r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', re.S | re.I)


def size_slug_labels(html: str) -> dict[str, str]:
    """Map each size attribute slug to the label the shop shows for it.

    The variations JSON carries slugs, not labels. Usually they are the same
    string ("44" -> "44") and the distinction does not matter, but Woo also
    emits placeholder options whose slug is an opaque term id:

        <option value="387">-</option>
        <option value="44">44</option>

    Read literally, that 387 became a size. It is not one -- the shop renders
    it as a dash -- and it reached the database as an EU size, where it
    overflowed `numeric(5,3)` and brought down a 500-product run. The select
    is the only place the two are related, so the label has to come from here.
    """
    labels: dict[str, str] = {}
    for select in _SIZE_SELECT.finditer(html):
        for value, text in _OPTION.findall(select.group(1)):
            value = value.strip()
            if value:
                labels[value] = _TAGS.sub("", html_mod.unescape(text)).strip()
    return labels


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
            # A list of ImageObject dicts on this store.
            image = ld_image(node)
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
            image = og_image(html)

        # The listing id the Store API also reports, so both routes agree on
        # merchant_sku and upsert the same offer.
        m = _PRODUCT_ID.search(html)
        merchant_sku = m.group(1) if m else (mpn or None)
        if not merchant_sku:
            return None
        extractors.setdefault("merchant_sku", "css")

        variants: list[RawVariant] = []
        seen: set[str] = set()
        # Slug -> displayed text, so a placeholder option cannot become a size.
        slug_labels = size_slug_labels(html)
        for variation in parse_variations(html):
            label = _size_from_attributes(variation.get("attributes") or {})
            if label:
                label = slug_labels.get(label, label)
            if not label or label in _NOT_A_SIZE:
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
        elif parent_price is None and _OUT_OF_STOCK.search(html):
            # Sold out, and the shop has taken the price down with the stock:
            # no `offers` node, no price anywhere on the page, an empty
            # variations list. Recorded as one priceless, out-of-stock variant
            # so the product page can say "sold out at this shop" instead of
            # implying the shop never carried it.
            #
            # Sizes are gone too -- there is no dropdown left to read -- so
            # this makes no claim about them either.
            extractors["stock"] = "css"
            variants = [RawVariant(size_label="", price_minor=None,
                                   currency_code="MKD", in_stock=False)]
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
