import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ChevronRight, ImageIcon, Info, Store } from "lucide-react";

import { getProduct, type Offer } from "@/lib/api";
import { formatMoney, formatSizeEu } from "@/lib/format";
import { OfferRow } from "@/components/catalog/offer-row";
import { SizePicker } from "@/components/catalog/size-picker";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { Badge } from "@/components/ui/badge";

export const dynamic = "force-dynamic";

type Params = Promise<{ slug: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length > 0 ? v : undefined;
}

export async function generateMetadata({
  params,
}: {
  params: Params;
}): Promise<Metadata> {
  const { slug } = await params;
  const product = await getProduct(slug);
  if (!product) return { title: "Product not found" };
  const from = product.lowestPrice ? ` from ${formatMoney(product.lowestPrice)}` : "";
  return {
    title: `${product.name}${from}`,
    description: `Compare ${product.offerCount} offers for the ${product.name} across ${product.merchantCount} shops in North Macedonia. Prices include delivery.`,
  };
}

/**
 * One row per shop, cheapest total first.
 *
 * Two decisions here, both learned from looking at the rendered page:
 *
 * **One row per shop, not per size.** Buzz carries this shoe in 30 sizes at
 * one price, so a row per size buried every other shop under thirty
 * near-identical lines.
 *
 * **The representative variant must be buyable.** Sorting purely on price
 * made the top row "Best total price — EU 35.5 — Sold out": true, useless,
 * and precisely the bait the site exists to prevent. Each shop is now
 * represented by its cheapest variant that is not sold out, falling back to
 * its cheapest overall only when nothing is available, in which case the row
 * reads honestly as sold out.
 */
function rowsFor(offers: Offer[], sizeEu?: number) {
  const rows = offers.flatMap((offer) => {
    const variants =
      sizeEu === undefined
        ? offer.variants
        : offer.variants.filter(
            (v) => v.sizeEu !== null && Math.abs(v.sizeEu - sizeEu) < 0.005,
          );
    if (variants.length === 0) return [];

    const byPrice = [...variants].sort(
      (a, b) =>
        (a.totalPrice?.amountMinor ?? Number.MAX_SAFE_INTEGER) -
        (b.totalPrice?.amountMinor ?? Number.MAX_SAFE_INTEGER),
    );
    const buyable = byPrice.filter((v) => v.stock !== "SOLD_OUT");
    const variant = buyable[0] ?? byPrice[0];

    return [
      {
        offer,
        variant,
        availableSizes: buyable.length,
        totalSizes: variants.length,
      },
    ];
  });

  // How much we can vouch for an offer, used only to break a price tie.
  const confidence = (stock: string) =>
    stock === "IN_STOCK" ? 0 : stock === "STALE" ? 1 : 2;

  return rows.sort((a, b) => {
    // A shop with nothing buyable sinks below one that has stock, whatever
    // its sticker says.
    const aOut = a.availableSizes === 0 ? 1 : 0;
    const bOut = b.availableSizes === 0 ? 1 : 0;
    if (aOut !== bOut) return aOut - bOut;

    const byPrice =
      (a.variant.totalPrice?.amountMinor ?? Number.MAX_SAFE_INTEGER) -
      (b.variant.totalPrice?.amountMinor ?? Number.MAX_SAFE_INTEGER);
    if (byPrice !== 0) return byPrice;

    // Identical totals: prefer the shop that actually confirms stock.
    // sizeer and sport-m quote the same price for the Stan Smith, and sizeer
    // publishes no availability at all — crowning the unconfirmed one "best
    // total price" would send shoppers to the weaker of two identical offers.
    return confidence(a.variant.stock) - confidence(b.variant.stock);
  });
}

