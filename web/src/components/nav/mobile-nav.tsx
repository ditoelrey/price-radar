"use client";

/**
 * The same tree on a phone, as an accordion.
 *
 * A hover menu means nothing on a touch screen, so this is not the desktop
 * component made narrow -- it is the same data in the shape that works:
 * `Обувки` expands to the three genders, each of which expands to the four
 * categories. Two taps to any listing, nothing behind a hover a finger
 * cannot perform.
 *
 * Built on explicit state rather than `<details>`, which was the first
 * attempt. `<details>` would have been less code and would have worked
 * before hydration -- but its collapse does not work in the browser this was
 * developed against, including for a bare `<details>` with no styling at
 * all, so every section rendered expanded. Shipping a disclosure widget
 * whose disclosing cannot be verified is worse than writing six lines of
 * state that can be.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, ChevronDown, Menu, X, type LucideIcon } from "lucide-react";

import {
  COMING_SOON,
  GENDER_COLUMNS,
  VERTICALS,
  categoriesFor,
  listingHref,
} from "@/lib/navigation";
import { cn } from "@/lib/utils";

function Toggle({
  label,
  expanded,
  onClick,
  muted,
  className,
  icon: Icon,
}: {
  label: string;
  expanded: boolean;
  onClick: () => void;
  muted?: boolean;
  className?: string;
  /** Only the verticals carry one; the gender rows inside do not. */
  icon?: LucideIcon;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      className={cn(
        "flex w-full items-center justify-between py-2.5 text-left text-sm font-medium",
        muted && "text-muted-foreground",
        className,
      )}
    >
      <span className="flex items-center gap-2">
        {Icon ? <Icon className="size-4 opacity-70" /> : null}
        {label}
      </span>
      <ChevronDown
        className={cn(
          "size-4 opacity-60 transition-transform",
          expanded && "rotate-180",
        )}
      />
    </button>
  );
}

export function MobileNav() {
  const [open, setOpen] = useState(false);
  // Footwear starts expanded: it is the only vertical with anything in it,
  // and opening the menu to a list of one collapsed row helps nobody.
  const [openKind, setOpenKind] = useState<string | null>("footwear");
  const [openGender, setOpenGender] = useState<string | null>(null);

  const close = () => setOpen(false);
  const toggleKind = (kind: string) =>
    setOpenKind((current) => (current === kind ? null : kind));
  const toggleGender = (gender: string) =>
    setOpenGender((current) => (current === gender ? null : gender));

  return (
    <div className="md:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? "Затвори мени" : "Отвори мени"}
        className="grid size-9 place-items-center rounded-md border"
      >
        {open ? <X className="size-4" /> : <Menu className="size-4" />}
      </button>

      {open && (
        <div className="absolute inset-x-0 top-full z-40 max-h-[70vh] overflow-y-auto border-y bg-background px-4 pb-4 shadow-lg">
          {VERTICALS.map((vertical) => {
            if (vertical.kind === "equipment") {
              return (
                <div
                  key={vertical.kind}
                  className="flex items-center justify-between border-b py-3 text-sm text-muted-foreground"
                >
                  <span className="flex items-center gap-2">
                    <vertical.icon className="size-4 opacity-70" />
                    {vertical.label}
                  </span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px]">
                    {COMING_SOON}
                  </span>
                </div>
              );
            }

            const expanded = openKind === vertical.kind;
            const soon = vertical.status === "soon";

            return (
              <div key={vertical.kind} className="border-b">
                <Toggle
                  label={vertical.label}
                  icon={vertical.icon}
                  expanded={expanded}
                  muted={soon}
                  onClick={() => toggleKind(vertical.kind)}
                />

                {expanded && soon && (
                  <div className="pb-2 pl-3">
                    {GENDER_COLUMNS.map((gender) => (
                      <div
                        key={gender.slug}
                        className="flex items-center justify-between py-1.5 text-sm text-muted-foreground/70"
                      >
                        {gender.label}
                        <span className="text-xs">{COMING_SOON}</span>
                      </div>
                    ))}
                  </div>
                )}

                {expanded && !soon && (
                  <div className="pb-2 pl-3">
                    <Link
                      href={listingHref({ kind: vertical.kind })}
                      onClick={close}
                      className="block py-1.5 text-sm font-medium underline underline-offset-4"
                    >
                      {vertical.allLabel}
                    </Link>

                    {GENDER_COLUMNS.map((gender) => {
                      const genderOpen = openGender === gender.slug;
                      return (
                        <div key={gender.slug} className="border-t">
                          <Toggle
                            label={gender.label}
                            expanded={genderOpen}
                            className="font-normal"
                            onClick={() => toggleGender(gender.slug)}
                          />
                          {genderOpen && (
                            <div className="pb-2 pl-3">
                              <ul>
                                {categoriesFor(
                                  vertical.kind,
                                  gender.slug,
                                ).map((category) => (
                                  <li key={category.slug}>
                                    <Link
                                      href={listingHref({
                                        kind: vertical.kind,
                                        gender: gender.slug,
                                        category: category.slug,
                                      })}
                                      onClick={close}
                                      className="block py-1.5 text-sm text-muted-foreground"
                                    >
                                      {category.label}
                                    </Link>
                                  </li>
                                ))}
                              </ul>

                              {/* Last, as in the desktop menu: "view all" is
                                  the escape hatch for a shopper the four
                                  leaves did not serve, so it belongs after
                                  them rather than ahead of them. */}
                              <Link
                                href={listingHref({
                                  kind: vertical.kind,
                                  gender: gender.slug,
                                })}
                                onClick={close}
                                className="mt-1 flex items-center gap-1 border-t pt-2 text-sm font-medium"
                              >
                                {vertical.allLabel}
                                <ArrowRight className="size-3.5" />
                              </Link>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
