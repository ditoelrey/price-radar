"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useFilterTransition } from "@/components/catalog/filter-transition";
import { ArrowDownUp, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { DEFAULT_SORT_LABEL, SORTS, type SortKey } from "@/lib/sort";

/**
 * The sort control, above the size rail.
 *
 * A real `<select>` rather than a styled popover: it is four mutually
 * exclusive options with no need to see them all at once, and the native
 * element brings keyboard support, the platform picker on a phone, and
 * correct behaviour inside a scrolling sidebar for free. The chrome is ours
 * (`appearance-none` plus our own chevron) so it matches the size chips, but
 * the behaviour underneath is the browser's.
 *
 * Changing it is a navigation, exactly like picking a size, so the result is
 * shareable and the back button works. `replace` rather than `push`, though:
 * re-sorting the same result set is a change of view, not a step in a
 * journey, and five sort changes should not mean five presses of Back to
 * leave the page.
 */
export function SortSelect({
  selected,
  className,
  layout = "stacked",
}: {
  /** Undefined when the shopper has not chosen one. */
  selected?: SortKey;
  className?: string;
  /**
   * `stacked` puts the label above the control, which is what a sidebar
   * wants. `inline` puts it beside, for the top right of the grid -- where
   * this control now lives, because sorting is not filtering and it belongs
   * with the result count rather than above the filters.
   */
  layout?: "stacked" | "inline";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // Re-sorting costs the same second a filter does, and the select would
  // otherwise sit on the new value with the old order still on screen.
  const transition = useFilterTransition();

  const onChange = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === "") {
      // The placeholder: back to no explicit order at all.
      next.delete("sort");
    } else {
      next.set("sort", value);
    }
    // Re-sorting reorders the whole result set, so page 4 of the old order is
    // meaningless -- the same reason the size and brand filters reset paging.
    next.delete("page");
    const qs = next.toString();
    const url = `${pathname}${qs ? `?${qs}` : ""}`;
    if (transition) {
      transition.navigate(url);
      return;
    }
    router.replace(url, { scroll: false });
  };

  const inline = layout === "inline";

  return (
    <div
      className={cn(
        inline ? "flex items-center gap-2" : "space-y-2",
        className,
      )}
    >
      <label
        htmlFor="sort"
        className={cn(
          "flex items-center gap-1.5 font-semibold",
          inline
            ? "shrink-0 text-xs text-muted-foreground"
            : "text-sm",
        )}
      >
        <ArrowDownUp className="size-3.5 text-muted-foreground" />
        Сортирај
      </label>

      <div className={cn("relative", inline && "min-w-[11rem]")}>
        <select
          id="sort"
          value={selected ?? ""}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            // Same height, radius, border and hover as a size chip, so the
            // two controls read as one set rather than two widgets that
            // happen to sit together.
            "h-9 w-full cursor-pointer appearance-none rounded-md border border-input bg-background",
            "pl-3 pr-9 text-sm font-medium transition-colors",
            "hover:border-primary hover:bg-primary/5",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
          )}
        >
          {/* `hidden` keeps this out of the open list while still letting
              the closed control display it -- the shopper sees exactly the
              four orderings on offer, and an honest label for the order the
              page is actually in. */}
          <option value="" hidden>
            {DEFAULT_SORT_LABEL}
          </option>
          {SORTS.map((sort) => (
            <option key={sort.value} value={sort.value}>
              {sort.label}
            </option>
          ))}
        </select>

        {/* The native arrow cannot be styled, so it is suppressed above and
            redrawn here. `pointer-events-none` keeps clicks going through to
            the select underneath, including on the icon itself. */}
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
      </div>
    </div>
  );
}
