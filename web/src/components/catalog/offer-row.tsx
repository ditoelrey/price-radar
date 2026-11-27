import { AlertCircle, Check } from "lucide-react";

import type { Offer, OfferVariant } from "@/lib/api";
import {
  discountPercent,
  formatCheckedAt,
  formatMoney,
  formatSizeEu,
  sizeDisplayLabel,
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
  // Only claim "EU" when the EU size is actually known. Sport Vision ships
  // some rows with its own conversion missing, and the pipeline now stores
  // those with a null sizeEu while keeping the shop's printed label. Pasting
  // "EU" in front of that label would put the wrong number back on the page
  // after the ingestion side went to the trouble of removing it.
  const sizeText =
    variant.sizeEu !== null
      ? `EU ${variant.sizeLabel}`
      : sizeDisplayLabel(variant);
  const buyable = variant.stock !== "SOLD_OUT";
  // Some shops take the price down with the stock: megasport publishes none
  // at all once every size of a product is gone. The offer is still worth
  // showing -- "sold out here" is real information, and omitting the shop
  // suggests it never carried the item -- but there is no number to print,
  // and a dash where the headline price goes looks like a loading bug.
  const unpriced = !variant.totalPrice;

  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-4 border-t p-4 transition-colors",
        // Fixed track widths, not `auto`. Each row is its own grid, so
        // auto-sized columns measure their own content: a row whose button
        // reads „Погледни ја понудата" rather than „Види понуда" shifts its
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
              Најниска цена
            </Badge>
          )}
        </div>

        <p className="text-sm text-muted-foreground">
          {!sizeFiltered && availableSizes > 1 ? (
            <>
              <span className="font-medium text-foreground">
                Достапни {availableSizes} од {totalSizes} големини
              </span>{" "}
              · од {sizeText}
            </>
          ) : variant.sizeLabel ? (
            <>
              Големина{" "}
              <span className="font-medium text-foreground">
                {sizeText}
              </span>
            </>
          ) : unpriced ? (
            // Not the same as a one-size article. When a shop sells out it
            // can take the size list down along with the price -- megasport
            // does -- so we hold no sizes for this offer and must not imply
            // it was ever sold as a single size.
            <span className="font-medium text-foreground">
              Големините не се достапни
            </span>
          ) : (
            // dsport lists one-size articles as "BEZ VELICINA"; the pipeline
            // stores those with no size rather than inventing one.
            <span className="font-medium text-foreground">
              Универзална големина
            </span>
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
              <> · Уште {variant.stockQty} на залиха</>
            )}
          </span>
        </p>

        {/* Delivery is gone from this row entirely -- the line that named
            it, the estimate beside it and the price breakdown below. The
            shops publish it inconsistently and the figures we hold for it
            are the least reliable thing on the page; quoting a total built
            on them, and then explaining the build, put the weakest number
            we have in the most prominent place. */}
        {/* Honest UI: the check time sits next to the price, not in a footnote. */}
        <p className="text-xs text-muted-foreground">
          {formatCheckedAt(variant.checkedAt)}
        </p>
      </div>

      {/* --- who sells it ------------------------------------------------- */}
      <div className="hidden justify-center sm:flex">
        <MerchantLogo slug={offer.merchantSlug} name={offer.merchantName} />
      </div>

      {/* --- what you pay, and the way out -------------------------------- */}
      <div className="flex items-center justify-between gap-4 sm:justify-end">
        <div className="text-right">
          <p
            className={cn(
              "tnum whitespace-nowrap font-bold leading-tight",
              unpriced
                ? "text-base font-semibold text-muted-foreground"
                : "text-xl",
            )}
          >
            {unpriced ? "Распродадено" : formatMoney(variant.totalPrice)}
          </p>
          {/* Only the one thing left to say under a price: that there is
              none. The breakdown that used to live here split the total
              into goods and delivery, which is the mention this row no
              longer makes. */}
          {unpriced && (
            <p className="whitespace-nowrap text-xs text-muted-foreground">
              Цената не е достапна
            </p>
          )}
          {discount !== null && (
            <Badge variant="discount" className="mt-1">
              −{discount}% од {formatMoney(variant.listPrice)}
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
            {buyable ? "Види понуда" : "Види сепак"}
          </a>
        </Button>
      </div>
    </div>
  );
}

export function offerVariantsSorted(offer: Offer): OfferVariant[] {
  // Infinity, not 0: a variant with no price is sold out and belongs at the
  // bottom. Coalescing to 0 sorted it to the very top, ahead of every offer
  // a shopper could actually buy.
  return [...offer.variants].sort(
    (a, b) =>
      (a.totalPrice?.amountMinor ?? Number.POSITIVE_INFINITY) -
      (b.totalPrice?.amountMinor ?? Number.POSITIVE_INFINITY),
  );
}

export function formatVariantSize(variant: OfferVariant): string {
  return variant.sizeEu !== null
    ? formatSizeEu(variant.sizeEu)
    : sizeDisplayLabel(variant);
}
