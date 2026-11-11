import Link from "next/link";

import { SizePicker } from "@/components/catalog/size-picker";
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
  sizeEu,
  brand,
  query,
}: {
  sizes: number[];
  sizeEu?: number;
  brand?: string;
  query?: string;
}) {
  const brandHref = (slug: string | null) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (sizeEu !== undefined) params.set("sizeEu", String(sizeEu));
    if (slug) params.set("brand", slug);
    const qs = params.toString();
    return `/products${qs ? `?${qs}` : ""}`;
  };

  return (
    <aside className="w-full shrink-0 lg:w-64">
      <div className="space-y-5 rounded-lg border bg-card p-4">
        <section>
          <h2 className="mb-1 text-sm font-semibold">Your size</h2>
          <p className="mb-3 text-xs text-muted-foreground">
            Pick a size and every price becomes the price you would actually
            pay in it.
          </p>
          {sizes.length > 0 ? (
            <SizePicker sizes={sizes} selected={sizeEu} />
          ) : (
            <p className="text-xs text-muted-foreground">
              No sizes in this result set.
            </p>
          )}
        </section>

        <Separator />

        <section>
          <h2 className="mb-2 text-sm font-semibold">Brand</h2>
          <ul className="space-y-0.5">
            <li>
              <Link
                href={brandHref(null)}
                className={cn(
                  "block rounded-md px-2 py-1 text-sm transition-colors hover:bg-accent",
                  !brand && "bg-accent font-medium",
                )}
              >
                All brands
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
          <h2 className="mb-2 text-sm font-semibold">Shops we compare</h2>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {SHOPS.map((shop) => (
              <li key={shop} className="flex items-center gap-2">
                <span className="size-1.5 rounded-full bg-price" />
                {shop}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            Offers are ranked by total price including delivery — never by what
            a shop pays us.
          </p>
        </section>
      </div>
    </aside>
  );
}
