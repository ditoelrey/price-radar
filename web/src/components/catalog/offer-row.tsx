import { AlertCircle, Check, Link2, Truck } from "lucide-react";

import type { Offer, OfferVariant } from "@/lib/api";
import {
  discountPercent,
  formatCheckedAt,
  formatMoney,
  formatSizeEu,
  stockLabel,
} from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * One shop's row in the comparison table.
 *
 * Modelled on idealo's offer list with price.com's clearer separation of
 * "item price" from "what you actually pay". Four columns, in the order a
 * shopper reads them: what it is, what it costs in total, who sells it, and
 * the button.
 *
 * The total is the headline figure and the sort key. 2 863 MKD plus 400
 * postage is dearer than 3 000 delivered free, and ranking on the sticker
 * price would mislead on exactly the comparison this page exists to make.
 */
export function OfferRow({
  offer,
  variant,
  rank,
  isBest,
  availableSizes,
  totalSizes,
  sizeFiltered,
}: {
  offer: Offer;
  variant: OfferVariant;
  rank: number;
  isBest: boolean;
  /** Sizes at this shop that are not sold out. */
  availableSizes: number;
  totalSizes: number;
  sizeFiltered: boolean;
}) {
  const stock = stockLabel(variant.stock);
  const discount = discountPercent(variant.price, variant.listPrice);
  const shippingMinor = variant.shipping?.amountMinor ?? 0;
  const buyable = variant.stock !== "SOLD_OUT";

  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-4 border-t p-4 transition-colors sm:grid-cols-[1fr_auto] sm:items-center",
        isBest && "bg-price-muted/50",
      )}
    >
      {/* --- what it is, and who sells it --------------------------------- */}
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tnum grid size-5 shrink-0 place-items-center rounded bg-muted text-[11px] font-semibold text-muted-foreground">
            {rank}
          </span>
          <span className="font-semibold">{offer.merchantName}</span>

          {offer.merchantRating !== null && (
            <span className="tnum text-xs text-muted-foreground">
              ★ {offer.merchantRating.toFixed(1)}
              {offer.merchantReviewCount > 0 &&
                ` (${offer.merchantReviewCount})`}
            </span>
          )}

          {isBest && (
            <Badge variant="price" className="font-semibold">
              Best total price
            </Badge>
          )}

          {offer.sameOperatorAs && (
            // sizeer and sport-m share a platform, a host IP and identical
            // prices. Unlabelled, two rows of the same operator just make the
            // list look padded.
            <Badge
              variant="muted"
              className="gap-1"
              title={`Same operator as ${offer.sameOperatorAs}`}
            >
              <Link2 className="size-3" />
              same operator as {offer.sameOperatorAs}
            </Badge>
          )}
        </div>

        <p className="text-sm text-muted-foreground">
          {!sizeFiltered && availableSizes > 1 ? (
            <>
              <span className="font-medium text-foreground">
                {availableSizes} of {totalSizes} sizes
              </span>{" "}
              available · from EU {variant.sizeLabel}
            </>
          ) : variant.sizeLabel ? (
            <>
              Size <span className="font-medium text-foreground">EU {variant.sizeLabel}</span>
            </>
          ) : (
            "One size"
          )}
          {" · "}
          <span
            className={cn(
              "font-medium",
              stock.tone === "good" && "text-price",
              stock.tone === "bad" && "text-destructive",
              stock.tone === "unknown" && "text-muted-foreground",
            )}
          >
            {stock.tone === "good" && <Check className="mr-0.5 inline size-3" />}
            {stock.tone === "unknown" && (
              <AlertCircle className="mr-0.5 inline size-3" />
            )}
            {stock.text}
            {variant.stockQty !== null && variant.stockQty > 0 && (
              <> · {variant.stockQty} left</>
            )}
          </span>
        </p>

        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Truck className="size-3" />
            {shippingMinor === 0
              ? "Free delivery"
              : `+ ${formatMoney(variant.shipping)} delivery`}
            {offer.deliveryEstimate && ` · ${offer.deliveryEstimate}`}
          </span>
          {/* Honest UI: the check time sits next to the price, not in a footnote. */}
          <span>{formatCheckedAt(variant.checkedAt)}</span>
        </p>
      </div>

      {/* --- what you pay, and the way out -------------------------------- */}
      <div className="flex items-center justify-between gap-4 sm:justify-end">
        <div className="text-right">
          <p className="tnum text-xl font-bold leading-tight">
            {formatMoney(variant.totalPrice)}
          </p>
          <p className="tnum text-xs text-muted-foreground">
            {shippingMinor === 0 ? (
              <>{formatMoney(variant.price)} · delivery included</>
            ) : (
              <>
                {formatMoney(variant.price)} + {formatMoney(variant.shipping)}
              </>
            )}
          </p>
          {discount !== null && (
            <Badge variant="discount" className="mt-1">
              −{discount}% vs {formatMoney(variant.listPrice)}
            </Badge>
          )}
        </div>

        <Button
          asChild
          variant={isBest ? "buy" : "outline"}
          className="shrink-0"
          size="lg"
        >
          {/*
            Always our own /out/{id}: the click is logged before the redirect,
            and it is what makes the offer billable. rel="sponsored nofollow"
            because these are commercial outbound links.
          */}
          <a
            href={variant.outUrl}
            rel="sponsored nofollow noopener"
            target="_blank"
          >
            {buyable ? "Go to shop" : "View anyway"}
          </a>
        </Button>
      </div>
    </div>
  );
}

export function offerVariantsSorted(offer: Offer): OfferVariant[] {
  return [...offer.variants].sort(
    (a, b) => (a.totalPrice?.amountMinor ?? 0) - (b.totalPrice?.amountMinor ?? 0),
  );
}

export function formatVariantSize(variant: OfferVariant): string {
  return variant.sizeEu !== null ? formatSizeEu(variant.sizeEu) : variant.sizeLabel;
}