export default async function ProductDetailPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Search;
}) {
  const { slug } = await params;
  const search = await searchParams;
  const sizeRaw = one(search.sizeEu);
  const sizeEu = sizeRaw ? Number(sizeRaw) : undefined;

  const product = await getProduct(slug);
  if (!product) notFound();

  const rows = rowsFor(product.offers, sizeEu);
  const best = rows[0];

  // The headline across all sizes, so the page can say plainly when the
  // advertised price is not available in the size the shopper asked for.
  const overallBest = rowsFor(product.offers)[0];
  const headlineDiffers =
    sizeEu !== undefined &&
    best &&
    overallBest &&
    best.variant.totalPrice &&
    overallBest.variant.totalPrice &&
    best.variant.totalPrice.amountMinor >
      overallBest.variant.totalPrice.amountMinor;

  const sizesWithStock = new Set(
    product.offers.flatMap((offer) =>
      offer.variants
        .filter((v) => v.stock !== "SOLD_OUT" && v.sizeEu !== null)
        .map((v) => v.sizeEu as number),
    ),
  );
  const allSizes = Array.from(
    new Set(
      product.offers.flatMap((offer) =>
        offer.variants.filter((v) => v.sizeEu !== null).map((v) => v.sizeEu as number),
      ),
    ),
  ).sort((a, b) => a - b);

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <nav className="mb-4 flex items-center gap-1 text-xs text-muted-foreground">
          <Link href="/products" className="hover:text-foreground">
            Патики
          </Link>
          <ChevronRight className="size-3" />
          <Link
            href={`/products?brand=${product.brand.toLowerCase().replace(/\s+/g, "-")}`}
            className="hover:text-foreground"
          >
            {product.brand}
          </Link>
          <ChevronRight className="size-3" />
          <span className="text-foreground">{product.name}</span>
        </nav>

        {/* ---------- header ---------- */}
        <div className="grid gap-6 rounded-lg border bg-card p-5 md:grid-cols-[260px_1fr]">
          <div className="grid aspect-square place-items-center rounded-md bg-muted/40">
            {product.imageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={product.imageUrl}
                alt={product.name}
                className="size-full object-contain p-4"
              />
            ) : (
              <ImageIcon className="size-12 text-muted-foreground/40" />
            )}
          </div>

          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {product.brand}
            </p>
            <h1 className="mt-0.5 text-2xl font-bold tracking-tight">
              {product.name}
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              {product.colorway && <span>{product.colorway}</span>}
              {product.mpn && (
                <span className="tnum">Art. {product.mpn}</span>
              )}
              <span className="inline-flex items-center gap-1">
                <Store className="size-3.5" />
                {product.merchantCount} shops · {product.offerCount} offers
              </span>
            </p>

            <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-2">
              <div>
                <p className="text-xs text-muted-foreground">
                  {sizeEu !== undefined
                    ? `Best total in EU ${formatSizeEu(sizeEu)}`
                    : "Best total price"}
                </p>
                <p className="tnum text-3xl font-bold text-price">
                  {formatMoney(best?.variant.totalPrice ?? product.lowestPrice)}
                </p>
              </div>
              {product.highestPrice && product.lowestPrice && (
                <p className="tnum pb-1 text-sm text-muted-foreground">
                  up to {formatMoney(product.highestPrice)}
                </p>
              )}
            </div>

            {/* The point of the whole size filter, stated outright. */}
            {headlineDiffers && (
              <div className="mt-3 flex items-start gap-2 rounded-md border border-discount/30 bg-discount-muted px-3 py-2 text-sm">
                <Info className="mt-0.5 size-4 shrink-0 text-discount" />
                <p>
                  The{" "}
                  <span className="tnum font-semibold">
                    {formatMoney(overallBest.variant.totalPrice)}
                  </span>{" "}
                  headline is from {overallBest.offer.merchantName}, which does
                  not have EU {formatSizeEu(sizeEu!)}. In your size the cheapest
                  is{" "}
                  <span className="tnum font-semibold">
                    {formatMoney(best.variant.totalPrice)}
                  </span>{" "}
                  at {best.offer.merchantName}.
                </p>
              </div>
            )}

            {allSizes.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-sm font-semibold">
                  Size <span className="font-normal text-muted-foreground">(EU)</span>
                </p>
                <SizePicker
                  sizes={allSizes}
                  selected={sizeEu}
                  unavailable={allSizes.filter((s) => !sizesWithStock.has(s))}
                />
              </div>
            )}
          </div>
        </div>

        {/* ---------- comparison table ---------- */}
        <section className="mt-6 overflow-hidden rounded-lg border bg-card">
          <header className="flex flex-wrap items-baseline justify-between gap-2 p-4">
            <h2 className="text-lg font-semibold">Price comparison</h2>
            <p className="text-xs text-muted-foreground">
              Sorted by total price, delivery included
              {sizeEu !== undefined && <> · EU {formatSizeEu(sizeEu)} only</>}
            </p>
          </header>

          {rows.length === 0 ? (
            <div className="border-t p-8 text-center">
              <p className="font-medium">No offers in this size</p>
              <p className="mt-1 text-sm text-muted-foreground">
                No shop currently lists EU {formatSizeEu(sizeEu!)}.
              </p>
              <Link
                href={`/products/${product.slug}`}
                className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
              >
                Show every size
              </Link>
            </div>
          ) : (
            rows.map((row, index) => (
              <OfferRow
                key={row.offer.id}
                offer={row.offer}
                variant={row.variant}
                rank={index + 1}
                isBest={index === 0 && row.availableSizes > 0}
                availableSizes={row.availableSizes}
                totalSizes={row.totalSizes}
                sizeFiltered={sizeEu !== undefined}
              />
            ))
          )}

          <p className="flex items-start gap-2 border-t bg-muted/30 p-4 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            {product.priceDisclaimer}
          </p>
        </section>

        {product.updatedAt && (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            Catalogue entry last refreshed{" "}
            {new Date(product.updatedAt).toLocaleString("mk-MK")}
          </p>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
