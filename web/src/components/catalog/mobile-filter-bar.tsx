"use client";

import { useEffect, useState } from "react";
import { ArrowDownUp, Check, SlidersHorizontal, X } from "lucide-react";

import {
  FilterSection,
  GroupBody,
} from "@/components/catalog/filter-controls";
import { FilterLink } from "@/components/catalog/filter-transition";
import { SearchableGroup } from "@/components/catalog/searchable-group";
import {
  type ActiveChip,
  type FilterGroupModel,
  type GroupKey,
} from "@/lib/filters";
import { cn } from "@/lib/utils";

/** A sort option, with the link that applies it. */
export type SortOption = {
  value: string;
  label: string;
  selected: boolean;
  href: string;
};

type Panel = { kind: "sort" } | { kind: "all" } | { kind: "group"; key: GroupKey };

/**
 * The phone's filter bar: one scrollable row of pills, each opening a sheet.
 *
 * The rail cannot be on screen on a phone -- it would be the whole screen --
 * and the previous answer was to stack it above the grid, which pushed the
 * products below two screens of controls. A shopper who has to scroll past
 * the filters to reach the products scrolls past them once and never opens
 * them again.
 *
 * `Сортирај` comes first, before `Филтри`. It is the control a shopper on a
 * phone reaches for most -- "cheapest first" is the whole reason to be on a
 * price comparison site -- and it is the one that is useful without reading
 * anything else on the page.
 *
 * Each pill opens a sheet holding exactly one group, with `Филтри (N)` as the
 * one that holds all of them. Ticking a box navigates, as it does on the
 * desktop: the sheet stays open because this component stays mounted across
 * a soft navigation, and the counts and the footer's figure come back updated
 * from the server. Nothing is staged client-side waiting for an Apply, so a
 * shopper who closes the sheet mid-change has still changed it, and the URL
 * is never out of step with what is on screen.
 */
