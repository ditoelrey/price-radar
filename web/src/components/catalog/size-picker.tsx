"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatSizeEu } from "@/lib/format";

/**
 * The size grid, modelled on idealo's.
 *
 * This is the most important control on the site, and it is a grid of chips
 * rather than a dropdown on purpose: a shopper knows their size, and should
 * be able to hit it in one click without opening anything. A select would add
 * two interactions to the single filter that changes what the prices mean.
 *
 * Each chip is a real `<Link>` to the same page with `?sizeEu=`, so filtering
 * is a navigation: shareable, bookmarkable, back-button friendly, and
 * rendered on the server with no client state to get out of step.
 */
export function SizePicker({
  sizes,
  selected,
  className,
  unavailable,
}: {
  sizes: number[];
  selected?: number;
  className?: string;
  /** Sizes to show greyed rather than hide, on a detail page. */
  unavailable?: number[];
}) {
  const pathname = usePathname();
  const params = useSearchParams();

  const href = (size: number | null) => {
    const next = new URLSearchParams(params.toString());
    if (size === null) {
      next.delete("sizeEu");
    } else {
      next.set("sizeEu", String(size));
    }
    // Any filter change resets paging; staying on page 4 of the old result
    // set is never what someone meant.
    next.delete("page");
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };

  const unavailableSet = new Set(unavailable ?? []);

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap gap-1.5">
        {sizes.map((size) => {
          const isSelected = selected !== undefined && Math.abs(selected - size) < 0.005;
          const isOut = unavailableSet.has(size);
          return (
            <Link
              key={size}
              href={href(isSelected ? null : size)}
              scroll={false}
              aria-pressed={isSelected}
              title={isOut ? `EU ${formatSizeEu(size)} — not available` : undefined}
              className={cn(
                "tnum inline-flex h-9 min-w-[3rem] items-center justify-center rounded-md border px-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                isSelected
                  ? "border-primary bg-primary text-primary-foreground shadow-sm"
                  : isOut
                    ? "border-dashed border-border bg-muted/40 text-muted-foreground/60 line-through"
                    : "border-input bg-background hover:border-primary hover:bg-primary/5",
              )}
            >
              {formatSizeEu(size)}
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
          Clear size EU {formatSizeEu(selected)}
        </Link>
      )}
    </div>
  );
}
