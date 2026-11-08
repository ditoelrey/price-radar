"""WooCommerce adapter: megasportonlineshop.com.

Recon verified the public Store API needs no auth:

* ``/wp-json/wc/store/products?per_page=100&category=202`` -- 665 sneakers in
  the Патики category (id 202)
* ``/wp-json/wc/store/products/{id}`` -- one product with its size attribute
  and its purchasable variations
* ``/wp-json/wc/store/products?type=variation&parent={id}`` -- per-variation
  detail, the cheap ``stock_probe`` endpoint

Two findings encoded below:

1. ``prices.currency_minor_unit`` is **0** for MKD here, so ``prices.price``
   is already whole denars. Never hard-code 100.
2. The same size is spelled two ways in one payload: ``attributes[].terms[]``
   says ``"37.5"`` while ``variations[].attributes[].value`` says ``"37-5"``.
   Stock is derived by set membership, so both spellings must normalise to the
   same number or every half size reads as sold out.
"""
from __future__ import annotations

import json

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, parse_price_minor
from .base import Adapter, as_text, register

# Attribute names that carry a shoe size on this store.
SIZE_ATTRIBUTES = {"големина", "golemina", "size", "velicina", "величина"}


def _is_size_attribute(name: str | None) -> bool:
    return bool(name) and name.strip().lower() in SIZE_ATTRIBUTES


class WooCommerceAdapter(Adapter):
    slug = "woocommerce"
    is_api = True

    def parse_product(self, payload, url, merchant_slug) -> RawOffer | None:
        data = payload if isinstance(payload, (dict, list)) else json.loads(as_text(payload))
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not data.get("id"):
            return None

        prices = data.get("prices") or {}
        minor_unit = prices.get("currency_minor_unit")
        if not isinstance(minor_unit, int):
            minor_unit = 0
        currency = prices.get("currency_code") or "MKD"

        price_minor = parse_price_minor(prices.get("price"), minor_unit=0)
        regular_minor = parse_price_minor(prices.get("regular_price"), minor_unit=0)

        # All sizes the listing advertises.
        offered: list[str] = []
        for attr in data.get("attributes") or []:
            if _is_size_attribute(attr.get("name")):
                offered += [t.get("name") for t in attr.get("terms") or []
                            if t.get("name")]

        # Sizes that are actually purchasable: the Store API only returns
        # variations that can be bought. Compare on the normalised number,
        # never on the raw string ("37.5" vs "37-5").
        purchasable: set[str] = set()
        for variation in data.get("variations") or []:
            for attr in variation.get("attributes") or []:
                if _is_size_attribute(attr.get("name")) and attr.get("value"):
                    size = normalize_size(attr["value"])
                    if size is not None:
                        purchasable.add(str(size))

        variant_ids = {}
        for variation in data.get("variations") or []:
            for attr in variation.get("attributes") or []:
                if _is_size_attribute(attr.get("name")) and attr.get("value"):
                    size = normalize_size(attr["value"])
                    if size is not None:
                        variant_ids.setdefault(str(size), variation.get("id"))

        variants: list[RawVariant] = []
        seen: set[str] = set()
        for label in offered:
            size_eu = normalize_size(label)
            key = str(size_eu) if size_eu is not None else label
            if key in seen:
                continue
            seen.add(key)
            variants.append(RawVariant(
                size_label=label,
                size_eu=size_eu,
                merchant_variant_id=(str(variant_ids[key])
                                     if key in variant_ids else None),
                price_minor=price_minor if price_minor is not None else 0,
                list_price_minor=regular_minor,
                currency_code=currency,
                in_stock=(key in purchasable) if purchasable else None,
            ))

        if not variants and price_minor is not None:
            variants = [RawVariant(
                size_label="", price_minor=price_minor, currency_code=currency,
                list_price_minor=regular_minor,
                in_stock=data.get("is_in_stock"))]

        images = data.get("images") or []
        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=str(data["id"]),
            # The Woo "sku" field holds the manufacturer code here
            # (e.g. "408280-02" for Puma, "392290-02" for the Caven 2.0).
            raw_mpn=(data.get("sku") or None),
            raw_title=data.get("name") or "",
            product_url=data.get("permalink") or url,
            image_url=(images[0].get("src") if images else None),
            currency_code=currency,
            variants=variants,
            extractors={"title": "api", "mpn": "api",
                        "price": "api", "sizes": "api"},
        )

    def parse_many(self, payload, base_url: str,
                   merchant_slug: str) -> list[RawOffer]:
        data = payload if isinstance(payload, list) else json.loads(as_text(payload))
        offers = []
        for item in data if isinstance(data, list) else []:
            offer = self.parse_product(item, base_url, merchant_slug)
            if offer:
                offers.append(offer)
        return offers

    def parse_stock(self, payload, url, merchant_slug) -> RawOffer | None:
        """``stock_probe`` over ``?type=variation&parent={id}``.

        Each returned row is one buyable size, so presence means in stock.
        """
        data = payload if isinstance(payload, list) else json.loads(as_text(payload))
        if not isinstance(data, list) or not data:
            return None

        parent_id = data[0].get("parent")
        variants: list[RawVariant] = []
        currency = "MKD"
        for row in data:
            prices = row.get("prices") or {}
            currency = prices.get("currency_code") or currency
            # "Големина: 38.5" -> "38.5"
            label = (row.get("variation") or "").split(":")[-1].strip()
            if not label:
                continue
            variants.append(RawVariant(
                size_label=label,
                size_eu=normalize_size(label),
                merchant_variant_id=str(row.get("id")),
                price_minor=parse_price_minor(prices.get("price"), minor_unit=0) or 0,
                currency_code=currency,
                in_stock=True,
            ))

        if not variants:
            return None
        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=str(parent_id) if parent_id else "",
            raw_title="", product_url=url, currency_code=currency,
            variants=variants, extractors={"sizes": "api"},
        )


adapter = register(WooCommerceAdapter())

__all__ = ["WooCommerceAdapter", "adapter", "SIZE_ATTRIBUTES"]