export function MobileFilterBar({
  groups,
  chips,
  clearHref,
  total,
  sortOptions,
  sortLabel,
}: {
  groups: FilterGroupModel[];
  chips: ActiveChip[];
  clearHref: string;
  /** Products the current filters match, for the footer button. */
  total?: number;
  sortOptions: SortOption[];
  /** What the sort pill reads when nothing explicit is chosen. */
  sortLabel: string;
}) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const shown = groups.filter(
    (group) => group.options.length > 0 || (group.sections?.length ?? 0) > 0,
  );
  const active = shown.reduce((sum, group) => sum + group.selectedCount, 0);

  // The sheet covers the page, so the page behind it must not scroll with it.
  useEffect(() => {
    if (panel === null) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [panel]);

  // Escape closes it, which is what a keyboard on a tablet expects.
  useEffect(() => {
    if (panel === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPanel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel]);

  const openGroup =
    panel?.kind === "group"
      ? shown.find((group) => group.key === panel.key)
      : undefined;

  return (
    <div className="lg:hidden">
      {/* Edge to edge, so the last pill is not cut off by the page gutter
          while still scrolling under it. */}
      <div className="-mx-4 mb-4 overflow-x-auto px-4 pb-1 sm:-mx-6 sm:px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex w-max items-center gap-2">
          <Pill
            onClick={() => setPanel({ kind: "sort" })}
            icon={<ArrowDownUp className="size-3.5" />}
          >
            {sortOptions.find((option) => option.selected)?.label ?? sortLabel}
          </Pill>

          <Pill
            onClick={() => setPanel({ kind: "all" })}
            icon={<SlidersHorizontal className="size-3.5" />}
            emphasis={active > 0}
          >
            Филтри{active > 0 ? ` (${active})` : ""}
          </Pill>

          {shown.map((group) => (
            <Pill
              key={group.key}
              onClick={() => setPanel({ kind: "group", key: group.key })}
              emphasis={group.selectedCount > 0}
            >
              {group.title}
              {group.selectedCount > 0 && ` (${group.selectedCount})`}
            </Pill>
          ))}
        </div>
      </div>

      {panel !== null && (
        <Sheet
          title={
            panel.kind === "sort"
              ? "Сортирај"
              : panel.kind === "all"
                ? "Филтри"
                : (openGroup?.title ?? "Филтри")
          }
          onClose={() => setPanel(null)}
          total={panel.kind === "sort" ? undefined : total}
        >
          {panel.kind === "sort" ? (
            <div className="space-y-0.5">
              {sortOptions.map((option) => (
                <FilterLink
                  key={option.value}
                  href={option.href}
                  onNavigate={() => setPanel(null)}
                  aria-current={option.selected}
                  className={cn(
                    "flex items-center justify-between rounded-md px-2 py-2.5 text-sm transition-colors hover:bg-accent",
                    option.selected
                      ? "font-medium text-primary"
                      : "text-foreground",
                  )}
                >
                  {option.label}
                  {option.selected && <Check className="size-4" />}
                </FilterLink>
              ))}
            </div>
          ) : (
            <>
              {chips.length > 0 && (
                <div className="mb-3 flex flex-wrap items-center gap-2 border-b pb-3">
                  {chips.map((chip) => (
                    <FilterLink
                      key={`${chip.key}:${chip.value}`}
                      href={chip.href}
                      className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 py-1 pl-3 pr-2 text-xs font-medium text-primary"
                    >
                      {chip.label}
                      <X aria-hidden className="size-3.5 opacity-70" />
                    </FilterLink>
                  ))}
                  <FilterLink
                    href={clearHref}
                    className="px-1 text-xs font-medium text-muted-foreground underline underline-offset-4"
                  >
                    Исчисти сè
                  </FilterLink>
                </div>
              )}

              {panel.kind === "all" ? (
                shown.map((group) => (
                  <FilterSection
                    key={group.key}
                    title={group.title}
                    selectedCount={group.selectedCount}
                  >
                    {group.search ? (
                      <SearchableGroup group={group} />
                    ) : (
                      <GroupBody group={group} />
                    )}
                  </FilterSection>
                ))
              ) : openGroup ? (
                openGroup.search ? (
                  <SearchableGroup group={openGroup} />
                ) : (
                  <GroupBody group={openGroup} />
                )
              ) : null}
            </>
          )}
        </Sheet>
      )}
    </div>
  );
}

function Pill({
  children,
  onClick,
  icon,
  emphasis,
}: {
  children: React.ReactNode;
  onClick: () => void;
  icon?: React.ReactNode;
  emphasis?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        emphasis
          ? "border-primary bg-primary/10 text-primary"
          : "border-input bg-background hover:border-primary",
      )}
    >
      {icon}
      {children}
      <svg
        aria-hidden
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        className="opacity-60"
      >
        <path
          d="M6 9l6 6 6-6"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}

/**
 * The sheet itself: a panel off the bottom of the screen.
 *
 * Bottom rather than side, because a phone is held in one hand and the thumb
 * reaches the bottom of the screen, not the top. Capped at 88vh so the page
 * behind it stays visible -- it is a filter over a result set, not a new
 * page, and seeing the products through the gap is the difference.
 */
function Sheet({
  title,
  onClose,
  total,
  children,
}: {
  title: string;
  onClose: () => void;
  total?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button
        type="button"
        aria-label="Затвори"
        onClick={onClose}
        className="absolute inset-0 bg-foreground/40"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative flex max-h-[88vh] flex-col rounded-t-xl border-t bg-card shadow-lg"
      >
        <div className="flex shrink-0 items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Затвори"
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
          {children}
        </div>

        {total !== undefined && (
          <div className="shrink-0 border-t bg-card px-4 py-3">
            {/* It closes the sheet rather than applying anything: the
                filters applied as they were ticked, and the figure here is
                the server's answer to what is ticked now. Labelling it
                "Примени" would claim a step that does not exist. */}
            <button
              type="button"
              onClick={onClose}
              className="h-11 w-full rounded-md bg-primary text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
            >
              Прикажи {total} производи
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
