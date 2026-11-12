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
import { MerchantLogo } from "@/components/catalog/merchant-logo";
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
  // Only claim "EU" when the EU size is actually known. Sport Vision ships
  // some rows with its own conversion missing, and the pipeline now stores
  // those with a null sizeEu while keeping the shop's printed label. Pasting
  // "EU" in front of that label would put the wrong number back on the page
  // after the ingestion side went to the trouble of removing it.
  const sizeText =
    variant.sizeEu !== null ? `EU ${variant.sizeLabel}` : variant.sizeLabel;
  const buyable = variant.stock !== "SOLD_OUT";

  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-4 border-t p-4 transition-colors",
        // Fixed track widths, not `auto`. Each row is its own grid, so
        // auto-sized columns measure their own content: a row whose
        // button reads "View anyway" rather than "Go to shop" shifts its
        // neighbours, and the logo column stops being a column. Measured
        // at 1.6px of drift between rows before pinning these.
        "sm:grid-cols-[minmax(0,1fr)_7rem_20rem] sm:items-center sm:gap-8",
        isBest && "bg-price-muted/50",
      )}
    >
      {/* --- what it is, and who sells it --------------------------------- */}
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tnum grid size-5 shrink-0 place-items-center rounded bg-muted text-[11px] font-semibold text-muted-foreground">
            {rank}
          </span>
          <MerchantLogo
            slug={offer.merchantSlug}
            name={offer.merchantName}
            className="h-6 w-20 sm:hidden"
          />
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
              available · from {sizeText}
            </>
          ) : variant.sizeLabel ? (
            <>
              Size{" "}
              <span className="font-medium text-foreground">
                {sizeText}
              </span>
            </>
          ) : (
            // dsport lists one-size articles as "BEZ VELICINA"; the pipeline
            // stores those with no size rather than inventing one.
            <span className="font-medium text-foreground">One size</span>
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

      {/* --- who sells it ------------------------------------------------- */}
      <div className="hidden justify-center sm:flex">
        <MerchantLogo slug={offer.merchantSlug} name={offer.merchantName} />
      </div>

      {/* --- what you pay, and the way out -------------------------------- */}
      <div className="flex items-center justify-between gap-4 sm:justify-end">
        <div className="text-right">
          <p className="tnum whitespace-nowrap text-xl font-bold leading-tight">
            {formatMoney(variant.totalPrice)}
          </p>
          <p className="whitespace-nowrap text-xs text-muted-foreground">
            {/*
              When delivery is free the total IS the price, so repeating the
              number here said nothing and made this block wide enough to
              overflow its grid track and crowd the logo. The breakdown is
              only worth showing when there is actually something to break
              down.
            */}
            {shippingMinor === 0 ? (
              "delivery included"
            ) : (
              <span className="tnum">
                {formatMoney(variant.price)} + {formatMoney(variant.shipping)}
              </span>
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
