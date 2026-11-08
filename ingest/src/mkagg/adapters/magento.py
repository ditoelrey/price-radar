"""Magento 2 adapter: dsport.mk.

Recon verified that ``POST https://www.dsport.mk/graphql`` is **fully open** --
no token, no API key, no rate limit encountered -- and returns everything the
platform needs:

* ``sku`` is the manufacturer article code (``CZ9556``, ``KJ8942``)
* ``price_range.minimum_price.final_price`` in MKD
* ``configurable_options`` -> the size run
* ``variants[].product`` -> per-size SKU, ``stock_status`` and
  ``only_x_left_in_stock`` (an actual remaining quantity)

This is a documented, versioned API, so it will not break on a redesign.
There is nothing to scrape on this store.
"""
from __future__ import annotations

import json

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, parse_price_minor
from .base import Adapter, as_text, register

# Requested once per catalogue page. Keep the field list tight: Magento's
# GraphQL cost grows fast with nested variants.
PRODUCT_FIELDS = """
sku
name
url_key
stock_status
image { url }
price_range { minimum_price { final_price { value currency } regular_price { value } } }
... on ConfigurableProduct {
  configurable_options { attribute_code label values { label } }
  variants {
    attributes { code label }
    product {
      sku
      stock_status
      only_x_left_in_stock
      price_range { minimum_price { final_price { value currency } } }
    }
  }
}
"""


def catalog_query(search: str = "", page: int = 1, page_size: int = 50,
                  category_id: str | None = None) -> dict:
    """Build a catalogue page query.

    Prefer ``category_id`` over ``search`` for enumeration: recon showed the
    search relevance filter returns a different (smaller) total_count than the
    category does, so a search sweep silently under-collects.
    """
    filters = []
    if category_id:
        filters.append(f'category_id:{{eq:"{category_id}"}}')
    filter_arg = f",filter:{{{','.join(filters)}}}" if filters else ""
    search_arg = f'search:"{search}",' if search else ""
    query = (
        f"{{products({search_arg}pageSize:{page_size},currentPage:{page}{filter_arg})"
        f"{{total_count items{{{PRODUCT_FIELDS}}}}}}}"
    )
    return {"query": query}


def size_probe_query(skus: list[str]) -> dict:
    """``stock_probe``: availability for a batch of parent SKUs, nothing else."""
    sku_list = ",".join(f'"{s}"' for s in skus)
    query = (
        f"{{products(filter:{{sku:{{in:[{sku_list}]}}}},pageSize:{len(skus)})"
        "{items{sku price_range{minimum_price{final_price{value currency}}}"
        "... on ConfigurableProduct{variants{attributes{label}"
        "product{sku stock_status only_x_left_in_stock}}}}}}"
    )
    return {"query": query}


class MagentoAdapter(Adapter):
    slug = "magento"
    is_api = True

    def parse_product(self, payload, url, merchant_slug) -> RawOffer | None:
        """Parse a single ``items[]`` entry, or a whole GraphQL envelope."""
        data = payload if isinstance(payload, dict) else json.loads(as_text(payload))
        items = self._items(data)
        if not items:
            return None
        return self._offer(items[0], url, merchant_slug)

    def parse_many(self, payload, base_url: str,
                   merchant_slug: str) -> list[RawOffer]:
        """Every product in one GraphQL catalogue response."""
        data = payload if isinstance(payload, dict) else json.loads(as_text(payload))
        offers = []
        for item in self._items(data):
            url = f"{base_url.rstrip('/')}/{item.get('url_key', '')}"
            offer = self._offer(item, url, merchant_slug)
            if offer:
                offers.append(offer)
        return offers

    @staticmethod
    def _items(data: dict) -> list[dict]:
        if "data" in data:
            return (data.get("data", {}).get("products", {}) or {}).get("items") or []
        if "products" in data:
            return data["products"].get("items") or []
        return [data] if "sku" in data else []

    def _offer(self, item: dict, url: str, merchant_slug: str) -> RawOffer | None:
        sku = item.get("sku")
        name = item.get("name")
        if not sku or not name:
            return None

        minimum = ((item.get("price_range") or {}).get("minimum_price") or {})
        final = (minimum.get("final_price") or {})
        currency = final.get("currency") or "MKD"
        parent_price = parse_price_minor(final.get("value"), minor_unit=0)
        regular = parse_price_minor(
            (minimum.get("regular_price") or {}).get("value"), minor_unit=0)

        variants: list[RawVariant] = []
        for variant in item.get("variants") or []:
            child = variant.get("product") or {}
            label = next((a.get("label") for a in variant.get("attributes") or []
                          if a.get("label")), None)
            if not label:
                continue
            size_eu = normalize_size(label)
            if size_eu is None and label.strip().upper() in ("BEZ VELICINA", "ONE SIZE"):
                # dsport uses "BEZ VELICINA" for one-size articles. Keep the
                # row (it is still a buyable offer) with an empty label.
                label = ""

            child_min = ((child.get("price_range") or {})
                         .get("minimum_price") or {}).get("final_price") or {}
            price = parse_price_minor(child_min.get("value"), minor_unit=0)
            qty = child.get("only_x_left_in_stock")

            variants.append(RawVariant(
                size_label=label,
                size_eu=size_eu,
                merchant_variant_id=child.get("sku"),
                price_minor=price if price is not None else (parent_price or 0),
                list_price_minor=regular,
                currency_code=currency,
                in_stock=(child.get("stock_status") == "IN_STOCK"),
                stock_qty=int(qty) if isinstance(qty, (int, float)) else None,
            ))

        if not variants and parent_price is not None:
            variants = [RawVariant(
                size_label="", price_minor=parent_price, currency_code=currency,
                list_price_minor=regular,
                in_stock=(item.get("stock_status") == "IN_STOCK"))]

        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=sku,
            raw_title=name,
            product_url=url,
            # On this store the Magento SKU *is* the manufacturer code.
            raw_mpn=sku,
            image_url=((item.get("image") or {}).get("url")),
            currency_code=currency,
            variants=variants,
            extractors={"title": "graphql", "mpn": "graphql",
                        "price": "graphql", "sizes": "graphql"},
        )

    def parse_stock(self, payload, url, merchant_slug) -> RawOffer | None:
        return self.parse_product(payload, url, merchant_slug)


adapter = register(MagentoAdapter())

__all__ = ["MagentoAdapter", "adapter", "catalog_query", "size_probe_query"]
