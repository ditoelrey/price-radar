import Link from "next/link";
import { ImageIcon, Store } from "lucide-react";

import type { ProductCard as ProductCardData } from "@/lib/api";
import { formatMoney, formatSizeEu } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * One product in the grid.
 *
 * The headline is a *from* price, and when a size filter is active it is the
 * cheapest offer **in that size** rather than the product's overall minimum.
 * The card says which, because the two can differ by a lot: the Stan Smith's
 * 4 072 MKD headline comes from a shop with one size in stock, and anyone
 * shopping for EU 44 really pays 6 799.
 */
export function ProductCard({
  product,
  sizeEu,
  size,
}: {
  product: ProductCardData;
  sizeEu?: number;
  /** The letter in force, when the listing is filtered on that axis. */
  size?: string;
}) {
  // The size in force travels to the detail page, whichever axis it is on.
  // Only `sizeEu` did, so clicking a hoodie from a listing filtered to M
  // landed on a page that had forgotten the size.
  const href = sizeEu
    ? `/products/${product.slug}?sizeEu=${sizeEu}`
    : size
      ? `/products/${product.slug}?size=${encodeURIComponent(size)}`
      : `/products/${product.slug}`;

  return (
    <Link
      href={href}
      className={cn(
        "group flex flex-col overflow-hidden rounded-lg border bg-card transition-all",
        "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <div className="relative aspect-square bg-muted/40">
        {product.imageUrl ? (
          // Shop CDNs are many and unpredictable, so this stays a plain <img>
          // rather than next/image: configuring a remote allowlist per shop
          // would break silently every time a new merchant is added.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={product.imageUrl}
            alt=""
            loading="lazy"
            className="size-full object-contain p-4 transition-transform group-hover:scale-[1.03]"
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground/40">
            <ImageIcon className="size-10" />
          </div>
        )}

        {/* "EU 42" for a shoe, a bare "M" for a garment: the letter is not
            an EU measurement and labelling it one is simply wrong. */}
        {product.fromPriceIsSizeSpecific && sizeEu !== undefined && (
          <Badge variant="price" className="absolute left-2 top-2">
            EU {formatSizeEu(sizeEu)}
          </Badge>
        )}
        {product.fromPriceIsSizeSpecific && sizeEu === undefined && size && (
          <Badge variant="price" className="absolute left-2 top-2">
            {size}
          </Badge>
        )}

        {/*
          Opposite corner from the size badge on purpose: a size-filtered page
          shows both at once, and they must never land on top of each other.

          The figure is the best saving any shop advertises on this product,
          so it is a reason to open the card rather than a promise about the
          headline price below -- that price is the cheapest offer, which is
          not always the discounted one.
        */}
        {typeof product.discountPct === "number" && (
          <Badge
            variant="discount"
            className="absolute right-2 top-2 tnum font-semibold shadow-sm"
          >
            −{product.discountPct}%
          </Badge>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-1 border-t p-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {product.brand}
        </p>
        <p className="line-clamp-2 text-sm font-medium leading-snug group-hover:text-primary">
          {product.name}
        </p>

        <div className="mt-auto pt-2">
          {/* "број" is a shoe size and "големина" a garment size; the card
              knows which it is by which list the product filled, since
              nothing carries both. Saying "во вашиот број" over a hoodie is
              the same mismatch the size rail's own heading had. */}
          <p className="text-[11px] text-muted-foreground">
            {product.fromPriceIsSizeSpecific
              ? product.availableSizesEu.length === 0 &&
                product.availableSizes.length > 0
                ? "во вашата големина од"
                : "во вашиот број од"
              : "од"}
          </p>
          <p className="tnum text-lg font-semibold text-price">
            {formatMoney(product.fromPrice)}
          </p>
          <p className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
            <Store className="size-3" />
            {product.merchantCount === 1
              ? "1 продавница"
              : `${product.merchantCount} продавници`}
            {product.offerCount > product.merchantCount &&
              ` · ${product.offerCount} понуди`}
          </p>
        </div>
      </div>
    </Link>
  );
}
