import Link from "next/link";
import { SearchX } from "lucide-react";

import { fetchFacets, searchProducts, type FacetOption } from "@/lib/api";
import { formatSizeEu } from "@/lib/format";
import { ActiveFilters } from "@/components/catalog/active-filters";
import { FilterRail } from "@/components/catalog/filter-rail";
import {
  FilterTransitionProvider,
  PendingGrid,
} from "@/components/catalog/filter-transition";
import {
  MobileFilterBar,
  type SortOption,
} from "@/components/catalog/mobile-filter-bar";
import { SortSelect } from "@/components/catalog/sort-select";
import {
  CONCENTRATIONS,
  GENDER_COLUMNS,
  GENDER_LABEL_MK,
  categoriesFor,
  listingHref,
  listingTitle,
} from "@/lib/navigation";
import {
  GROUP_LABELS,
  type ActiveChip,
  type FilterGroupModel,
  type FilterOption,
  type Filters,
  clearedHref,
  filterHref,
  priceBandLabel,
  audienceOf,
  readList,
  sizeHref,
  tickedGenders,
  toggle,
} from "@/lib/filters";
import { DEFAULT_SORT_LABEL, SORTS, isSortKey } from "@/lib/sort";
import { ProductCard } from "@/components/catalog/product-card";
import { PaginationBar } from "@/components/catalog/pagination-bar";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length > 0 ? v : undefined;
}

/** The letters, as a rung of the ladder rather than as a string. */
function sizeLabel(axis: string, value: string): string {
  if (axis === "eu") return formatSizeEu(Number(value));
  if (axis === "ml") return `${value} ml`;
  return value;
}

/**
 * What a size option writes into the URL.
 *
 * Millilitres keep their unit: the API reads `30ml` as a volume and a bare
 * `30` as a letter, finds no such rung on the ladder, and answers with an
 * empty page. The letters and the EU numbers are already what they are.
 */
