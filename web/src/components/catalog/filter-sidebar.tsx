import Link from "next/link";

import { AlphaSizePicker } from "@/components/catalog/alpha-size-picker";
import { SizePicker } from "@/components/catalog/size-picker";
import { SortSelect } from "@/components/catalog/sort-select";
import {
  GENDER_COLUMNS,
  type AudienceSlug,
  categoriesFor,
  listingHref,
  type ListingParams,
} from "@/lib/navigation";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

/*
 * The brand list used to live here, as twelve sneaker brands in the order
 * shoppers asked for them. That was right while the catalogue was shoes.
 *
 * It became wrong in both directions at once. Hoka and Jordan were offered
 * on the Облека and Опрема listings, where they have nothing, so a
 * shopper clicking one got an empty page and concluded the site was broken.
 * And Парфеми offered none of the brands it carries -- Ajmal, Lattafa,
 * Dolce & Gabbana -- so the filter was useless in the one vertical where a
 * shopper is most likely to arrive knowing the brand they want.
 *
 * The brands now come from `GET /api/v1/brands`, asked with this listing's
 * own filters minus the brand itself. The facet and the page it leads to
 * therefore cannot disagree.
 */

/*
 * The shop rail had the same disease as the brand list above, and it
 * survived the fix because it looked like a static fact about the site
 * rather than a filter. It was six sneaker shops, hardcoded, on every
 * listing -- so Машки парфеми told a shopper we compare Sport Vision,
 * Sport Reality, Buzz Sneakers, Megasport, Sport-M and Sizeer, none of
 * which sells perfume, while naming neither shop its offers came from.
 *
 * It now comes from `GET /api/v1/merchants`, asked with this listing's own
 * filters, so the rail cannot claim a comparison the page does not make.
 */

/**
 * Left rail, as in the references.
 *
 * Size comes first and is the only filter given real estate above the fold.
 * It is the one control that changes what the prices on the page *mean*,
 * rather than merely narrowing which rows are shown.
 */
