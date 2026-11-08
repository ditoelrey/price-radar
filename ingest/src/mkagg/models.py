"""Transport objects between the adapters and the loader.

The adapters' only job is ``bytes -> RawOffer``. They never touch the network
and never touch the database, which is what makes every one of them testable
against a saved HTML/JSON fixture with no live site and no credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# Which extraction tier produced a field. Recorded per field, per run, into
# ingest_run.extractor_stats: a rising share of "css" means a redesign is
# coming, and a drop in "jsonld" is the earliest breakage signal there is.
ExtractorTier = str  # "api" | "graphql" | "jsonld" | "datalayer" | "url" | "css" | "regex"


@dataclass(slots=True)
class RawVariant:
    """One size of one merchant listing."""

    size_label: str                      # verbatim from the shop: "44 2/3", "41⅓"
    price_minor: int                     # integer minor units
    currency_code: str = "MKD"

    size_eu: Decimal | None = None
    size_uk: Decimal | None = None
    size_cm: Decimal | None = None

    merchant_variant_id: str | None = None
    list_price_minor: int | None = None
    shipping_cost_minor: int | None = None

    # None means "the shop does not publish stock" -- never coerce to False.
    # sizeer.com.mk returns its size list with Zaliha = null for every row.
    in_stock: bool | None = None
    stock_qty: int | None = None

    def __post_init__(self) -> None:
        if self.price_minor is not None and self.price_minor < 0:
            raise ValueError(f"negative price for size {self.size_label!r}")


@dataclass(slots=True)
class RawOffer:
    """One merchant's listing of one product, with all its sizes."""

    merchant_slug: str
    merchant_sku: str                    # the shop's own listing id
    raw_title: str
    product_url: str

    raw_mpn: str | None = None           # manufacturer code, verbatim
    raw_brand: str | None = None
    image_url: str | None = None
    currency_code: str = "MKD"

    variants: list[RawVariant] = field(default_factory=list)
    extractors: dict[str, ExtractorTier] = field(default_factory=dict)

    @property
    def min_price_minor(self) -> int | None:
        prices = [v.price_minor for v in self.variants if v.price_minor is not None]
        return min(prices) if prices else None

    @property
    def in_stock_sizes(self) -> list[str]:
        """Sizes we can positively assert are buyable."""
        return [v.size_label for v in self.variants if v.in_stock is True]

    @property
    def stock_is_known(self) -> bool:
        return any(v.in_stock is not None for v in self.variants)

    def quality_issues(self) -> list[str]:
        """Pre-commit validation. The loader rejects a run that trips these."""
        issues: list[str] = []
        if not self.raw_mpn:
            issues.append("missing_mpn")
        if not self.variants:
            issues.append("no_variants")
        if self.min_price_minor in (None, 0):
            issues.append("missing_price")
        if self.variants and not any(v.size_eu is not None for v in self.variants):
            issues.append("no_parsable_size")
        return issues


@dataclass(slots=True)
class ProductCandidate:
    """A catalogue product, as the matcher sees it."""

    product_id: int
    brand_slug: str
    model_name: str
    canonical_name: str
    primary_mpn: str | None = None
    colorway: str | None = None
    gender: str = "unisex"
    identifiers: set[str] = field(default_factory=set)   # normalised MPN/GTIN values


@dataclass(slots=True)
class MatchResult:
    product_id: int | None
    method: str                          # mpn | gtin | merchant_sku | fuzzy | image | manual
    confidence: float
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def is_auto(self) -> bool:
        """Confident enough to link without a human looking at it."""
        return self.product_id is not None and self.confidence >= 0.92

    @property
    def needs_review(self) -> bool:
        return self.product_id is not None and 0.75 <= self.confidence < 0.92
