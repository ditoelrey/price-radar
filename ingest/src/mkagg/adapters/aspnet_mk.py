"""ASP.NET MVC adapter: sport-m.com.mk and sizeer.com.mk.

One platform, two merchants, one host IP (62.162.58.202). Recon findings:

* The product URL *is* the identifier::

      /ProductCatalog/ProductDetails?ProductID=M20325

  ``M20325`` is the Adidas manufacturer code, so matching is free on this
  platform -- no parsing needed to get the key.

* The price sits in an element whose **id contains the SKU**::

      <div class="normal-price" id='M20325 Price'>6.799,00 ден.</div>

* The page ships an **unrendered Razor placeholder** where the sizes belong
  (``data-original-title="item.Velicina"``), so sizes are never in the HTML.
  They come from a POST-only endpoint found in the page's own JavaScript::

      POST /ProductCatalog/GetVelicini/   body: ProductID=M20325

  A GET returns 404; ``GetSearchSuggestions`` likewise rejects GET with
  ``JsonRequestBehavior``. Always POST with ``X-Requested-With``.

* Crucial difference between the two merchants, same endpoint:

  ===================  ==================================================
  sport-m.com.mk       ``Zaliha`` is a real quantity (1, 3, 5, ...)
  sizeer.com.mk        ``Zaliha`` is ``null`` for every size
  ===================  ==================================================

  So sizeer gets ``in_stock=None`` -- unknown, not out of stock. The UI must
  render that as "listed", never as "in stock". See ``merchant.publishes_stock``.
"""
from __future__ import annotations

import json
import re

from ..models import RawOffer, RawVariant
from ..normalize import normalize_size, parse_price_minor
from .base import Adapter, as_text, register

SIZES_PATH = "/ProductCatalog/GetVelicini/"

_URL_PRODUCT_ID = re.compile(r"[?&]ProductID=([A-Za-z0-9\-_.]+)", re.I)
# id='M20325 Price'  ->  ("M20325", "6.799,00 ден.")
_PRICE_BY_ID = re.compile(
    r"""id=['"]([A-Za-z0-9\-_.]+)\s+Price['"][^>]*>\s*([^<]+?)\s*<""")
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
#: Product photos live at /ProductImages/{ProductID}.webp on this platform.
#: Matched against *this* product's id on purpose: the page also carries the
#: carousel's images (GX6394, ID2045) and a brand-logo directory, so a generic
#: "first image on the page" would attach a neighbour's photo or a logo.
#:
#: og:image is useless here and actively harmful -- sport-m advertises
#: Content/FacebookLogo.png and sizeer Content/Logo.png, so trusting that tag
#: would put a logo on every single product card.
_PRODUCT_IMAGE = r'["\']([^"\']*?/ProductImages/{pid}(?:_\d+)?\.(?:webp|jpg|jpeg|png))["\']'
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def product_id_from_url(url: str) -> str | None:
    m = _URL_PRODUCT_ID.search(url or "")
    return m.group(1) if m else None


def sizes_request(base_url: str, product_id: str) -> tuple[str, bytes, dict]:
    """Build the POST that returns the size run. GET does not work."""
    return (
        f"{base_url.rstrip('/')}{SIZES_PATH}",
        f"ProductID={product_id}".encode(),
        {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": (f"{base_url.rstrip('/')}"
                        f"/ProductCatalog/ProductDetails?ProductID={product_id}"),
        },
    )


def parse_sizes(payload, *, price_minor: int, currency: str = "MKD",
                publishes_stock: bool = True) -> list[RawVariant]:
    """Turn a ``GetVelicini`` response into variants.

    Field map::

        Velicina          UK size, the platform's primary label ("7.5")
        EvropskaVelicina  EU size, with Unicode vulgar fractions ("41⅓")
        VelicinaCM        cm, usually 0.00 and therefore ignored
        Zaliha            remaining quantity, or null on sizeer
    """
    rows = payload if isinstance(payload, list) else json.loads(as_text(payload))
    variants: list[RawVariant] = []
    seen: set[str] = set()

    for row in rows if isinstance(rows, list) else []:
        eu_label = (row.get("EvropskaVelicina") or "").strip()
        uk_label = str(row.get("Velicina") or "").strip()
        label = eu_label or uk_label
        if not label or label in seen:
            continue
        seen.add(label)

        qty = row.get("Zaliha")
        has_qty = isinstance(qty, (int, float))
        cm = row.get("VelicinaCM")
        try:
            cm_val = normalize_size(str(cm)) if cm else None
            if cm_val is not None and cm_val == 0:
                cm_val = None
        except Exception:
            cm_val = None

        variants.append(RawVariant(
            size_label=label,
            size_eu=normalize_size(eu_label) if eu_label else None,
            size_uk=normalize_size(uk_label) if uk_label else None,
            size_cm=cm_val,
            price_minor=price_minor,
            currency_code=currency,
            # publishes_stock=False (sizeer) -> stay None. Unknown stock must
            # never be rendered as a positive in-stock claim.
            in_stock=(qty > 0) if (has_qty and publishes_stock) else None,
            stock_qty=int(qty) if (has_qty and publishes_stock) else None,
        ))
    return variants


