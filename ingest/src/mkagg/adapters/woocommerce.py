"""WooCommerce adapter: megasportonlineshop.com.

Recon verified the public Store API needs no auth:

* ``/wp-json/wc/store/products?per_page=100&category=202`` -- 665 sneakers in
  the Патики category (id 202)
* ``/wp-json/wc/store/products/{id}`` -- one product with its size attribute
  and its purchasable variations
* ``/wp-json/wc/store/products?type=variation&parent={id}`` -- per-variation
  detail, the cheap ``stock_probe`` endpoint

Two findings encoded below:

1. ``prices.price`` is an integer already scaled by
   ``prices.currency_minor_unit``, which is a *per-shop* setting: megasport
   reports 0 and sends ``"3199"`` for 3 199 ден, while e-elixir reports 2 and
   sends ``"424000"`` for 4 240 ден. Read the field, never assume the shop
   you wrote the adapter against. See :func:`parse_api_price_minor`.
2. The same size is spelled two ways in one payload: ``attributes[].terms[]``
   says ``"37.5"`` while ``variations[].attributes[].value`` says ``"37-5"``.
   Stock is derived by set membership, so both spellings must normalise to the
   same number or every half size reads as sold out.
"""
from __future__ import annotations

import html
import json
import re

from ..models import RawOffer, RawVariant
from ..fragrance import is_single_bottle, most_specific_shelf
from ..normalize import normalize_size, parse_api_price_minor
from ..sizing import read_size
from .base import Adapter, as_text, register

# Attribute names that carry a shoe size on this store.
SIZE_ATTRIBUTES = {"големина", "golemina", "size", "velicina", "величина"}


def _is_size_attribute(name: str | None) -> bool:
    return bool(name) and name.strip().lower() in SIZE_ATTRIBUTES


def _is_volume(value: str | None) -> bool:
    """Whether one attribute value states a bottle volume.

    Decided by the value, not the attribute name, because the name is not
    reliable: e-elixir spells the same axis милилитража on 1 275
    variations and "Достапни големини" -- literally "available sizes" --
    on 45 more, and a third shop could use that second name for clothing.
    "30ml" can only be one thing.
    """
    return read_size(value).volume_ml is not None


#: A volume written into the title. 214 of e-elixir's 279 *simple* products
#: carry one -- "Annayake Pour Elle Eau de Parfum 100ml" -- because a product
#: sold in one size has no variation to hang it on.
_TITLE_VOLUME = re.compile(r"(?<![a-z0-9])(\d{1,4})\s*ml(?![a-z0-9])", re.I)


def _volume_in_title(title: str | None) -> str | None:
    """The bottle size a title states, when nothing else carries it."""
    m = _TITLE_VOLUME.search(html.unescape(title or ""))
    return f"{m.group(1)}ml" if m else None


def _volume_terms(data: dict) -> list[str]:
    """Every volume this listing advertises, in the shop's own spelling."""
    out: list[str] = []
    for attr in data.get("attributes") or []:
        for term in attr.get("terms") or []:
            name = term.get("name")
            if name and _is_volume(name):
                out.append(name)
    return out


def _minor_unit(prices: dict) -> int:
    """The scale this payload says its own prices carry."""
    unit = prices.get("currency_minor_unit")
    return unit if isinstance(unit, int) and unit >= 0 else 0


