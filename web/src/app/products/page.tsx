import Link from "next/link";
import { ChevronLeft, ChevronRight, SearchX } from "lucide-react";

import { searchProducts } from "@/lib/api";
import { formatSizeEu } from "@/lib/format";
import { FilterSidebar } from "@/components/catalog/filter-sidebar";
import { byAlphaLadder, listingHref, listingTitle } from "@/lib/navigation";
import { isSortKey } from "@/lib/sort";
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
  // The garment axis. Not validated against the ladder here: an unknown
  // letter matches no row and the shopper gets an empty listing, which is
  // the truthful answer, and validating would mean this page kept its own
  // copy of a vocabulary that lives in the database.
  const size = one(params.size);
  // Validated against the known keys rather than passed through: an unknown
  // value would otherwise travel to the API to be silently ignored there,
  // and the control would show a selection the listing is not using.
  // Undefined, not a fallback value: "no sort chosen" is a real state that
  // the API answers with its own default ordering, and the control has to be
  // able to show that rather than claim a choice the shopper never made.
  const sortRaw = one(params.sort);
  const sort = isSortKey(sortRaw) ? sortRaw : undefined;
  const page = Number(one(params.page) ?? 0) || 0;
  // Passed through rather than validated against a list. An unknown value
  // matches no row and the shopper gets an empty listing, which is the
  // truthful answer; validating here would mean this page kept its own copy
  // of the taxonomy, to be forgotten the next time the tree changes.
  const kind = one(params.kind);
  const category = one(params.category);
  const gender = one(params.gender);

  const filters = {
    q,
    brand,
    sizeEu: Number.isFinite(sizeEu) ? sizeEu : undefined,
    size,
    kind,
    category,
    gender,
    sort,
  };

  const result = await searchProducts({ ...filters, page, pageSize: 24 });

  // The size rail offers what this result set actually contains, so it never
  // suggests a size that would empty the page.
  const sizes = Array.from(
    new Set(result.items.flatMap((item) => item.availableSizesEu)),
  ).sort((a, b) => a - b);
  // Ranked, not sorted and not left as found. Each card's own list arrives
  // in ladder order, but merging 24 of them orders by first appearance --
  // a page opening with an S/M/XL hoodie renders "S M XL L XXL" -- and
  // sorting the strings instead would give 3XL, L, M, S, XL, XS.
  const alphaSizes = Array.from(
    new Set(result.items.flatMap((item) => item.availableSizes)),
  ).sort(byAlphaLadder);

  const pageHref = (next: number) => listingHref({ ...filters, page: next });

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader query={q} activeKind={kind} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              {listingTitle(filters)}
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {result.items.length === 0
                ? "Нема производи"
                : `${result.items.length}${result.hasMore ? "+" : ""} производи`}
              {sizeEu !== undefined && (
                <> · цени за EU {formatSizeEu(sizeEu)}</>
              )}
            </p>
          </div>

          {sizeEu !== undefined && (
            <Badge variant="price" className="h-7 px-3 text-sm">
              Прикажани се цени за EU {formatSizeEu(sizeEu)}
            </Badge>
          )}
        </div>

        <div className="flex flex-col gap-6 lg:flex-row">
          <FilterSidebar
            sizes={sizes}
            alphaSizes={alphaSizes}
            filters={filters}
          />

          <section className="min-w-0 flex-1">
            {result.items.length === 0 ? (
              <div className="grid place-items-center rounded-lg border border-dashed py-20 text-center">
                <SearchX className="mb-3 size-8 text-muted-foreground/50" />
                <p className="font-medium">Нема резултати</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  {sizeEu !== undefined
                    ? `Ниту една продавница не ја нуди оваа комбинација во EU ${formatSizeEu(sizeEu)}. Пробајте без филтер за број.`
                    : "Пробајте друг бренд или пократок поим за пребарување."}
                </p>
                <Button asChild variant="outline" size="sm" className="mt-4">
                  <Link href={listingHref()}>Исчисти ги филтрите</Link>
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                {result.items.map((product) => (
                  <ProductCard
                    key={product.slug}
                    product={product}
                    sizeEu={sizeEu}
                    size={size}
                  />
                ))}
              </div>
            )}

            {(page > 0 || result.hasMore) && (
              <nav className="mt-6 flex items-center justify-between">
                {page > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(page - 1)}>
                      <ChevronLeft /> Претходна
                    </Link>
                  </Button>
                ) : (
                  <span />
                )}
                <span className="text-sm text-muted-foreground">
                  Страница {page + 1}
                </span>
                {result.hasMore ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(page + 1)}>
                      Следна <ChevronRight />
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