function sizeParam(axis: string, value: string): string {
  return axis === "ml" ? `${value}ml` : value;
}

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  // Every group is a list. A single value is a one-element list, so a link
  // written before the multi-select -- a menu leaf, a breadcrumb, anything
  // shared -- still means what it meant.
  const filters: Filters = {
    q: one(params.q),
    // Passed through rather than validated against the taxonomy: an unknown
    // value matches no row and the shopper gets an empty listing, which is
    // the truthful answer, and validating would mean this page kept its own
    // copy of a tree that lives in the database.
    kind: one(params.kind),
    concentration: one(params.concentration),
    // Validated, unlike the rest: an unknown sort would travel to the API to
    // be ignored there while the control showed a choice the page is not
    // using. Undefined is a real state -- the API's own default ordering.
    sort: isSortKey(one(params.sort)) ? one(params.sort) : undefined,
    gender: readList(params.gender),
    category: readList(params.category),
    brand: readList(params.brand),
    shop: readList(params.shop),
    price: readList(params.price),
    sizeEu: readList(params.sizeEu),
    size: readList(params.size),
  } as Filters;
  const page = Number(one(params.page) ?? 0) || 0;

  const query = {
    q: filters.q,
    brand: filters.brand.join(",") || undefined,
    sizeEu: filters.sizeEu.join(",") || undefined,
    size: filters.size.join(",") || undefined,
    kind: filters.kind,
    category: filters.category.join(",") || undefined,
    gender: filters.gender.join(",") || undefined,
    shop: filters.shop.join(",") || undefined,
    price: filters.price.join(",") || undefined,
    concentration: filters.concentration,
  };

  // Together, because the facets do not depend on the page of results and
  // waiting for one before asking for the other would add a round trip to
  // every listing.
  //
  // The facets are asked with the *whole* filter state, including the groups
  // themselves: the API leaves each group's own filter out of that group's
  // count. Asking without them -- which is what the old brand and shop calls
  // did -- gives counts for a page the shopper is not on.
  const [result, facets] = await Promise.all([
    searchProducts({ ...query, sort: filters.sort, page, pageSize: 24 }),
    fetchFacets(query),
  ]);

  // ------------------------------------------------------------ the controls
  // Nouns, because a filter heading names a department rather than
  // describing a product: Мажи, not Машки. Унисекс has no column in the mega
  // menu -- it is not a department a shop opens with -- but it is a real
  // answer here, and on fragrances it is a third of the catalogue.
  const genderLabel = (slug: string) =>
    slug === "unisex"
      ? GENDER_LABEL_MK.unisex
      : (GENDER_COLUMNS.find((g) => g.slug === slug)?.label ?? slug);

  // A bottle's strength is this vertical's product type. `fragrances` is the
  // only leaf there is, so Производи would otherwise offer one option
  // reading "Парфем" over the whole catalogue, while the thing a shopper
  // actually picks between -- EDT, EDP, a parfum -- sat in a menu they had
  // to go back to.
  const isFragrance = filters.kind === "fragrance";
  // The leaf's Macedonian name comes from the API, which reads it from the
  // same column the mega menu's labels were copied from. The menu is the
  // fallback for a leaf the facet named without a translation.
  const menuCategories = categoriesFor(filters.kind);
  const categoryLabel = (slug: string, fallback: string) =>
    menuCategories.find((c) => c.slug === slug)?.label ?? fallback ?? slug;

  // `adults` is in the gender parameter but it is not a department: it is
  // what the Опрема menu sets to mean "not the kids' shelf". It has no box in
  // the control, and ticking a real department replaces it -- `adults,men`
  // would read as "adults OR men", which is every adult product.
  const ticked = tickedGenders(filters);
  const audience = audienceOf(filters);

  const plainOptions = (
    key: "gender" | "category" | "brand" | "shop" | "price",
    rows: FacetOption[] | undefined,
    label: (row: FacetOption) => string,
  ): FilterOption[] =>
    (rows ?? []).map((row) => {
      const current = key === "gender" ? ticked : filters[key];
      const next = toggle(current, row.value);
      return {
        value: row.value,
        label: label(row),
        count: row.productCount,
        selected: current.includes(row.value),
        href: filterHref(filters, {
          // Unticking the last department puts the audience back, so Опрема
          // does not silently become "every age" on the way out.
          [key]:
            key === "gender" && next.length === 0 ? audience : next,
        } as Partial<Filters>),
      };
    });

  /**
   * Производи, the one group that takes a single answer.
   *
   * Two product types at once is a page about nothing in particular: patiki
   * and kopachki have different sizes, different prices and different
   * reasons to be bought, and every shop here makes it a choice too.
   * Clicking the active one clears it and gives the vertical back.
   */
  const productOptions = (): FilterOption[] => {
    if (!isFragrance) {
      return (facets.categories ?? []).map((row) => {
        const selected = filters.category.includes(row.value);
        return {
          value: row.value,
          label: categoryLabel(row.value, row.label),
          count: row.productCount,
          selected,
          href: filterHref(filters, {
            category: selected ? [] : [row.value],
          }),
        };
      });
    }
    // The four the menu offers, counted from the strengths behind them:
    // "Парфеми" is PARFUM, EXTRAIT, ELIXIR and ABSOLU together, because a
    // shopper reading that word does not distinguish them.
    const counted = new Map(
      (facets.concentrations ?? []).map((row) => [row.value, row.productCount]),
    );
    const chosen = new Set(
      (filters.concentration ?? "").split(",").filter(Boolean),
    );
    return CONCENTRATIONS.map((entry) => {
      const members = entry.value.split(",");
      const count = members.reduce(
        (sum, member) => sum + (counted.get(member) ?? 0),
        0,
      );
      const selected =
        chosen.size === members.length &&
        members.every((member) => chosen.has(member));
      return {
        value: entry.value,
        label: entry.short ? `${entry.short} — ${entry.label}` : entry.label,
        count,
        selected,
        href: filterHref(filters, {
          concentration: selected ? undefined : entry.value,
        }),
      };
    }).filter((option) => option.count > 0 || option.selected);
  };

  const sizeOptions = (axis: string): FilterOption[] =>
    (facets.sizes ?? [])
      .filter((row) => row.axis === axis)
      .map((row) => {
        const value = sizeParam(axis, row.value);
        const selected =
          axis === "eu"
            ? filters.sizeEu.some(
                (v) => Math.abs(Number(v) - Number(row.value)) < 0.005,
              )
            : filters.size.includes(value);
        return {
          value,
          label: sizeLabel(axis, row.value),
          count: row.productCount,
          selected,
          href: sizeHref(filters, axis, value),
        };
      });

  const sizeSections = [
    { title: "Број (EU)", options: sizeOptions("eu") },
    { title: "Големина", options: sizeOptions("alpha") },
    { title: "Милилитража", options: sizeOptions("ml") },
  ].filter((section) => section.options.length > 0);

  const products = productOptions();
  const productsChosen = products.some((option) => option.selected);

  const groups: FilterGroupModel[] = [
    // Производи first, because it is the question a shopper answers first:
    // what am I buying. Пол narrows it; on Обувки three quarters of the
    // catalogue is in whichever department they are already in, so opening
    // with it narrows almost nothing.
    {
      key: "category",
      title: GROUP_LABELS.category,
      options: products,
      single: true,
      selectedCount: productsChosen ? 1 : 0,
      // Open when it is still unanswered -- someone who clicked Обувки or
      // Машки обувки lands on the list they came to choose from. Someone who
      // clicked Патики has answered it, and gets the space back.
      open: !productsChosen,
    },
    {
      key: "gender",
      title: GROUP_LABELS.gender,
      options: plainOptions("gender", facets.genders, (row) =>
        genderLabel(row.value),
      ),
      selectedCount: ticked.length,
      open: ticked.length === 0,
    },
    {
      key: "size",
      // A bottle is not a size, it is an amount, and the shops label it so:
      // e-elixir's own attribute is милилитража.
      title: isFragrance ? "Милитража" : GROUP_LABELS.size,
      options: sizeSections.flatMap((section) => section.options),
      sections: sizeSections,
      selectedCount: filters.sizeEu.length + filters.size.length,
    },
    {
      key: "brand",
      title: GROUP_LABELS.brand,
      options: plainOptions("brand", facets.brands, (row) => row.label),
      // The only search box in the sidebar; see `SearchableGroup`.
      search: true,
      selectedCount: filters.brand.length,
    },
    {
      key: "shop",
      title: GROUP_LABELS.shop,
      options: plainOptions("shop", facets.shops, (row) => row.label),
      selectedCount: filters.shop.length,
    },
    {
      key: "price",
      title: GROUP_LABELS.price,
      // The bands are the API's ids and the words are ours, as every other
      // label on this page is.
      options: plainOptions("price", facets.prices, (row) =>
        priceBandLabel(row.value),
      ),
      selectedCount: filters.price.length,
    },
  ];

  // --------------------------------------------------------------- the chips
  const chips: ActiveChip[] = [];
  for (const group of groups) {
    if (group.key === "size") continue;
    for (const option of group.options) {
      if (option.selected) {
        // The option's own href is the one that removes it: ticking and
        // unticking are the same link.
        chips.push({
          key: group.key,
          value: option.value,
          label: option.label,
          href: option.href,
        });
      }
    }
  }
  // A value that is ticked but not among the options still needs a chip. The
  // facet lists what the scope has, so a second category whose products the
  // first filter excluded comes back with no row at all -- and without a chip
  // there is nothing to click to undo it, on a page that is now empty because
  // of it. Same for a slug in a hand-edited or outdated link.
  for (const group of groups) {
    if (group.key === "size") continue;
    // On fragrances Производи is the concentration, which is not one of the
    // lists below -- its options already carry their own remove links, and
    // the menu never writes a strength the facet cannot name.
    if (group.key === "category" && isFragrance) continue;
    const offered = new Set(group.options.map((option) => option.value));
    const key = group.key as "gender" | "category" | "brand" | "shop" | "price";
    for (const value of key === "gender" ? ticked : filters[key]) {
      if (offered.has(value)) continue;
      const next = toggle(key === "gender" ? ticked : filters[key], value);
      chips.push({
        key: group.key,
        value,
        label:
          key === "gender"
            ? genderLabel(value)
            : key === "price"
              ? priceBandLabel(value)
              : key === "category"
                ? categoryLabel(value, value)
                : value,
        href: filterHref(filters, {
          [key]: key === "gender" && next.length === 0 ? audience : next,
        } as Partial<Filters>),
      });
    }
  }

  // Sizes separately, so a rung still ticked on an axis the current result
  // set no longer offers can be taken off. That happens the moment a shopper
  // changes category with a size applied, and without this the only way out
  // is Исчисти сè.
  for (const value of filters.sizeEu) {
    chips.push({
      key: "size",
      value,
      label: `EU ${formatSizeEu(Number(value))}`,
      href: filterHref(filters, { sizeEu: toggle(filters.sizeEu, value) }),
    });
  }
  for (const value of filters.size) {
    chips.push({
      key: "size",
      value,
      label: value,
      href: filterHref(filters, { size: toggle(filters.size, value) }),
    });
  }

  const sortOptions: SortOption[] = SORTS.map((sort) => ({
    value: sort.value,
    label: sort.label,
    selected: filters.sort === sort.value,
    href: filterHref(filters, { sort: sort.value }),
  }));

  const pageHref = (next: number) =>
    listingHref({ ...query, sort: filters.sort, page: next });

  // The EU number a card quotes its price in. One value, where the filter
  // takes several: a card shows one price, and on a page filtered to 42 and
  // 42.5 it is the cheaper of the two -- so the badge names the filter's
  // first rung rather than claiming a size the figure may not be for.
  const firstEu = filters.sizeEu[0] ? Number(filters.sizeEu[0]) : undefined;
  const firstSize = filters.size[0];

  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader query={filters.q} activeKind={filters.kind} />

      {/* Every filter control inside this is a link whose click is run as a
          transition, so the second the server spends rebuilding the listing
          is a second the page can show it is working. See
          `FilterTransitionProvider`. */}
      <FilterTransitionProvider>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              {listingTitle({
                q: filters.q,
                kind: filters.kind,
                category: filters.category,
                gender: filters.gender,
              })}
            </h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {/* The real figure now that the API counts: "165 производи"
                  rather than "24+", which only ever said "a page's worth,
                  and there is more". The `+` form stays as the fallback for
                  a payload cached before `total` existed. */}
              {result.items.length === 0
                ? "Нема производи"
                : result.total !== undefined
                  ? `${result.total} производи`
                  : `${result.items.length}${result.hasMore ? "+" : ""} производи`}
              {firstEu !== undefined && (
                <> · цени за EU {formatSizeEu(firstEu)}</>
              )}
            </p>
          </div>

        </div>

        <MobileFilterBar
          groups={groups}
          chips={chips}
          clearHref={clearedHref(filters)}
          total={result.total}
          sortOptions={sortOptions}
          sortLabel={DEFAULT_SORT_LABEL}
        />

        <div className="flex flex-col gap-6 lg:flex-row">
          <FilterRail groups={groups} />

          <section className="min-w-0 flex-1">
            {/* Chips left, Сортирај right, on one line directly above the
                grid. The control used to sit up in the header, a row and a
                half above the cards it reorders; here it is level with the
                filters it is not one of, and the eye finds both at the top
                edge of the results. Hidden on a phone, where it is the first
                pill in the row above. */}
            <div className="mb-4 flex min-h-9 items-center justify-between gap-3">
              <ActiveFilters chips={chips} clearHref={clearedHref(filters)} />
              <SortSelect
                selected={filters.sort}
                layout="inline"
                className="ml-auto hidden shrink-0 lg:flex"
              />
            </div>

            {result.items.length === 0 ? (
              <div className="grid place-items-center rounded-lg border border-dashed py-20 text-center">
                <SearchX className="mb-3 size-8 text-muted-foreground/50" />
                <p className="font-medium">Нема резултати</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  {firstEu !== undefined
                    ? `Ниту една продавница не ја нуди оваа комбинација во EU ${formatSizeEu(firstEu)}. Пробајте без филтер за број.`
                    : "Пробајте друг бренд или пократок поим за пребарување."}
                </p>
                <Button asChild variant="outline" size="sm" className="mt-4">
                  <Link href={clearedHref(filters)}>Исчисти ги филтрите</Link>
                </Button>
              </div>
            ) : (
              <PendingGrid>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                  {result.items.map((product) => (
                    <ProductCard
                      key={product.slug}
                      product={product}
                      sizeEu={firstEu}
                      size={firstSize}
                    />
                  ))}
                </div>
              </PendingGrid>
            )}

            {/* `total` is what lets the bar number itself and offer the
                last page. Passed through as undefined when the payload
                does not carry it -- a body cached by `fetch` before the API
                served the field -- and the bar then shows previous and next
                only. It used to guess `page + (hasMore ? 2 : 1)` here,
                which on the first page of a 350-page listing drew "1 2" and
                sent the last-page button to page 2. */}
            <PaginationBar
              page={page}
              totalPages={
                result.total !== undefined
                  ? Math.max(1, Math.ceil(result.total / result.pageSize))
                  : undefined
              }
              hasMore={result.hasMore}
              href={pageHref}
            />
          </section>
        </div>
      </main>
      </FilterTransitionProvider>

      <SiteFooter />
    </div>
  );
}
