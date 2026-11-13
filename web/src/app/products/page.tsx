import Link from "next/link";
import { ChevronLeft, ChevronRight, SearchX } from "lucide-react";

import { searchProducts } from "@/lib/api";
import { formatSizeEu } from "@/lib/format";
import { FilterSidebar } from "@/components/catalog/filter-sidebar";
import { DEFAULT_SORT, isSortKey } from "@/lib/sort";
import { ProductCard } from "@/components/catalog/product-card";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length > 0 ? v : undefined;
}

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const q = one(params.q);
  const brand = one(params.brand);
  const sizeRaw = one(params.sizeEu);
  const sizeEu = sizeRaw ? Number(sizeRaw) : undefined;
  // Validated against the known keys rather than passed through: an unknown
  // value would otherwise travel to the API to be silently ignored there,
  // and the control would show a selection the listing is not using.
  const sortRaw = one(params.sort);
  const sort = isSortKey(sortRaw) ? sortRaw : DEFAULT_SORT;
  const page = Number(one(params.page) ?? 0) || 0;

  const result = await searchProducts({
    q,
    brand,
    sizeEu: Number.isFinite(sizeEu) ? sizeEu : undefined,
    sort,
    page,
    pageSize: 24,
  });

  // The size rail offers what this result set actually contains, so it never
  // suggests a size that would empty the page.
  const sizes = Array.from(
    new Set(result.items.flatMap((item) => item.availableSizesEu)),
  ).sort((a, b) => a - b);

  const pageHref = (next: number) => {
    const sp = new URLSearchParams();
    if (q) sp.set("q", q);
    if (brand) sp.set("brand", brand);
    if (sizeEu !== undefined) sp.set("sizeEu", String(sizeEu));
    if (sort !== DEFAULT_SORT) sp.set("sort", sort);
    if (next > 0) sp.set("page", String(next));
    const qs = sp.toString();
    return `/products${qs ? `?${qs}` : ""}`;
  };

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader query={q} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              {q ? `Results for “${q}”` : "Патики"}
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {result.items.length === 0
                ? "No products"
                : `${result.items.length}${result.hasMore ? "+" : ""} products`}
              {sizeEu !== undefined && (
                <> · priced for EU {formatSizeEu(sizeEu)}</>
              )}
            </p>
          </div>

          {sizeEu !== undefined && (
            <Badge variant="price" className="h-7 px-3 text-sm">
              Showing prices in EU {formatSizeEu(sizeEu)}
            </Badge>
          )}
        </div>

        <div className="flex flex-col gap-6 lg:flex-row">
          <FilterSidebar
            sizes={sizes}
            sizeEu={sizeEu}
            brand={brand}
            query={q}
            sort={sort}
          />

          <section className="min-w-0 flex-1">
            {result.items.length === 0 ? (
              <div className="grid place-items-center rounded-lg border border-dashed py-20 text-center">
                <SearchX className="mb-3 size-8 text-muted-foreground/50" />
                <p className="font-medium">Nothing matched</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  {sizeEu !== undefined
                    ? `No shop currently lists these products in EU ${formatSizeEu(sizeEu)}. Try clearing the size.`
                    : "Try a different brand, or a shorter search term."}
                </p>
                <Button asChild variant="outline" size="sm" className="mt-4">
                  <Link href="/products">Clear all filters</Link>
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                {result.items.map((product) => (
                  <ProductCard
                    key={product.slug}
                    product={product}
                    sizeEu={sizeEu}
                  />
                ))}
              </div>
            )}

            {(page > 0 || result.hasMore) && (
              <nav className="mt-6 flex items-center justify-between">
                {page > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(page - 1)}>
                      <ChevronLeft /> Previous
                    </Link>
                  </Button>
                ) : (
                  <span />
                )}
                <span className="text-sm text-muted-foreground">
                  Page {page + 1}
                </span>
                {result.hasMore ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(page + 1)}>
                      Next <ChevronRight />
                    </Link>
                  </Button>
                ) : (
                  <span />
                )}
              </nav>
            )}
          </section>
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}
