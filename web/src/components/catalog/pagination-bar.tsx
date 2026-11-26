import { FilterLink } from "@/components/catalog/filter-transition";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The page numbers to draw, with gaps marked.
 *
 * Always the first page, always the last, and the current one with a
 * neighbour either side. The last page is not an ornament: it is the only
 * thing on the bar that tells a shopper how much there is, so it is never
 * collapsed into an ellipsis.
 *
 * Seven or fewer pages are listed in full, because a window plus two
 * ellipses would be wider than the thing it abbreviates.
 *
 * Exported for its own test: the branch that decides where a gap falls is
 * the part worth pinning, and it needs no DOM.
 */
export function pageWindow(current: number, total: number): Array<number | "gap"> {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const near = new Set<number>([1, total, current]);
  for (const page of [current - 1, current + 1]) {
    if (page > 1 && page < total) near.add(page);
  }
  // Keep the bar a stable width near the ends, where a one-sided window
  // would otherwise leave it visibly shorter than in the middle.
  if (current <= 3) {
    near.add(2).add(3).add(4);
  }
  if (current >= total - 2) {
    near.add(total - 1).add(total - 2).add(total - 3);
  }

  const pages = [...near].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out: Array<number | "gap"> = [];
  let previous = 0;
  for (const page of pages) {
    // A gap worth one page is not a gap: "1 … 3" hides nothing that
    // "1 2 3" would not have shown, and costs the same width.
    if (previous && page - previous > 1) {
      out.push(page - previous === 2 ? previous + 1 : "gap");
    }
    out.push(page);
    previous = page;
  }
  return out;
}

const STEP =
  "inline-flex h-9 min-w-9 items-center justify-center gap-1 rounded-md " +
  "border px-2 text-sm transition-colors";

/**
 * One arrow button.
 *
 * A disabled step is a span rather than a link, because an anchor pointing
 * at the page you are already on is still clickable and still navigates --
 * on page 1 that is a "first page" button that reloads for nothing.
 *
 * Declared here and not inside `PaginationBar`: a component created during
 * render is a new type on every render, so React remounts its subtree
 * instead of updating it.
 */
function Step({
  href,
  to,
  disabled,
  label,
  children,
}: {
  href: (page: number) => string;
  to: number;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span
        aria-disabled="true"
        className={cn(STEP, "cursor-not-allowed text-muted-foreground/40")}
      >
        {children}
      </span>
    );
  }
  return (
    <FilterLink
      href={href(to - 1)}
      aria-label={label}
      className={cn(STEP, "hover:border-primary/40 hover:text-primary")}
    >
      {children}
    </FilterLink>
  );
}

/**
 * Numbered pagination under a listing.
 *
 * Renders nothing at all for a single page: a bar reading "1" with every
 * arrow greyed out is a control that cannot be used, and it reads as
 * something being broken rather than as a catalogue with one page in it.
 *
 * `href` carries the whole filter state, so every button here preserves
 * the kind, category, gender, brand, size, sort and query already in the
 * URL -- the same `listingHref` the rest of the storefront builds links
 * with.
 */
export function PaginationBar({
  page,
  totalPages,
  hasMore,
  href,
  className,
}: {
  /** Zero-based, as the API numbers it. */
  page: number;
  /**
   * How many pages there are, or undefined when the payload did not say.
   *
   * Undefined is a real state, not a bug to paper over: a response cached
   * before the API served `total` has none. The first version of this
   * component guessed in that case -- current page plus one if there was
   * more -- and the guess was a lie with consequences. On page 1 it drew
   * "1 2" for a 350-page listing and pointed the last-page button at page
   * 2. Nothing looked broken, which is what made it bad.
   *
   * So an unknown total now draws only what is known: previous and next.
   */
  totalPages?: number;
  /** Whether a next page exists. The only navigation left when the total
   *  is unknown, and `hasMore` has always been able to answer it. */
  hasMore?: boolean;
  href: (page: number) => string;
  className?: string;
}) {
  const current = page + 1;

  if (totalPages === undefined) {
    // Nothing to number and no last page to offer. Hidden entirely on the
    // first page with nothing after it, which is the one-page case.
    if (page === 0 && !hasMore) return null;
    return (
      <nav
        aria-label="Страници"
        className={cn("mt-6 flex items-center justify-center gap-1.5",
                      className)}
      >
        <Step href={href} to={current - 1} disabled={page === 0}
              label="Претходна страница">
          <ChevronLeft className="size-4" />
          <span className="hidden sm:inline">Претходна</span>
        </Step>
        <span className="px-2 text-sm tabular-nums text-muted-foreground">
          {current}
        </span>
        <Step href={href} to={current + 1} disabled={!hasMore}
              label="Следна страница">
          <span className="hidden sm:inline">Следна</span>
          <ChevronRight className="size-4" />
        </Step>
      </nav>
    );
  }

  if (totalPages <= 1) return null;

  const atFirst = current <= 1;
  const atLast = current >= totalPages;

  return (
    <nav
      aria-label="Страници"
      className={cn("mt-6 flex flex-wrap items-center justify-center gap-1.5",
                    className)}
    >
      <Step href={href} to={1} disabled={atFirst} label="Прва страница">
        <ChevronsLeft className="size-4" />
      </Step>
      <Step href={href} to={current - 1} disabled={atFirst} label="Претходна страница">
        <ChevronLeft className="size-4" />
        {/* The word costs more width than two pages of numbers on a phone,
            and the arrow already says it. */}
        <span className="hidden sm:inline">Претходна</span>
      </Step>

      {pageWindow(current, totalPages).map((entry, i) => {
        if (entry === "gap") {
          return (
            <span
              key={`gap-${i}`}
              aria-hidden="true"
              className="px-1 text-sm text-muted-foreground"
            >
              …
            </span>
          );
        }
        if (entry === current) {
          return (
            <span
              key={entry}
              aria-current="page"
              className={cn(STEP, "border-primary font-semibold text-primary",
                            "tabular-nums")}
            >
              {entry}
            </span>
          );
        }
        /* The neighbours are a desktop luxury. At 375px the full window --
           two arrows, first, a gap, three numbers, a gap, last, two more
           arrows -- wrapped onto three lines, which is worse than not
           offering them: measured, nav height 78px against 36. First,
           current and last stay, because those are the three a phone
           actually needs: where you are, where it starts, how much there
           is. */
        const essential = entry === 1 || entry === totalPages;
        return (
          <FilterLink
            key={entry}
            href={href(entry - 1)}
            aria-label={`Страница ${entry}`}
            className={cn(
              STEP,
              "tabular-nums hover:border-primary/40 hover:text-primary",
              essential ? "inline-flex" : "hidden sm:inline-flex",
            )}
          >
            {entry}
          </FilterLink>
        );
      })}

      <Step href={href} to={current + 1} disabled={atLast} label="Следна страница">
        <span className="hidden sm:inline">Следна</span>
        <ChevronRight className="size-4" />
      </Step>
      <Step href={href} to={totalPages} disabled={atLast} label="Последна страница">
        <ChevronsRight className="size-4" />
      </Step>
    </nav>
  );
}
