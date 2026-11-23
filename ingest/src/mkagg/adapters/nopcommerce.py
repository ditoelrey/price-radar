"""nopCommerce adapter: shop.schatze.mk.

The sixth platform and the second perfumery. Not to be confused with
:mod:`mkagg.adapters.aspnet_mk`, which is also ASP.NET and is otherwise
nothing alike -- that one is a bespoke MVC app with
``/ProductCatalog/ProductDetails?ProductID=M20325``, while this is stock
nopCommerce 4.x, recognisable from its robots.txt alone
(``/setproductreviewhelpfulness``, ``/boards/``, ``/onepagecheckout``).

Findings from recon, each of which this module encodes:

1. **The page is Macedonian unless you ask otherwise.** A first request
   gets ``Производител:`` and ``Почетна / Парфеми / Женски``. The site then
   sets ``.Duos.Culture`` and will happily serve English for the rest of
   the session, which is how the first recon pass came back reading
   ``Manufacturer:`` and ``Fragrances / Women``. Both spellings are read
   here, because a stray cookie must not change what we parse.

2. **The brand is not in the title.** "Pour Homme - edt" is Versace's, and
   says so only in a Manufacturer field. That is the whole reason
   `mkagg.fragrance` strips a brand it is given rather than one it finds.

3. **Two price shapes.** A plain product renders one span; a discounted one
   renders ``Цена:`` (the old price) above ``Вашата цена:``. Reading the
   first number on the page gets the label on the second shape, and the
   first recon pass recorded a product as unpriced for exactly that reason.

4. **One price, several volumes.** The Milliliters radio group lists 30ml,
   50ml and 100ml, and the page prices only the preselected one. Which one
   that is, is not stated anywhere in the markup beyond `checked`. Per-
   volume prices exist only behind
   ``POST /shoppingcart/productdetails_attributechange``, which this shop's
   robots.txt disallows -- see ``merchant.robots_notes`` for schatze, and
   :func:`attribute_change_request` for the shape it would take.
"""
from __future__ import annotations

import html as html_module
import json
import re
from urllib.parse import urlencode

from ..fragrance import is_single_bottle
from ..models import RawOffer, RawVariant
from ..normalize import parse_price_minor
from .base import Adapter, as_text, register

#: The shop's own id for a product, on the wrapper nopCommerce renders
#: around every detail page. The same number appears in `price-value-NN`,
#: and both are checked because a redesign is more likely to drop one.
_PRODUCT_ID = re.compile(r'data-productid="(\d+)"')
_PRICE_ID = re.compile(r"price-value-(\d+)")

_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_MANUFACTURER = re.compile(r'class="manufacturers"[^>]*>(.*?)</div>', re.S | re.I)
_BREADCRUMB = re.compile(r'breadcrumb"?[^>]*>(.*?)</(?:div|ol|ul)>', re.S | re.I)
_IMAGE = re.compile(r'itemprop="image"\s+content="([^"]+)"', re.I)
_AVAILABILITY = re.compile(r'itemprop="availability"\s+content="([^"]+)"', re.I)

#: The actual price, in both shapes: a plain product renders
#: `id="price-value-NN" class="price-value-NN"`, a discounted one renders
#: only the class, inside the `discounted-price` block.
def _price_span(product_id: str) -> re.Pattern[str]:
    return re.compile(
        rf'class="[^"]*price-value-{product_id}[^"]*"[^>]*>(.*?)</span>', re.S)


#: The pre-discount price, when the shop advertises one.
_OLD_PRICE = re.compile(
    r'class="non-discounted-price".*?<span[^>]*>(.*?)</span>', re.S | re.I)

#: The Milliliters radio group. `data-attr` is the shop's attribute id and
#: `data-attr-value` each option's -- both needed to ask
#: productdetails_attributechange about one volume.
_ATTRIBUTES = re.compile(r'<div class="attributes">(.*?)</dl>', re.S | re.I)
_ATTR_ID = re.compile(r'data-attr="(\d+)"')
_OPTION = re.compile(
    r'data-attr-value="(\d+)".*?custom-control-label[^>]*>([^<]{0,24})', re.S)
