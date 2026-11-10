"""Magento product-page adapter: dsport.mk, the robots-permitted route.

``dsport.mk/robots.txt`` forbids ``/graphql``, so :mod:`mkagg.adapters.magento`
cannot legally be used however open that endpoint is. Product pages *are*
allowed, and they carry the same information in Magento's configurable-product
bootstrap:

* ``data-product-sku="KJ8942"`` -- the manufacturer article code
* ``spConfig.attributes[<id>]`` with ``code: "size"`` -- the size run, each
  option naming the child product id that supplies it
* ``spConfig.optionPrices[<child id>].finalPrice.amount`` -- per-size price

Stock, and why ``in_stock=True`` is honest here: Magento omits non-purchasable
children from ``spConfig`` entirely. Verified against the GraphQL capture for
the same store, where *every* returned variant was ``IN_STOCK`` -- both routes
list only buyable sizes and simply leave the rest out. The consequence worth
knowing is that "this size is sold out" and "this shoe was never made in that
size" are indistinguishable on this platform, from either route.
"""
from __future__ import annotations

import json
import re

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, parse_price_minor
from .base import Adapter, as_text, register

_PRODUCT_SKU = re.compile(r'data-product-sku="([^"]+)"')
_H1 = re.compile(r'<h1[^>]*class="[^"]*page-title[^"]*"[^>]*>(.*?)</h1>', re.S | re.I)
_OG_TITLE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', re.I)
_OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', re.I)
_PRICE_AMOUNT = re.compile(r'data-price-amount="([\d.]+)"')
_TAGS = re.compile(r"<[^>]+>")

# The configurable bootstrap. Located by its distinctive key rather than by
# walking all 38 x-magento-init blocks.
_SP_ATTRIBUTES = re.compile(r'"attributes"\s*:\s*\{\s*"\d+"\s*:\s*\{')
_SIZE_CODES = {"size", "golemina", "velicina", "shoe_size"}


def _balanced_object(text: str, start: int) -> str | None:
    """Slice the JSON object that begins at ``text[start] == '{'``.

    Needed because the spConfig lives inside a larger x-magento-init blob and
    the surrounding structure differs between Magento themes; finding the key
    and reading its balanced object is more robust than parsing the whole
    block and guessing at its shape.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_sp_config(html: str) -> dict | None:
    """Extract ``{attributes, optionPrices, ...}`` from the page."""
    match = _SP_ATTRIBUTES.search(html)
    if not match:
        return None

    attrs_start = html.index("{", match.start() + len('"attributes"') )
    attributes_raw = _balanced_object(html, attrs_start)
    if not attributes_raw:
        return None
    try:
        attributes = json.loads(attributes_raw)
    except ValueError:
        return None

    option_prices: dict = {}
    key = html.find('"optionPrices"', match.end())
    if key != -1:
        prices_raw = _balanced_object(html, html.index("{", key))
        if prices_raw:
            try:
                option_prices = json.loads(prices_raw)
            except ValueError:
                option_prices = {}
    return {"attributes": attributes, "optionPrices": option_prices}


class MagentoHtmlAdapter(Adapter):
    slug = "magento_html"
    is_api = False

    def parse_product(self, payload, url, merchant_slug) -> RawOffer | None:
        html = as_text(payload)

        sku_match = _PRODUCT_SKU.search(html)
        sku = sku_match.group(1).strip() if sku_match else None
        if not sku:
            # Fall back to the trailing token of the URL slug, which is the
            # article code on this store (".../adidas-...-kj8942").
            tail = re.search(r"-([a-z0-9]{5,14})/?$", url.split("?")[0], re.I)
            sku = tail.group(1).upper() if tail else None
        if not sku:
            return None

        title = None
        for pattern in (_H1, _OG_TITLE):
            m = pattern.search(html)
            if m:
                candidate = re.sub(r"\s+", " ", _TAGS.sub(" ", m.group(1))).strip()
                if candidate:
                    title = candidate
                    break

        image = None
        m = _OG_IMAGE.search(html)
        if m:
            image = m.group(1)

        # Parent price: the first data-price-amount on the page belongs to the
        # product; later ones are recommendation tiles.
        parent_price = None
        m = _PRICE_AMOUNT.search(html)
        if m:
            parent_price = parse_price_minor(m.group(1), minor_unit=0)

        extractors = {"mpn": "css" if sku_match else "url",
                      "title": "css", "price": "css"}

        variants: list[RawVariant] = []
        config = parse_sp_config(html)
        if config:
            option_prices = config.get("optionPrices") or {}
            for attr in (config.get("attributes") or {}).values():
                if str(attr.get("code", "")).lower() not in _SIZE_CODES:
                    continue
                extractors["sizes"] = "jsonconfig"
                seen: set[str] = set()
                for option in attr.get("options") or []:
                    label = str(option.get("label") or "").strip()
                    if not label:
                        continue
                    size_eu = normalize_size(label)
                    key = str(size_eu) if size_eu is not None else label
                    if key in seen:
                        continue
                    seen.add(key)

                    children = option.get("products") or []
                    child_id = str(children[0]) if children else None
                    price = None
                    if child_id and child_id in option_prices:
                        price = parse_price_minor(
                            ((option_prices[child_id].get("finalPrice") or {})
                             .get("amount")), minor_unit=0)
                    list_price = None
                    if child_id and child_id in option_prices:
                        list_price = parse_price_minor(
                            ((option_prices[child_id].get("oldPrice") or {})
                             .get("amount")), minor_unit=0)

                    variants.append(RawVariant(
                        size_label=label,
                        size_eu=size_eu,
                        merchant_variant_id=child_id,
                        price_minor=price if price is not None
                        else (parent_price or 0),
                        list_price_minor=list_price,
                        currency_code="MKD",
                        # Magento omits non-purchasable children, so every
                        # option present is buyable. See the module docstring.
                        in_stock=True))
                break

        if not variants and parent_price is not None:
            variants = [RawVariant(size_label="", price_minor=parent_price,
                                   currency_code="MKD", in_stock=None)]

        return RawOffer(
            merchant_slug=merchant_slug,
            # Same merchant_sku as the GraphQL adapter produces, so switching
            # routes updates the existing offer instead of duplicating it.
            merchant_sku=sku,
            raw_mpn=sku,
            raw_title=title or sku,
            raw_brand=_brand_from_title(title),
            product_url=url,
            image_url=image,
            currency_code="MKD",
            variants=variants,
            extractors=extractors)


def _brand_from_title(title: str | None) -> str | None:
    """dsport titles start with the brand: "ADIDAS TERREX ANYLANDER ЗА МАЖИ"."""
    if not title:
        return None
    first = title.strip().split()
    return first[0].title() if first else None


adapter = register(MagentoHtmlAdapter())

__all__ = ["MagentoHtmlAdapter", "adapter", "parse_sp_config"]