export function FilterSidebar({
  sizes,
  alphaSizes,
  filters,
  volumes,
  brandFacets,
  merchantFacets,
}: {
  sizes: number[];
  /**
   * Letter sizes present in this result set, in ladder order. Garments fill
   * this and shoes fill `sizes`; a mixed result -- a search across both
   * verticals -- can fill both, and then both rails are drawn, because
   * hiding one would silently drop half the results from the filter.
   */
  alphaSizes: string[];
  /**
   * The listing's whole filter state, passed as one object rather than as
   * loose props. These hrefs are rebuilt from scratch, so anything not
   * carried here is silently dropped the moment a shopper picks a brand --
   * which is what used to happen, and what would have happened again to the
   * category and gender the mega menu sets.
   */
  filters: ListingParams;
  /**
   * Bottle volumes in millilitres present in this result set, smallest
   * first. The third size axis, and like the other two it only ever offers
   * what the page actually contains.
   */
  volumes?: number[];
  /**
   * Brands with products under the current scope, commonest first.
   *
   * Empty is a real state and renders no section at all: either the scope
   * genuinely has nothing, or the facet call failed. Both are better served
   * by an absent filter than by a list of brands whose pages are empty.
   */
  brandFacets?: ReadonlyArray<{
    slug: string;
    name: string;
    productCount: number;
  }>;
  /**
   * The shops this listing compares, biggest first.
   *
   * Empty renders no section, like `brandFacets`. The heading claims
   * something -- that these are the shops we compare here -- so an empty
   * list must print nothing rather than a heading over nothing, and a
   * failed facet call must not fall back to a guess. Guessing is what the
   * old fixed array did.
   */
  merchantFacets?: ReadonlyArray<{
    slug: string;
    name: string;
    productCount: number;
  }>;
}) {
  const { sizeEu, size, brand, sort, kind, category, gender } = filters;
  const brands = brandFacets ?? [];
  const shops = merchantFacets ?? [];
  // Rendered with the unit. The picker takes strings and writes them into
  // `?size=` verbatim, which is exactly what the API wants to read back.
  const volumeLabels = (volumes ?? []).map((ml) => `${ml}ml`);
  const brandHref = (slug: string | null) =>
    listingHref({ ...filters, brand: slug ?? undefined });
  const categoryHref = (slug: string | null) =>
    listingHref({ ...filters, category: slug ?? undefined, page: 0 });
  const genderHref = (slug: string | null) =>
    listingHref({ ...filters, gender: slug ?? undefined, page: 0 });

  // Narrowed by the gender in force, so the women's listing does not offer
  // a men's-only leaf -- and the other way round, which is the case that
  // matters: Градници и топови has no men's stock at all.
  // `adults` belongs here too, and not only the three departments: it is
  // what the Опрема menu's general column sends, and without it the rail
  // offered Ролери и тротинети on an adults page -- a kids-only leaf whose
  // adult listing holds one product.
  const isAudience = (value: string | undefined): value is AudienceSlug =>
    value === "adults" || GENDER_COLUMNS.some((g) => g.slug === value);
  const categories = categoriesFor(
    kind,
    isAudience(gender) ? gender : undefined,
  );
  const activeGender = GENDER_COLUMNS.find((g) => g.slug === gender);

  return (
    <aside className="w-full shrink-0 lg:w-64">
      <div className="space-y-5 rounded-lg border bg-card p-4">
        <SortSelect selected={sort} />

        {categories.length > 0 && (
          <>
            <Separator />

            {/* Above size and brand, because these two decide what the page
                is while the others only narrow it. Rendered only for a
                vertical that has leaves, so a search-results page -- which
                has no kind -- is not given a category rail belonging to
                whichever vertical we guessed. */}
            <section>
              <h2 className="mb-2 text-sm font-semibold">Оддел</h2>
              <ul className="mb-4 space-y-0.5">
                <li>
                  <Link
                    href={genderHref(null)}
                    className={cn(
                      "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                      !activeGender && "bg-accent font-medium",
                    )}
                  >
                    Сите
                  </Link>
                </li>
                {GENDER_COLUMNS.map((g) => (
                  <li key={g.slug}>
                    <Link
                      href={genderHref(g.slug)}
                      className={cn(
                        "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                        gender === g.slug
                          ? "bg-primary/10 font-medium text-primary"
                          : "text-muted-foreground",
                      )}
                    >
                      {g.label}
                    </Link>
                  </li>
                ))}
              </ul>

              <h2 className="mb-2 text-sm font-semibold">Категорија</h2>
              <ul className="space-y-0.5">
                <li>
                  <Link
                    href={categoryHref(null)}
                    className={cn(
                      "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                      !category && "bg-accent font-medium",
                    )}
                  >
                    Сите категории
                  </Link>
                </li>
                {categories.map((c) => (
                  <li key={c.slug}>
                    <Link
                      href={categoryHref(c.slug)}
                      className={cn(
                        "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                        category === c.slug
                          ? "bg-primary/10 font-medium text-primary"
                          : "text-muted-foreground",
                      )}
                    >
                      {c.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        {/* Hidden outright when neither rail has anything, rather than
            showing a heading over a note saying there is nothing. On a
            fragrance listing that note was also untrue: those products are
            sized, in millilitres, and every card shows the chips. The rail
            cannot offer them yet -- the API's size filter walks the letter
            ladder and a volume has no rung on it, so the link would lead to
            an empty page. */}
        {(sizes.length > 0 || alphaSizes.length > 0) && (
          <>
        <Separator />

        <section>
          {/* The heading names whichever axis this result set is on. It read
              "Вашиот број" over every listing, which is the right word for a
              shoe and the wrong one for a hoodie -- and on an apparel page it
              sat above "Нема броеви во овие резултати", because the rail only
              ever read EU numbers. */}
          <h2 className="mb-1 text-sm font-semibold">
            {sizes.length === 0 && alphaSizes.length > 0
              ? "Вашата големина"
              : "Вашиот број"}
          </h2>
          <p className="mb-3 text-xs text-muted-foreground">
            Изберете и секоја цена станува цената што навистина би ја платиле
            во таа големина.
          </p>
          {sizes.length > 0 && (
            <SizePicker sizes={sizes} selected={sizeEu} />
          )}
          {alphaSizes.length > 0 && (
            <AlphaSizePicker
              sizes={alphaSizes}
              selected={size}
              className={sizes.length > 0 ? "mt-2" : undefined}
            />
          )}
        </section>
          </>
        )}

        {volumeLabels.length > 0 && (
          <>
            <Separator />

            <section>
              {/* Its own rail rather than a third case inside the size one.
                  The other two answer "what fits you"; this answers "how
                  much of it do you want", which is a different question a
                  shopper asks for a different reason -- and the price moves
                  with it, where a shoe costs the same in 42 as in 43. */}
              {/* The same word the detail page uses, and the one the shops
                  use themselves -- e-elixir's own attribute is милилитража.
                  Two words for one axis would read as two filters. */}
              <h2 className="mb-1 text-sm font-semibold">Милилитража</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Секоја милилитража има своја цена — изберете ја вашата и
                цените се однесуваат на неа.
              </p>
              <AlphaSizePicker sizes={volumeLabels} selected={size} />
            </section>
          </>
        )}

        {brands.length > 0 && (
          <>
            <Separator />

            <section>
              <h2 className="mb-2 text-sm font-semibold">Бренд</h2>
              <ul className="space-y-0.5">
                <li>
                  <Link
                    href={brandHref(null)}
                    className={cn(
                      "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                      !brand && "bg-accent font-medium",
                    )}
                  >
                    Сите брендови
                  </Link>
                </li>
                {brands.map((b) => (
                  <li key={b.slug}>
                    <Link
                      href={brandHref(b.slug)}
                      className={cn(
                        "flex items-baseline justify-between gap-2 rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                        brand === b.slug
                          ? "bg-primary/10 font-medium text-primary"
                          : "text-muted-foreground",
                      )}
                    >
                      <span className="truncate">{b.name}</span>
                      {/* The count is the facet's promise: this many
                          products, under exactly these filters. */}
                      <span className="shrink-0 text-[11px] tabular-nums opacity-60">
                        {b.productCount}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        {shops.length > 0 && (
          <>
            <Separator />

            <section>
              <h2 className="mb-2 text-sm font-semibold">
                Продавници што ги споредуваме
              </h2>
              <ul className="space-y-1 text-xs text-muted-foreground">
                {shops.map((shop) => (
                  <li key={shop.slug} className="flex items-center gap-2">
                    <span className="size-1.5 rounded-full bg-price" />
                    {shop.name}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
                Понудите се подредени според вкупна цена со достава — никогаш
                според тоа колку продавницата ни плаќа.
              </p>
            </section>
          </>
        )}
      </div>
    </aside>
  );
}
