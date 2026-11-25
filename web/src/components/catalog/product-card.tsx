import Link from "next/link";
import { ImageIcon, Store } from "lucide-react";

import type { ProductCard as ProductCardData } from "@/lib/api";
import { formatMoney, formatSizeEu } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { GENDER_LABEL_MK, isFragrance } from "@/lib/navigation";
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

  // Defaulted, not assumed. These arrive from a cached fetch that may
  // predate the field: see the note on `ProductCard` in lib/api.ts.
  const volumes = product.availableVolumesMl ?? [];
  const toPrice = product.toPrice ?? null;

  // A range only where both ends are things the shopper is choosing
  // between: 30ml against 100ml of one fragrance. On a shoe the two ends
  // are two shops, and the dearer one is nobody's option -- the cheapest
  // is the whole answer, which is what "од" has always said.
  //
  // Never on a size-filtered page either: the API sends no maximum there,
  // because the product's overall maximum covers sizes the shopper has
  // just filtered out.
  const showRange =
    isFragrance(product.category) &&
    toPrice !== null &&
    !product.fromPriceIsSizeSpecific;

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
        {/* Two lines reserved, not just allowed.
            `line-clamp-2` caps a long name at two lines; it does not give a
            short one the same height. That is what broke the grid: measured
            on a Killtec search at 1400px, a row of one-line names came out
            371px tall and any row holding a two-line name 390px, so the
            price sat 19px lower on some rows than others. The image box was
            never the cause -- it is `aspect-square` and measured exactly
            227x227 on every card, whatever the photo's shape.
            `lh` is the element's own line-height, so this stays correct if
            the type scale moves. */}
        <p className="line-clamp-2 min-h-[2lh] text-sm font-medium leading-snug group-hover:text-primary">
          {product.name}
        </p>

        {/* The audience, for fragrances only. Two cards reading "Ajmal
            Amaze EDP" at two prices are indistinguishable without it --
            and the name cannot carry it, because stripping the audience
            word is what lets the two shops' titles meet at all. */}
        {isFragrance(product.category) && product.gender && (
          <p className="text-[11px] text-muted-foreground">
            {GENDER_LABEL_MK[product.gender] ?? product.gender}
          </p>
        )}

        {/* Bottle volumes, and only ever the buyable ones -- the rail comes
            from the summary, which filters on stock. An empty rail on a
            fragrance means every bottle is sold out, so nothing is drawn
            rather than an empty row of chips. */}
        {volumes.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-1">
            {volumes.slice(0, 4).map((ml) => (
              <li
                key={ml}
                className="rounded border px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground"
              >
                {ml}ml
              </li>
            ))}
            {volumes.length > 4 && (
              <li className="px-1 py-0.5 text-[10px] text-muted-foreground">
                +{volumes.length - 4}
              </li>
            )}
          </ul>
        )}

        <div className="mt-auto pt-2">
          {/* "број" is a shoe size and "големина" a garment size; the card
              knows which it is by which list the product filled, since
              nothing carries both. Saying "во вашиот број" over a hoodie is
              the same mismatch the size rail's own heading had. */}
          {/* "број" is a shoe size, "големина" a garment one and
              "волумен" a bottle; the card knows which by which list the
              product filled, since nothing carries two. Volumes are tested
              first: a fragrance fills neither of the other two, so without
              this branch it fell through to "во вашиот број" -- your shoe
              number -- over a bottle of perfume. A range needs no "од" at all --
              it states both ends itself, and "од 4.240 – 6.040" reads as
              a mistake. */}
          <p className="text-[11px] text-muted-foreground">
            {product.fromPriceIsSizeSpecific
              ? volumes.length > 0
                ? "во избраниот волумен од"
                : product.availableSizesEu.length === 0 &&
                    product.availableSizes.length > 0
                  ? "во вашата големина од"
                  : "во вашиот број од"
              : showRange
                ? "цена"
                : "од"}
          </p>
          <p className="tnum text-lg font-semibold text-price">
            {formatMoney(product.fromPrice)}
            {showRange && (
              <>
                {" – "}
                {formatMoney(toPrice)}
              </>
            )}
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
