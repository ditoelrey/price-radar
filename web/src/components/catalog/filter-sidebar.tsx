import Link from "next/link";

import { SizePicker } from "@/components/catalog/size-picker";
import { SortSelect } from "@/components/catalog/sort-select";
import { listingHref, type ListingParams } from "@/lib/navigation";
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
  filters,
}: {
  sizes: number[];
  /**
   * The listing's whole filter state, passed as one object rather than as
   * loose props. These hrefs are rebuilt from scratch, so anything not
   * carried here is silently dropped the moment a shopper picks a brand --
   * which is what used to happen, and what would have happened again to the
   * category and gender the mega menu sets.
   */
  filters: ListingParams;
}) {
  const { sizeEu, brand, sort } = filters;
  const brandHref = (slug: string | null) =>
    listingHref({ ...filters, brand: slug ?? undefined });

  return (
    <aside className="w-full shrink-0 lg:w-64">
      <div className="space-y-5 rounded-lg border bg-card p-4">
        <SortSelect selected={sort} />

        <Separator />

        <section>
          <h2 className="mb-1 text-sm font-semibold">Вашиот број</h2>
          <p className="mb-3 text-xs text-muted-foreground">
            Изберете број и секоја цена станува цената што навистина би ја
            платиле во тој број.
          </p>
          {sizes.length > 0 ? (
            <SizePicker sizes={sizes} selected={sizeEu} />
          ) : (
            <p className="text-xs text-muted-foreground">
              Нема броеви во овие резултати.
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