class WooCommerceAdapter(Adapter):
    slug = "woocommerce"
    is_api = True

    def parse_product(self, payload, url, merchant_slug, *,
                      vertical: str | None = None) -> RawOffer | None:
        data = payload if isinstance(payload, (dict, list)) else json.loads(as_text(payload))
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not data.get("id"):
            return None

        shelves = [c.get("name") for c in (data.get("categories") or [])
                   if c.get("name")]

        # The fragrance vertical carries things that are not bottles of
        # perfume -- gift sets, candles, body mists, room diffusers,
        # deodorants -- on the same shelves as the bottles. 264 of
        # e-elixir's 987. They are dropped here, where the whole payload is
        # visible: the shelf that gives a set away is not always the one
        # recorded on the offer, and `is_single_bottle` wants every shelf.
        #
        # Gated on the vertical rather than applied always, because the
        # same adapter serves a shop selling shoes, and a sneaker whose
        # title happens to contain a plus is not a gift set.
        if vertical == "fragrance":
            volume_labels = [t.get("name")
                             for a in (data.get("attributes") or [])
                             for t in (a.get("terms") or []) if t.get("name")]
            if not is_single_bottle(data.get("name"), shelves, volume_labels):
                return None

        prices = data.get("prices") or {}
        minor_unit = _minor_unit(prices)
        currency = prices.get("currency_code") or "MKD"

        price_minor = parse_api_price_minor(
            prices.get("price"), source_minor_unit=minor_unit)
        regular_minor = parse_api_price_minor(
            prices.get("regular_price"), source_minor_unit=minor_unit)

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

        # Bottles, not shoes. A parent carries one price and a range, never
        # a price per volume -- so what can be said honestly depends on how
        # many volumes there are.
        volumes = _volume_terms(data) if not variants else []

        # A product sold in one size is `simple`: no variation to hang a
        # volume on, so the shop writes it into the name instead -- 214 of
        # e-elixir's 279 simple products do.
        #
        # And its attribute terms must be ignored, not merged. A simple
        # Annayake 100ml still carries "Достапни големини: 15ml, 30ml,
        # 60ml", because that attribute lists the sizes the *line* comes
        # in, not the ones this listing sells. Reading them as this
        # product's volumes makes a one-bottle listing look like four, and
        # then -- having more than one -- it reports no volume at all. The
        # first crawl filed eight Annayake bottles exactly that way.
        if vertical == "fragrance" and data.get("type") == "simple":
            from_title = _volume_in_title(data.get("name"))
            volumes = [from_title] if from_title else []
        if len(volumes) == 1 and price_minor is not None:
            # One volume, so the parent's price is that bottle's price.
            variants = [RawVariant(
                size_label=volumes[0], price_minor=price_minor,
                currency_code=currency, list_price_minor=regular_minor,
                in_stock=data.get("is_in_stock"))]
        elif len(volumes) > 1 and price_minor is not None:
            # Several, and `prices.price` is the cheapest of them. Which
            # bottle it belongs to is not stated: usually the smallest, but
            # "usually" would put a 30ml price on a 100ml listing whenever
            # it is not. So this offer carries no volume at all until the
            # variation endpoint prices each one -- see parse_stock, which
            # is where a fragrance's real rail comes from.
            variants = [RawVariant(
                size_label="", price_minor=price_minor,
                currency_code=currency, list_price_minor=regular_minor,
                in_stock=data.get("is_in_stock"))]

        if not variants and price_minor is not None:
            variants = [RawVariant(
                size_label="", price_minor=price_minor, currency_code=currency,
                list_price_minor=regular_minor,
                in_stock=data.get("is_in_stock"))]

        images = data.get("images") or []
        # WooCommerce's own brand taxonomy, which e-elixir populates on 969
        # of its 987 fragrances. megasport leaves it empty and keeps the
        # manufacturer code in `sku`, so both shapes have to be allowed.
        brands = data.get("brands") or []
        # Unescaped for the same reason the title is, and it costs more here:
        # 21 of the first crawl's 32 unmatched offers were "Dolce &amp;
        # Gabbana" failing to resolve against the "Dolce & Gabbana" already
        # in the brand table. A brand is the first half of a fragrance's
        # identity, so a mangled one does not merely look wrong -- it leaves
        # the offer attached to no product at all.
        brand = html.unescape(
            (brands[0].get("name") if brands else None) or "") or None
        # The shop's own shelf for this article. Chosen, not taken from
        # position 0: WooCommerce returns categories in no useful order, so
        # the first is the root Мириси as often as the leaf Машки Eau de
        # toilette. `most_specific_shelf` picks the one that says the most.
        shelf = most_specific_shelf(shelves)

        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=str(data["id"]),
            raw_brand=brand,
            category_path=shelf,
            # The Woo "sku" field holds the manufacturer code here
            # (e.g. "408280-02" for Puma, "392290-02" for the Caven 2.0).
            raw_mpn=(data.get("sku") or None),
            # Unescaped, because this becomes the product's canonical name.
            # WooCommerce serves 154 of e-elixir's 987 names with an escaped
            # apostrophe, and the first crawl filed one as "Annayake An 8217
            # Na Eau De Parfum" -- the entity's digits surviving into the
            # catalogue as a word.
            raw_title=html.unescape(data.get("name") or ""),
            product_url=data.get("permalink") or url,
            image_url=(images[0].get("src") if images else None),
            currency_code=currency,
            variants=variants,
            extractors={"title": "api", "mpn": "api",
                        "price": "api", "sizes": "api"},
        )

    def parse_many(self, payload, base_url: str, merchant_slug: str, *,
                   vertical: str | None = None) -> list[RawOffer]:
        data = payload if isinstance(payload, list) else json.loads(as_text(payload))
        offers = []
        for item in data if isinstance(data, list) else []:
            offer = self.parse_product(item, base_url, merchant_slug,
                                       vertical=vertical)
            if offer:
                offers.append(offer)
        return offers

    def parse_stock(self, payload, url, merchant_slug) -> RawOffer | None:
        """``stock_probe`` over ``?type=variation&parent={id}``.

        Also the per-volume source for fragrances: this is the only endpoint
        that prices each bottle, since a parent carries one price and a
        range.

        **Presence does not mean in stock.** That holds on megasport, which
        only ever returned buyable rows, and it was written down here as if
        it were a property of the platform. e-elixir returns sold-out ones
        too -- Ralph Lauren Polo 67 comes back with three volumes and
        ``is_in_stock`` false on one of them. So the field is read when the
        payload states it, and presence is only the fallback for a shop that
        does not.
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
                price_minor=parse_api_price_minor(
                    prices.get("price"),
                    source_minor_unit=_minor_unit(prices)) or 0,
                list_price_minor=parse_api_price_minor(
                    prices.get("regular_price"),
                    source_minor_unit=_minor_unit(prices)),
                currency_code=currency,
                in_stock=(row["is_in_stock"] if "is_in_stock" in row
                          else True),
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
