"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDownUp, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";
import { DEFAULT_SORT, SORTS, type SortKey } from "@/lib/sort";

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
  selected = DEFAULT_SORT,
  className,
}: {
  selected?: SortKey;
  className?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const onChange = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === DEFAULT_SORT) {
      // The default stays out of the URL, so the canonical listing has one
      // address rather than two that render identically.
      next.delete("sort");
    } else {
      next.set("sort", value);
    }
    // Re-sorting reorders the whole result set, so page 4 of the old order is
    // meaningless -- the same reason the size and brand filters reset paging.
    next.delete("page");
    const qs = next.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
  };

  return (
    <div className={cn("space-y-2", className)}>
      <label
        htmlFor="sort"
        className="flex items-center gap-1.5 text-sm font-semibold"
      >
        <ArrowDownUp className="size-3.5 text-muted-foreground" />
        Сортирај
      </label>

      <div className="relative">
        <select
          id="sort"
          value={selected}
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