_CHECKED = re.compile(r'value="(\d+)"\s+checked')

#: What the brand field is called, in either language the shop may serve.
_BRAND_LABELS = ("производител", "manufacturer")

#: The antiforgery token the attribute form carries. nopCommerce pairs it
#: with a `.Duos.Antiforgery` cookie, so a request needs both or answers 400.
_TOKEN = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]*)"')


def _text(fragment: str | None) -> str:
    """Tags out, entities decoded, whitespace squeezed."""
    if not fragment:
        return ""
    return " ".join(
        html_module.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _brand(page: str) -> str | None:
    """The manufacturer, without the label the shop prints in front of it."""
    found = _MANUFACTURER.search(page)
    if not found:
        return None
    value = _text(found.group(1))
    # "Производител: Versace" / "Manufacturer: Versace". Split on the colon
    # rather than stripping a known prefix, so a third language still works.
    head, sep, tail = value.partition(":")
    if sep and head.strip().lower() in _BRAND_LABELS:
        value = tail
    return value.strip() or None


def _shelf(page: str) -> str | None:
    """The shop's own shelf, as its breadcrumb states it.

    "Почетна / Парфеми / Женски / Pour Homme - edt" yields "Парфеми /
    Женски": the vertical and the department, without the home link or the
    product's own name. Both halves earn their place -- `mkagg.taxonomy`
    reads the first as `perfume` and `mkagg.fragrance` reads the second as
    the audience.
    """
    found = _BREADCRUMB.search(page)
    if not found:
        return None
    crumbs = [c.strip() for c in _text(found.group(1)).split("/") if c.strip()]
    # Drop the home link and the product itself.
    middle = crumbs[1:-1]
    return " / ".join(middle) or None


def _volumes(page: str) -> tuple[str | None, list[tuple[str, str]], str | None]:
    """``(attribute_id, [(option_id, label)], checked_option_id)``.

    Empty for a product sold in one unstated size, which this shop does
    have -- the group is only rendered when the product has options.
    """
    block = _ATTRIBUTES.search(page)
    if not block:
        return None, [], None
    inner = block.group(1)
    attr = _ATTR_ID.search(inner)
    options = [(value, _text(label)) for value, label in _OPTION.findall(inner)]
    checked = _CHECKED.search(inner)
    return (attr.group(1) if attr else None,
            options,
            checked.group(1) if checked else None)


def attribute_change_request(base_url: str, page: str, product_id: str,
                             attribute_id: str, option_id: str):
    """The POST that prices one volume.

    Read-only despite the path: it returns JSON and changes nothing. The
    mutating route on this platform is ``/addproducttocart/``, which this
    adapter never calls. See V32 for why it is fetched at all -- the shop's
    robots.txt disallows the ``/shoppingcart/`` prefix and the decision to
    call it anyway is an operator's, recorded in ``merchant.robots_notes``.

    The page is passed in because the request is not self-contained: it
    needs the antiforgery token out of the product form, which is bound to
    a cookie from the same session. Without it the shop answers 400 and
    says nothing about why.
    """
    token = _TOKEN.search(page)
    body = urlencode({
        f"product_attribute_{attribute_id}": option_id,
        f"addtocart_{product_id}.EnteredQuantity": "1",
        "__RequestVerificationToken": token.group(1) if token else "",
    }).encode()
    url = (f"{base_url.rstrip('/')}/shoppingcart/productdetails_attributechange"
           f"?productId={product_id}"
           f"&validateAttributeConditions=False&loadPicture=False")
    headers = {"X-Requested-With": "XMLHttpRequest",
               "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    return url, body, headers


def parse_attribute_change(payload) -> tuple[int | None, int | None]:
    """``(price_minor, list_price_minor)`` for one volume.

    Only the two prices, because only the two prices are there. The
    response also carries `sku`, `mpn`, `gtin` and `stockAvailability`, and
    on every product tested each one came back null or empty -- this
    installation configures no per-combination codes and no per-combination
    stock. Reading them would be reading nothing; claiming them would be
    worse.

    `priceWithoutDiscount` equal to `price` is not a discount, and the
    badge must not say otherwise -- this shop renders the two-price layout
    at full price too.
    """
    try:
        data = json.loads(as_text(payload))
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    price = parse_price_minor(_text(data.get("price")))
    was = parse_price_minor(_text(data.get("priceWithoutDiscount")))
    if was is not None and price is not None and was <= price:
        was = None
    return price, was


def volume_options(page: str):
    """``(product_id, attribute_id, [(option_id, label)])`` for a page.

    Exposed for the worker, which makes the per-volume requests: the
    adapter parses, the worker fetches, and neither does the other's job.
    """
    found = _PRODUCT_ID.search(page) or _PRICE_ID.search(page)
    if not found:
        return None, None, []
    attribute_id, options, _checked = _volumes(page)
    return found.group(1), attribute_id, options


class NopCommerceAdapter(Adapter):
    slug = "nopcommerce"
    is_api = False

    def parse_product(self, payload, url, merchant_slug, *,
                      vertical: str | None = None,
                      publishes_stock: bool = False) -> RawOffer | None:
        page = as_text(payload)
        found = _PRODUCT_ID.search(page) or _PRICE_ID.search(page)
        if not found:
            return None
        product_id = found.group(1)

        heading = _H1.search(page)
        title = _text(heading.group(1)) if heading else ""
        if not title:
            return None

        priced = _price_span(product_id).search(page)
        price_minor = (parse_price_minor(_text(priced.group(1)))
                       if priced else None)
        was = _OLD_PRICE.search(page)
        list_minor = (parse_price_minor(_text(was.group(1)))
                      if was else None)
        # Equal prices are not a discount, and the badge must not claim one.
        if list_minor is not None and price_minor is not None \
                and list_minor <= price_minor:
            list_minor = None

        _attr, options, checked = _volumes(page)
        labels = [label for _value, label in options]

        # Gift sets, shelved with the bottles. 152 of this shop's 1 234
        # fragrance pages are one -- "212 Vip Black 100ml EDP + Shower Gel
        # 100ml", "Boss Bottled EDT 100ml + Deodorant 150ml + Shower Gel".
        # A set is not a volume of the bottle inside it, and letting one in
        # puts a set's price on the same rail as the bottle's.
        #
        # Gated on the vertical for the same reason the WooCommerce adapter
        # is: this is a rule about perfume, not about nopCommerce.
        if vertical == "fragrance" and not is_single_bottle(
                title, [_shelf(page) or ""], labels):
            return None

        # Stock is product-level microdata here: the page says InStock for
        # the product, never for a volume. With `publishes_stock` false --
        # which is how this merchant is seeded -- that is not evidence
        # about the bottle a shopper wants, so it stays unknown.
        stated = _AVAILABILITY.search(page)
        in_stock = None
        if publishes_stock:
            in_stock = bool(stated) and "InStock" in stated.group(1)

        variants: list[RawVariant] = []
        if price_minor is not None:
            if len(labels) == 1:
                # One volume, so the page's price is that bottle's price.
                variants.append(RawVariant(
                    size_label=labels[0], price_minor=price_minor,
                    list_price_minor=list_minor, in_stock=in_stock))
            else:
                # Several, and the page prices only the preselected one --
                # `checked` says which option, but not which price, and the
                # other volumes cost more. Attributing this figure to any
                # one of them would be a guess, and attributing it to all
                # of them would be three wrong prices instead of one
                # missing rail. So the offer carries a price and no volume.
                variants.append(RawVariant(
                    size_label="", price_minor=price_minor,
                    list_price_minor=list_minor, in_stock=in_stock))

        image = _IMAGE.search(page)
        return RawOffer(
            merchant_slug=merchant_slug,
            merchant_sku=product_id,
            raw_title=title,
            raw_brand=_brand(page),
            product_url=url,
            image_url=image.group(1) if image else None,
            category_path=_shelf(page),
            variants=variants,
            extractors={"title": "html", "price": "html",
                        "brand": "html", "sizes": "html"},
        )


adapter = register(NopCommerceAdapter())

__all__ = ["NopCommerceAdapter", "adapter", "attribute_change_request",
           "parse_attribute_change", "volume_options"]
