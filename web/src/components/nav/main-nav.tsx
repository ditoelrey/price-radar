"use client";

/**
 * The second header row: three verticals, with a full-width mega menu.
 *
 * Opening on hover is the pattern the MK shops use and the one shoppers
 * arrive expecting, but hover alone would make the whole category tree
 * unreachable without a mouse. So the same panel opens on focus, closes on
 * Escape, and each trigger is a real link that works with JavaScript off --
 * `Обувки` navigates to all footwear whether or not its menu ever opens.
 *
 * Closing is deliberately slow (a short timer) rather than immediate. The
 * trigger and the panel do not touch, and a pointer crossing that gap would
 * otherwise snap the menu shut mid-reach.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";

import {
  COMING_SOON,
  GENDER_COLUMNS,
  VERTICALS,
  categoriesFor,
  listingHref,
  type Vertical,
} from "@/lib/navigation";
import { cn } from "@/lib/utils";

/** Long enough to cross the gap below the trigger, short enough to feel shut. */
const CLOSE_DELAY_MS = 120;

/**
 * One menu for every vertical that has leaves.
 *
 * This was two components, `FootwearMenu` and a `ComingSoonMenu` that drew
 * the three gender headings with "Наскоро" under each. Apparel went live
 * with 17 032 offers and still rendered the second one, so the menu showed
 * Мажи / Жени / Деца and nothing to click.
 */
/**
 * The menu for a vertical whose departments hold the same stock.
 *
 * Опрема is that vertical. Splitting it into Мажи / Жени / Деца would draw
 * thirty links where ten will do, because a men's listing already includes
 * unisex and most equipment is unisex -- 55 percent of Sport Vision's, 66 of
 * Sport Reality's. The two adult columns would be near-copies of each other.
 *
 * Kids is the exception and gets a link of its own: ролери, тротинети and
 * кациги are a genuinely different shelf.
 */
function CategoryMenu({ vertical }: { vertical: Vertical }) {
  const categories = categoriesFor(vertical.kind);
  return (
    <div>
      <ul className="grid grid-cols-2 gap-x-8 gap-y-1 sm:grid-cols-3">
        {categories.map((category) => (
          <li key={category.slug}>
            <Link
              href={listingHref({
                kind: vertical.kind,
                category: category.slug,
              })}
              className="block py-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {category.label}
            </Link>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-3">
        <Link
          href={listingHref({ kind: vertical.kind, gender: "kids" })}
          className="flex items-center gap-1 text-sm font-medium transition-colors hover:text-primary"
        >
          {vertical.label} за деца
          <ArrowRight className="size-3.5" />
        </Link>
        <Link
          href={listingHref({ kind: vertical.kind })}
          className="flex items-center gap-1 text-sm font-medium transition-colors hover:text-primary"
        >
          {vertical.allLabel}
          <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </div>
  );
}

function VerticalMenu({ vertical }: { vertical: Vertical }) {
  if (vertical.genderColumns === false) {
    return <CategoryMenu vertical={vertical} />;
  }
  return (
    <div className="grid grid-cols-3 gap-8">
      {GENDER_COLUMNS.map((gender) => {
        const categories = categoriesFor(vertical.kind, gender.slug);
        return (
          <section key={gender.slug}>
            {/* text-base against the leaves' text-sm. Both were text-sm
                first, which left weight and colour doing all the work and the
                column reading as five similar links. */}
            <h3 className="border-b pb-2 text-base font-semibold">
              {gender.label}
            </h3>
            {/* The leaves carry the weight here, so they are set smaller and
                tighter than the column head. Apparel brings eleven of them
                against footwear's four, so the list scrolls with the panel
                rather than setting its own height. */}
            <ul className="mt-3 space-y-1">
              {categories.map((category) => (
                <li key={category.slug}>
                  <Link
                    href={listingHref({
                      kind: vertical.kind,
                      gender: gender.slug,
                      category: category.slug,
                    })}
                    className="block py-0.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {category.label}
                  </Link>
                </li>
              ))}
            </ul>

            {/* Last, not first. The "view all" link is the escape hatch for
                someone the leaves did not serve, and a shopper who knows
                they want Копачки should not have to read past "everything"
                to find it. Separated by a rule so it reads as a different
                kind of link rather than one more category. */}
            <Link
              href={listingHref({ kind: vertical.kind, gender: gender.slug })}
              className="mt-3 flex items-center gap-1 border-t pt-3 text-sm font-medium transition-colors hover:text-primary"
            >
              {vertical.allLabel}
              <ArrowRight className="size-3.5" />
            </Link>
          </section>
        );
      })}
    </div>
  );
}

export function MainNav({ activeKind }: { activeKind?: string }) {
  const [openKind, setOpenKind] = useState<string | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navRef = useRef<HTMLDivElement>(null);

  const cancelClose = () => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  const open = (kind: string) => {
    cancelClose();
    setOpenKind(kind);
  };

  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpenKind(null), CLOSE_DELAY_MS);
  };

  useEffect(() => cancelClose, []);

  useEffect(() => {
    if (!openKind) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenKind(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [openKind]);

  // Driven by the data now, not by naming the one vertical that lacks
  // leaves: a vertical with no categories has nothing to open.
  const hasMenu = (vertical: Vertical) => Boolean(vertical.categories);

  return (
    <div
      ref={navRef}
      className="relative hidden border-t md:block"
      onMouseLeave={scheduleClose}
      onBlur={(event) => {
        if (!navRef.current?.contains(event.relatedTarget as Node)) {
          setOpenKind(null);
        }
      }}
    >
      <div className="mx-auto flex max-w-7xl items-center gap-1 px-4 sm:px-6">
        {VERTICALS.map((vertical) => {
          const isOpen = openKind === vertical.kind;
          const isActive = activeKind === vertical.kind;
          const Icon = vertical.icon;
          const shared = cn(
            "flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors",
            "border-b-2",
            isActive || isOpen
              ? "border-primary text-foreground"
              : "border-transparent",
          );

          if (vertical.status === "soon" && !hasMenu(vertical)) {
            return (
              <span
                key={vertical.kind}
                title={COMING_SOON}
                aria-disabled="true"
                className={cn(shared, "cursor-default text-muted-foreground")}
              >
                <Icon className="size-4 opacity-70" />
                {vertical.label}
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                  {COMING_SOON}
                </span>
              </span>
            );
          }

          const trigger =
            vertical.status === "live" ? (
              <Link
                href={listingHref({ kind: vertical.kind })}
                className={cn(shared, "hover:text-primary")}
                aria-expanded={isOpen}
                aria-haspopup="true"
              >
                <Icon className="size-4 opacity-70" />
                {vertical.label}
                <ChevronDown className="size-3.5 opacity-60" />
              </Link>
            ) : (
              <button
                type="button"
                className={cn(shared, "text-muted-foreground")}
                aria-expanded={isOpen}
                aria-haspopup="true"
              >
                <Icon className="size-4 opacity-70" />
                {vertical.label}
                <ChevronDown className="size-3.5 opacity-60" />
              </button>
            );

          return (
            <div
              key={vertical.kind}
              onMouseEnter={() => open(vertical.kind)}
              onFocus={() => open(vertical.kind)}
            >
              {trigger}
            </div>
          );
        })}
      </div>

      {openKind && (
        <div
          className="absolute inset-x-0 top-full z-40 border-y bg-background shadow-lg"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
            {(() => {
              const vertical = VERTICALS.find((v) => v.kind === openKind);
              return vertical?.categories ? (
                <VerticalMenu vertical={vertical} />
              ) : null;
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
