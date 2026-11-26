import { X } from "lucide-react";

import { FilterLink } from "@/components/catalog/filter-transition";
import { type ActiveChip } from "@/lib/filters";

/**
 * What is filtered right now, each with the click that undoes it.
 *
 * Above the grid rather than in the rail, because this is the answer to "why
 * am I seeing these 40 products" and a shopper asks it while looking at the
 * products. With six multi-select groups the ticked boxes can be three
 * sections apart and two of them below the fold; a shopper who cannot see
 * what is applied concludes the catalogue is small rather than that they are
 * filtered.
 *
 * Each chip's href is the same page minus that one value, so removing a
 * filter is one click and never "clear everything and start again".
 */
export function ActiveFilters({
  chips,
  clearHref,
}: {
  chips: ActiveChip[];
  /** Everything off, keeping the vertical the shopper is browsing. */
  clearHref: string;
}) {
  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => (
        <FilterLink
          key={`${chip.key}:${chip.value}`}
          href={chip.href}
          className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 py-1 pl-3 pr-2 text-xs font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {chip.label}
          <X aria-hidden className="size-3.5 opacity-70" />
          <span className="sr-only">Отстрани филтер</span>
        </FilterLink>
      ))}

      {/* Only from two chips up. With one, it is the same click as the chip
          itself, and two controls that do one thing is noise. */}
      {chips.length > 1 && (
        <FilterLink
          href={clearHref}
          className="rounded-md px-2 py-1 text-xs font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Исчисти сè
        </FilterLink>
      )}
    </div>
  );
}
