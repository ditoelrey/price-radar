import Link from "next/link";

import { AlphaSizePicker } from "@/components/catalog/alpha-size-picker";
import { SizePicker } from "@/components/catalog/size-picker";
import { SortSelect } from "@/components/catalog/sort-select";
import {
  GENDER_COLUMNS,
  categoriesFor,
  listingHref,
  type GenderSlug,
  type ListingParams,
} from "@/lib/navigation";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

/** The brands seeded in the catalogue, in the order shoppers ask for them. */
const BRANDS = [
  { slug: "adidas", label: "Adidas" },
  { slug: "nike", label: "Nike" },
  { slug: "puma", label: "Puma" },
  { slug: "new-balance", label: "New Balance" },
  { slug: "under-armour", label: "Under Armour" },
  { slug: "reebok", label: "Reebok" },
  { slug: "converse", label: "Converse" },
  { slug: "vans", label: "Vans" },
  { slug: "asics", label: "Asics" },
  { slug: "hoka", label: "Hoka" },
  { slug: "skechers", label: "Skechers" },
  { slug: "jordan", label: "Jordan" },
];

const SHOPS = [
  "Sport Vision",
  "Sport Reality",
  "Buzz Sneakers",
  "Megasport",
  "Sport-M",
  "Sizeer",
];

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
}) {
  const { sizeEu, size, brand, sort, kind, category, gender } = filters;
  const brandHref = (slug: string | null) =>
    listingHref({ ...filters, brand: slug ?? undefined });
  const categoryHref = (slug: string | null) =>
    listingHref({ ...filters, category: slug ?? undefined, page: 0 });
  const genderHref = (slug: string | null) =>
    listingHref({ ...filters, gender: slug ?? undefined, page: 0 });

  // Narrowed by the gender in force, so the women's listing does not offer
  // a men's-only leaf -- and the other way round, which is the case that
  // matters: Градници и топови has no men's stock at all.
  const isGender = (value: string | undefined): value is GenderSlug =>
    GENDER_COLUMNS.some((g) => g.slug === value);
  const categories = categoriesFor(kind, isGender(gender) ? gender : undefined);
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
          {sizes.length === 0 && alphaSizes.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Нема големини во овие резултати.
            </p>
          )}
        </section>

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
            {BRANDS.map((b) => (
              <li key={b.slug}>
                <Link
                  href={brandHref(b.slug)}
                  className={cn(
                    "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                    brand === b.slug
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground",
                  )}
                >
                  {b.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <Separator />

        <section>
          <h2 className="mb-2 text-sm font-semibold">Продавници што ги споредуваме</h2>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {SHOPS.map((shop) => (
              <li key={shop} className="flex items-center gap-2">
                <span className="size-1.5 rounded-full bg-price" />
                {shop}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            Понудите се подредени според вкупна цена со достава — никогаш
            според тоа колку продавницата ни плаќа.
          </p>
        </section>
      </div>
    </aside>
  );
}
