"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The detail page's non-EU size rail: letters for adult garments, age or
 * height bands for kids'.
 *
 * Distinct from {@link AlphaSizePicker}, which is the listing's rail and only
 * ever shows ladder letters gathered from a page of products. This one shows
 * whatever one product actually comes in, so "9-10 год." is a first-class
 * chip rather than something off the ladder to be ranked last, and the order
 * is the API's -- each system sorted on its own scale, letters by the ladder
 * and ages by month.
 *
 * Sold-out sizes stay on the rail, struck through and still clickable, as the
 * EU picker does. Hiding them would answer "do they make it in XL?" with
 * silence, which is a different claim from "yes, and nobody has it".
 */
export function LabelSizePicker({
  sizes,
  selected,
  unavailable,
  className,
}: {
  /** Already ordered by the API. Rendered as given. */
  sizes: string[];
  selected?: string;
  /** Shown struck through rather than hidden. */
  unavailable?: string[];
  className?: string;
}) {
  const pathname = usePathname();
  const params = useSearchParams();
  const unavailableSet = new Set(unavailable ?? []);

  const href = (size: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (size === null) {
      next.delete("size");
    } else {
      next.set("size", size);
      // A product has one size axis, so an EU number left in the URL from a
      // footwear page would filter this one to nothing.
      next.delete("sizeEu");
    }
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-1.5">
        {sizes.map((size) => {
          const isSelected = selected === size;
          const isOut = unavailableSet.has(size);
          return (
            <Link
              key={size}
              // Clicking the selected chip clears the filter. Without it the
              // only way back to every offer is the browser's back button or
              // editing the URL.
              href={href(isSelected ? null : size)}
              scroll={false}
              aria-pressed={isSelected}
              className={cn(
                "inline-flex h-9 min-w-[3rem] items-center justify-center rounded-md border px-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                isSelected
                  ? "border-primary bg-primary text-primary-foreground shadow-sm"
                  : isOut
                    ? "border-dashed border-border bg-muted/40 text-muted-foreground/60 line-through hover:border-primary"
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
