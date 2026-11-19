"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The letter-size grid, the garment counterpart of {@link SizePicker}.
 *
 * A separate component rather than a generic one taking `number | string`.
 * The two rails look alike and behave differently in every detail that
 * matters: this one writes `?size=`, has no fractional tolerance to apply
 * when deciding what is selected, needs no `formatSizeEu`, and must never
 * sort what it is given — the API returns the ladder in order, and sorting
 * these as strings produces 3XL, L, M, S, XL, XS. Folding both into one
 * component meant four conditionals in a control whose whole job is to be
 * unambiguous.
 *
 * Each chip is a real `<Link>`, so filtering stays a navigation: shareable,
 * bookmarkable and server-rendered, with no client state to drift.
 */
export function AlphaSizePicker({
  sizes,
  selected,
  className,
}: {
  /** Already in ladder order. Rendered as given. */
  sizes: string[];
  selected?: string;
  className?: string;
}) {
  const pathname = usePathname();
  const params = useSearchParams();

  const href = (size: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (size === null) {
      next.delete("size");
    } else {
      next.set("size", size);
      // The other axis cannot survive this click. A shopper arriving from a
      // footwear listing with ?sizeEu=42 still in the URL would otherwise ask
      // for a hoodie that is both EU 42 and size M, and get an empty page.
      next.delete("sizeEu");
    }
    // Any filter change resets paging; staying on page 4 of the old result
    // set is never what someone meant.
    next.delete("page");
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-1.5">
        {sizes.map((size) => {
          const isSelected = selected === size;
          return (
            <Link
              key={size}
              href={href(isSelected ? null : size)}
              scroll={false}
              aria-pressed={isSelected}
              className={cn(
                "inline-flex h-9 min-w-[3rem] items-center justify-center rounded-md border px-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                isSelected
                  ? "border-primary bg-primary text-primary-foreground shadow-sm"
                  : "border-input bg-background hover:border-primary hover:bg-primary/5",
              )}
            >
              {size}
            </Link>
          );
        })}
      </div>

      {selected !== undefined && (
        <Link
          href={href(null)}
          scroll={false}
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <X className="size-3" />
          Откажи големина {selected}
        </Link>
      )}
    </div>
  );
}
