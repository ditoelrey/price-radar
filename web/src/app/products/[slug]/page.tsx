import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ChevronRight, ImageIcon, Info, Store } from "lucide-react";

import { getProduct, type Offer } from "@/lib/api";
import { formatMoney, formatSizeEu, sizeDisplayLabel } from "@/lib/format";
import { OfferRow } from "@/components/catalog/offer-row";
import { LabelSizePicker } from "@/components/catalog/label-size-picker";
import { SizePicker } from "@/components/catalog/size-picker";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { Badge } from "@/components/ui/badge";
import { VERTICALS, listingHref } from "@/lib/navigation";

export const dynamic = "force-dynamic";

type Params = Promise<{ slug: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

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
  const from = product.lowestPrice
    ? ` from ${formatMoney(product.lowestPrice)}`
    : "";
  return {
    title: `${product.name}${from}`,
    description: product.lowestPrice
      ? `Compare ${product.offerCount} offers for the ${product.name} across ${product.merchantCount} shops in North Macedonia. Prices include delivery.`
      : `${product.name} — no shop we compare is listing this product right now.`,
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
function rowsFor(offers: Offer[], sizeEu?: number, size?: string) {
  const rows = offers.flatMap((offer) => {
    // One axis or the other. A variant carries an EU number or a letter,
    // never both, so narrowing on both at once always empties the table.
    const variants =
      sizeEu !== undefined
        ? offer.variants.filter(
            (v) => v.sizeEu !== null && Math.abs(v.sizeEu - sizeEu) < 0.005,
          )
        : size !== undefined
          ? // Matched against the same string the chip shows, which is the
            // canonical letter where there is one and the shop's own label
            // otherwise -- the only form a kids' size has.
            offer.variants.filter((v) => (v.sizeAlpha ?? v.sizeLabel) === size)
          : offer.variants;
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
  const size = one(search.size);

  // Fetched unfiltered on purpose, even when a size is in the URL: the page
  // needs every offer to work out whether the headline price is actually
  // available in that size. The endpoint takes `size` too, for clients that
  // only want the narrowed list.
  const product = await getProduct(slug);
  if (!product) notFound();

  // The vertical this product belongs to, for the breadcrumb's first step.
  // Looked up rather than assumed: an unclassified product has no vertical
  // and gets a plain link to everything instead of a wrong one.
  const vertical = VERTICALS.find((v) => v.kind === product.categoryKind);

  // What every step of the trail below the first one is scoped to.
  //
  // The brand step used to be built by hand -- `/products?brand=` and the
  // display name lower-cased -- which dropped the scope and guessed the
  // slug. Both halves were wrong. `/products` with no `kind` means
  // footwear, so Calvin Klein on a perfume page led to Calvin Klein
  // *trainers*, of which there are none, and Adidas on a hoodie led to
  // Adidas shoes rather than Adidas hoodies.
  //
  // `kind: "all"` where the product has no vertical: an unclassified
  // product's brand link would otherwise fall into the footwear default
  // and claim the brand has nothing, when what we actually know is that we
  // do not know where it belongs.
  const trailScope = {
    kind: vertical?.kind ?? "all",
    category: product.category ?? undefined,
  };
  const rows = rowsFor(product.offers, sizeEu, size);
  const best = rows[0];

  // The headline across all sizes, so the page can say plainly when the
  // advertised price is not available in the size the shopper asked for.
  const overallBest = rowsFor(product.offers)[0];
  const headlineDiffers =
    (sizeEu !== undefined || size !== undefined) &&
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

  // The non-EU sizes: letters for adult garments, age bands for kids'. Shown
  // because the page otherwise listed a price and no sizes at all for every
  // apparel product -- 17 032 offers whose sizes we hold.
  //
  // `numeric` is excluded, and that is the whole filter. It is the sizing
  // parser's catch-all rather than a real system, and on apparel it is
  // almost entirely Sport Vision's template dictionary: every garment page
  // carries NS, 1X, 2XLT, YMD and twenty more the shop never sells. One
  // adidas tee renders 33 sizes that way, of which five are real.
  //
  // Order is the API's, which ranks each system on its own scale -- the
  // ladder for letters, months for ages. Re-sorting here would put "11-12
  // год." before "9-10 год.".
  const labelled = product.offers.flatMap((offer) => offer.variants).filter(
    (v) =>
      v.sizeEu === null &&
      v.sizeSystem !== null &&
      v.sizeSystem !== "numeric",
  );
  const otherSizes: string[] = [];
  const otherInStock = new Set<string>();
  for (const variant of labelled) {
    const label = sizeDisplayLabel(variant);
    if (!otherSizes.includes(label)) otherSizes.push(label);
    if (variant.stock !== "SOLD_OUT") otherInStock.add(label);
  }

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        {/* The trail the product actually sits on. It read "Патики" for
            every product, which on a Puma t-shirt was both wrong and a dead
            end: the link went to all footwear. */}
        <nav className="mb-4 flex items-center gap-1 text-xs text-muted-foreground">
          <Link
            href={listingHref({ kind: trailScope.kind })}
            className="hover:text-foreground"
          >
            {vertical?.label ?? "Производи"}
          </Link>
          <ChevronRight className="size-3" />
          {product.categoryMk && product.category && (
            <>
              <Link
                href={listingHref(trailScope)}
                className="hover:text-foreground"
              >
                {product.categoryMk}
              </Link>
              <ChevronRight className="size-3" />
            </>
          )}
          <Link
            href={listingHref({ ...trailScope, brand: product.brandSlug })}
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
                {/* Counts come from the summary, which a product with no
                    purchasable offer no longer has — so fall back to what is
                    actually on the page rather than printing "0 shops". */}
                {plural(product.merchantCount || rows.length, "shop")} ·{" "}
                {plural(product.offerCount || rows.length, "offer")}
              </span>
            </p>

            <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-2">
              <div>
                <p className="text-xs text-muted-foreground">
                  {!best
                    ? "Currently unavailable"
                    : sizeEu !== undefined
                      ? `Best total in EU ${formatSizeEu(sizeEu)}`
                      : size !== undefined
                        ? `Best total in ${size}`
                        : "Best total price"}
                </p>
                <p className="tnum text-3xl font-bold text-price">
                  {/*
                    best?.totalPrice only -- never falling back to the
                    summary's lowestPrice. That fallback is what printed
                    "8 599 ден." on a product whose only shop had been
                    deactivated: the summary row outlived the offers it was
                    computed from.
                  */}
                  {best ? formatMoney(best.variant.totalPrice) : "No price"}
                </p>
              </div>
              {best && product.highestPrice && product.lowestPrice
                && product.highestPrice.amountMinor
                   > product.lowestPrice.amountMinor && (
                <p className="tnum pb-1 text-sm text-muted-foreground">
                  up to {formatMoney(product.highestPrice)}
                </p>
              )}
            </div>

            {/* The point of the whole size filter, stated outright. */}
            {headlineDiffers && (
              <div className="mt-3 flex items-start gap-2 rounded-md border border-discount/30 bg-discount-muted px-3 py-2 text-sm">
                <Info className="mt-0.5 size-4 shrink-0 text-discount" />
                {/* Says only what is true in every case: the headline
                    belongs to a size the shopper did not pick.
                    
                    It used to say the headline's shop "does not have" that
                    size, which was a guess that held for shoes and broke on
                    fragrances. One perfumery sells a bottle in 30ml, 50ml
                    and 100ml at three prices, so the headline and the
                    filtered price are routinely the same shop -- and the
                    page read "Elixir, which does not have 50ml ... the
                    cheapest is 8.930 at Elixir". */}
                <p>
                  The{" "}
                  <span className="tnum font-semibold">
                    {formatMoney(overallBest.variant.totalPrice)}
                  </span>{" "}
                  headline is for another size. In{" "}
                  {sizeEu !== undefined ? `EU ${formatSizeEu(sizeEu)}` : size}{" "}
                  the cheapest is{" "}
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

            {otherSizes.length > 0 && (
              <div className="mt-5">
                {/* A bottle is sized in millilitres, and the shops call that
                    милилитража -- it is e-elixir's own word for the
                    attribute. "Size" is right for a hoodie and wrong here,
                    where the choice changes the price as well as the fit.
                    Only fragrances: Обувки, Облека and Опрема keep theirs. */}
                <p className="mb-2 text-sm font-semibold">
                  {product.categoryKind === "fragrance"
                    ? "Милилитража"
                    : "Size"}
                </p>
                <LabelSizePicker
                  sizes={otherSizes}
                  selected={size}
                  unavailable={otherSizes.filter((s) => !otherInStock.has(s))}
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
              {sizeEu !== undefined ? (
                <>
                  <p className="font-medium">No offers in this size</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    No shop currently lists EU {formatSizeEu(sizeEu)}.
                  </p>
                  <Link
                    href={`/products/${product.slug}`}
                    className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
                  >
                    Show every size
                  </Link>
                </>
              ) : (
                <>
                  {/*
                    Reachable by direct link: every shop that listed this
                    product is currently unavailable to us, so we have no
                    live price for it. Saying nothing is the honest answer --
                    the alternative is quoting a figure nobody can buy at.
                  */}
                  <p className="font-medium">No current offers</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    None of the shops we compare is listing this product right
                    now. We would rather show nothing than a price you cannot
                    buy at.
                  </p>
                  <Link
                    href="/products"
                    className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
                  >
                    Browse everything else
                  </Link>
                </>
              )}
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
            Последна проверка кај продавниците:{" "}
            {new Date(product.updatedAt).toLocaleString("mk-MK")}
          </p>
        )}
      </main>

      <SiteFooter />
    </div>
  );
}
