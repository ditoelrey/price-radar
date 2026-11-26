"use client";

import { Check, Search } from "lucide-react";

import {
  FilterLink,
  useOptimisticSelected,
} from "@/components/catalog/filter-transition";
import {
  type FilterGroupModel,
  type FilterOption,
  type GroupKey,
} from "@/lib/filters";
import { cn } from "@/lib/utils";

/**
 * The parts both filter surfaces are built from.
 *
 * The desktop rail is a server component and the mobile drawer a client one,
 * and both render these: keeping them in one file is what stops the two
 * surfaces drifting into two controls that happen to look alike.
 *
 * `"use client"` because a box now answers before the server does -- see
 * `useOptimisticSelected`. The rail above them stays on the server; only the
 * controls themselves cross over.
 *
 * Every option is a `<Link>` dressed as a checkbox rather than an `<input>`.
 * Filtering is a navigation here -- the listing is server-rendered and the
 * URL is the state -- so a real checkbox would need a client handler to do
 * what an anchor does for free, and would stop working with JavaScript off.
 * `role="checkbox"` and `aria-checked` tell a screen reader what it is; the
 * box is drawn, not native, because a native one cannot be the link.
 */
export function OptionRow({
  option,
  group,
  single,
  className,
}: {
  option: FilterOption;
  /** Which group this belongs to, so a click can be shown before it lands. */
  group: GroupKey;
  /** Drawn as a radio, and clicking the active one clears it. */
  single?: boolean;
  className?: string;
}) {
  const selected = useOptimisticSelected(
    group,
    option.value,
    option.selected,
    single,
  );

  return (
    <FilterLink
      href={option.href}
      pick={{ group, value: option.value, selected: !option.selected }}
      role={single ? "radio" : "checkbox"}
      aria-checked={selected}
      className={cn(
        "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "font-medium" : "text-muted-foreground",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "grid size-4 shrink-0 place-items-center border transition-colors",
          // A circle says "one of these" before a word does, which is the
          // whole reason this group looks different from the other five.
          single ? "rounded-full" : "rounded-[4px]",
          selected
            ? "border-primary bg-primary text-primary-foreground"
            : "border-input bg-background group-hover:border-primary",
        )}
      >
        {selected &&
          (single ? (
            <span className="size-1.5 rounded-full bg-primary-foreground" />
          ) : (
            <Check className="size-3" strokeWidth={3} />
          ))}
      </span>
      {/* Производи wraps, everything else truncates. Its labels are the
          longest on the page -- "EDP — Парфимирани води", "Кациги, наочари и
          заштитници" -- and there are at most a dozen of them, where Бренд
          has sixty rows that have to stay one line each to be scannable. */}
      <span className={cn("min-w-0 flex-1", single ? "break-words" : "truncate")}>
        {option.label}
      </span>
      {/* The count is the facet's promise, and it is why the boxes are worth
          ticking: a shopper can see which option leaves them something. */}
      <span className="shrink-0 text-[11px] tabular-nums opacity-60">
        {option.count}
      </span>
    </FilterLink>
  );
}

/** The size ladders, as chips: a rung is two characters and a row is cheap. */
export function SizeChips({ options }: { options: FilterOption[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => (
        <SizeChip key={option.value} option={option} />
      ))}
    </div>
  );
}

/** Its own component so it can hold the hook that fills it in early. */
function SizeChip({ option }: { option: FilterOption }) {
  const selected = useOptimisticSelected("size", option.value, option.selected);

  return (
    <FilterLink
      href={option.href}
      pick={{ group: "size", value: option.value, selected: !option.selected }}
      role="checkbox"
      aria-checked={selected}
      title={`${option.count} производи`}
      className={cn(
        "inline-flex h-9 min-w-[3rem] items-center justify-center rounded-md border px-2 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        selected
          ? "border-primary bg-primary text-primary-foreground shadow-sm"
          : "border-input bg-background hover:border-primary hover:bg-primary/5",
      )}
    >
      {option.label}
    </FilterLink>
  );
}

/**
 * A group's body: the boxes, the chips, or the searchable brand list.
 *
 * Scrolls past twelve options rather than growing without limit. Бренд is the
 * group this matters for -- a footwear listing has sixty brands -- and it is
 * also the only one given a search box, because it is the only one where a
 * shopper arrives already knowing the word they want. Категорија deliberately
 * has none: a vertical has at most a dozen leaves, and a search box over
 * twelve visible items is furniture.
 */
export function GroupBody({
  group,
  query,
  onQueryChange,
}: {
  group: FilterGroupModel;
  /** Only passed for Бренд, by the client wrapper that owns the input. */
  query?: string;
  onQueryChange?: (value: string) => void;
}) {
  if (group.sections) {
    return (
      <div className="space-y-4">
        {group.sections.map((section) => (
          <div key={section.title}>
            {/* Named only when there are two ladders to tell apart, which
                happens on a search across verticals. */}
            {group.sections!.length > 1 && (
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                {section.title}
              </p>
            )}
            <SizeChips options={section.options} />
          </div>
        ))}
      </div>
    );
  }

  const options = group.options;
  return (
    <div className="space-y-2">
      {group.search && onQueryChange && (
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="search"
            value={query ?? ""}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Пронајди бренд"
            aria-label="Пронајди бренд"
            className={cn(
              "h-9 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm",
              "placeholder:text-muted-foreground focus-visible:outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
            )}
          />
        </div>
      )}

      {options.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          Нема резултати
        </p>
      ) : (
        <div
          role={group.single ? "radiogroup" : undefined}
          className="-mx-1 max-h-64 space-y-0.5 overflow-y-auto px-1"
        >
          {options.map((option) => (
            <OptionRow
              key={option.value}
              option={option}
              group={group.key}
              single={group.single}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One accordion section.
 *
 * `<details>` rather than a popover with client state: it opens without
 * JavaScript, carries its own keyboard and screen-reader behaviour, and the
 * whole rail is server-rendered, so there is nothing to hydrate. A group
 * opens by default when it is one of the first ones or has something ticked
 * -- a shopper must never have to open a section to discover they are
 * filtered by it.
 */
export function FilterSection({
  title,
  selectedCount,
  defaultOpen,
  children,
}: {
  title: string;
  selectedCount: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details
      // `defaultOpen` alone, not `|| selectedCount > 0`. A group a shopper
      // has already answered is the one they need least: the chips above the
      // grid say what is applied, and opening every answered section pushed
      // the unanswered ones off the screen.
      open={defaultOpen}
      className="group border-b border-border/60 py-3 last:border-b-0 [&_summary::-webkit-details-marker]:hidden"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold">
        <span className="flex items-baseline gap-1.5">
          {title}
          {selectedCount > 0 && (
            <span className="rounded-full bg-primary/10 px-1.5 text-[11px] font-medium tabular-nums text-primary">
              {selectedCount}
            </span>
          )}
        </span>
        {/* Drawn rather than borrowed from an icon set: it has to rotate with
            the element's own open state, which CSS can see and React cannot
            without owning it. */}
        <span
          aria-hidden
          className="shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path
              d="M6 9l6 6 6-6"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </summary>
      <div className="pt-3">{children}</div>
    </details>
  );
}
