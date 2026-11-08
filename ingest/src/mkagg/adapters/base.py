"""Adapter contract and shared extraction helpers.

Architecture rule, enforced by the type signatures here: an adapter is a pure
function from bytes to :class:`RawOffer`. Fetching lives in ``mkagg.fetcher``,
loading lives in ``mkagg.loader``. That separation is what lets every parser
be tested against a saved fixture, and it is what lets a broken parser be
fixed and then re-run over archived raw HTML instead of losing the history.

Two fetch kinds, deliberately distinct:

``catalog_parse``
    The full product page or catalogue record: title, images, MPN, the whole
    size run. 80-400 KB. Runs daily or weekly.

``stock_probe``
    Price and per-size availability only, from the smallest endpoint the store
    offers. 2-8 KB. Runs every 15 minutes for the hot tier. Most of the
    freshness budget goes here.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from ..models import RawOffer

# -----------------------------------------------------------------------------
# JSON-LD
# -----------------------------------------------------------------------------

_LD_BLOCK = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)


def iter_jsonld(html: str):
    """Yield every parseable JSON-LD node in the document.

    Tolerant by necessity: buzzsneakers.mk leaks HTML comment markers
    (``--><!--``) *inside* its JSON-LD script block, so a strict parse raises
    on that store. Unparseable blocks are skipped rather than fatal, and
    callers fall back to :func:`rescue_field`.
    """
    for block in _LD_BLOCK.findall(html):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict):
                yield node
                for sub in node.get("@graph", []) or []:
                    if isinstance(sub, dict):
                        yield sub


def jsonld_product(html: str) -> dict[str, Any] | None:
    """The first JSON-LD Product / ProductGroup node, or None."""
    for node in iter_jsonld(html):
        if node.get("@type") in ("Product", "ProductGroup"):
            return node
    return None


def ld_offer(node: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``offers``, which may be a dict, a list, or absent."""
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), {})
    return offers if isinstance(offers, dict) else {}


def ld_text(value: Any) -> str | None:
    """JSON-LD values are sometimes a bare string, sometimes ``{"name": ...}``."""
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def rescue_field(html: str, key: str) -> str | None:
    """Pull one JSON field out of malformed JSON-LD by regex.

    Only for stores whose structured data does not parse (buzzsneakers).
    Rejects captures containing HTML comment markers, which is exactly what
    leaks through on that store.
    """
    m = re.search(r'"%s"\s*:\s*"([^"<>]{1,60})"' % re.escape(key), html)
    if not m:
        return None
    value = m.group(1).strip()
    return None if ("--" in value or not value) else value


# -----------------------------------------------------------------------------
# dataLayer
# -----------------------------------------------------------------------------

_PRODUCT_CODE = re.compile(
    r'productCode["\']?\s*[:=]\s*["\']([A-Za-z0-9\-]{4,20})["\']')


def datalayer_product_codes(html: str) -> list[str]:
    """Manufacturer codes from the GTM dataLayer.

    The Sport Vision group ships ``productCode`` for the main product and for
    every recommendation tile, so this is a *candidate list*, not an answer --
    callers must cross-check against the page's own identity (JSON-LD sku, or
    the id in the URL) before trusting it.
    """
    seen: dict[str, None] = {}
    for code in _PRODUCT_CODE.findall(html):
        seen.setdefault(code.upper(), None)
    return list(seen)


# -----------------------------------------------------------------------------
# Adapter contract
# -----------------------------------------------------------------------------


class Adapter(ABC):
    """One adapter serves one platform, and therefore possibly many merchants.

    Recon collapsed 7 MK stores onto 4 adapters:

    ===============  =====================================================
    adapter          merchants
    ===============  =====================================================
    ``sportvision``  sportvision.mk, sportreality.mk, buzzsneakers.mk
    ``magento``      dsport.mk
    ``woocommerce``  megasportonlineshop.com
    ``aspnet_mk``    sport-m.com.mk, sizeer.com.mk
    ===============  =====================================================
    """

    #: adapter id, matching ``merchant.adapter`` in the database
    slug: str = ""

    #: True when the platform serves structured data and needs no DOM scraping
    is_api: bool = False

    @abstractmethod
    def parse_product(self, payload: bytes | str, url: str,
                      merchant_slug: str) -> RawOffer | None:
        """``catalog_parse``: a full product record from one fetched payload."""

    def parse_stock(self, payload: bytes | str, url: str,
                    merchant_slug: str) -> RawOffer | None:
        """``stock_probe``: price + availability only.

        Defaults to the full parse. Override where the platform offers a
        cheaper endpoint -- every adapter here does except ``sportvision``,
        which has no price-only endpoint and must re-fetch the page.
        """
        return self.parse_product(payload, url, merchant_slug)


_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    _REGISTRY[adapter.slug] = adapter
    return adapter


def get_adapter(slug: str) -> Adapter:
    try:
        return _REGISTRY[slug]
    except KeyError:
        raise LookupError(
            f"no adapter {slug!r}; registered: {sorted(_REGISTRY)}") from None


def all_adapters() -> dict[str, Adapter]:
    return dict(_REGISTRY)


def as_text(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "replace")
    return payload