def product_image(html: str, product_id: str, base_url: str = "") -> str | None:
    """The product's own photo, keyed to its id rather than page order."""
    if not product_id:
        return None
    pattern = _PRODUCT_IMAGE.format(pid=re.escape(product_id))
    match = re.search(pattern, html, re.I)
    if not match:
        return None
    url = match.group(1)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/") and base_url:
        return base_url.rstrip("/") + url
    return url


def _brand_from_title(title: str | None) -> str | None:
    """First token of the title, which is the brand on this platform."""
    if not title:
        return None
    first = title.strip().split()
    if not first:
        return None
    token = first[0].strip(" -|,")
    return token.title() if 2 <= len(token) <= 20 else None


class AspNetMkAdapter(Adapter):
    slug = "aspnet_mk"
    is_api = True   # sizes come from JSON; only the price needs the HTML

    def parse_product(self, payload, url, merchant_slug, *,
                      sizes_payload=None, publishes_stock: bool = True
                      ) -> RawOffer | None:
        html = as_text(payload)
        origin = re.match(r"https?://[^/]+", url or "")
        base_url = origin.group(0) if origin else ""

        product_id = product_id_from_url(url)
        price_minor, price_sku = None, None
        for sku, text in _PRICE_BY_ID.findall(html):
            # Prefer the element whose id matches the URL's ProductID; the page
            # also renders price elements for recommendation tiles.
            if product_id and sku.upper() == product_id.upper():
                price_minor, price_sku = parse_price_minor(text, minor_unit=0), sku
                break
            if price_minor is None:
                price_minor, price_sku = parse_price_minor(text, minor_unit=0), sku

        product_id = product_id or price_sku
        if not product_id:
            return None

        title = None
        for pattern in (_H1, _TITLE):
            m = pattern.search(html)
            if m:
                candidate = _TAGS.sub(" ", m.group(1))
                candidate = re.sub(r"\s+", " ", candidate).strip()
                if candidate:
                    title = candidate
                    break

        variants: list[RawVariant] = []
        if sizes_payload is not None:
            variants = parse_sizes(
                sizes_payload, price_minor=price_minor or 0,
                publishes_stock=publishes_stock)
        if not variants and price_minor is not None:
            variants = [RawVariant(size_label="", price_minor=price_minor,
                                   currency_code="MKD", in_stock=None)]

        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=product_id,
            # The URL's ProductID is the manufacturer code on this platform.
            raw_mpn=product_id,
            image_url=product_image(html, product_id, base_url),
            raw_title=title or product_id,
            # Titles on this platform lead with the brand ("Hoka Clifton 11").
            # Without it the matcher cannot block, and the offer stays
            # unmatched however good its article code is.
            raw_brand=_brand_from_title(title),
            product_url=url,
            currency_code="MKD",
            variants=variants,
            extractors={"mpn": "url", "price": "css",
                        "sizes": "api" if sizes_payload is not None else "none"},
        )

    def parse_stock(self, payload, url, merchant_slug, *,
                    price_minor: int = 0, publishes_stock: bool = True
                    ) -> RawOffer | None:
        """``stock_probe``: one small POST, no HTML fetch needed."""
        product_id = product_id_from_url(url)
        variants = parse_sizes(payload, price_minor=price_minor,
                               publishes_stock=publishes_stock)
        if not variants:
            return None
        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=product_id or "",
            raw_mpn=product_id,
            raw_title="", product_url=url, currency_code="MKD",
            variants=variants, extractors={"sizes": "api"},
        )


adapter = register(AspNetMkAdapter())

__all__ = ["AspNetMkAdapter", "adapter", "parse_sizes", "sizes_request",
           "product_id_from_url", "product_image", "SIZES_PATH"]
