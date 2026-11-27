"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * One size a product is sold in, on both scales at once.
 *
 * `value` is what the URL carries and never changes with the tab: the EU
 * number for a shoe, the shop's own label for a kids' garment. That is the
 * whole design of this control -- the second scale is a way of *reading* the
 * ladder, not a second thing to filter by. The API's size filter, the
 * listing's facets and every link on the site stay on one axis.
 */
export type SizeRung = {
  value: string;
  /** What the default tab prints: "42", "7-8г." */
  label: string;
  /** What the CM tab prints: "26.5", "128". Null when this rung has none. */
  cm: string | null;
  inStock: boolean;
};

/**
 * The size grid with a scale switcher above it, as the MK shops draw it.
 *
 * Sport Vision puts `Големини EU / Големини / Големини CM` over its grid and
 * a shopper who knows their foot in centimetres -- which is how half the
 * Balkan market buys shoes online -- picks the one they can answer. We hold
 * the same data: the shops publish the centimetre beside the EU number on
 * the size widget, and the pipeline has been storing it all along.
 *
 * Three rules this control is built around.
 *
 * **The default tab is the page as it was.** It opens on EU (or on the age
 * band), renders the same chips in the same order, and writes the same URL.
 * A shopper who never notices the tabs sees no change at all.
 *
 * **The tab is not in the URL.** It is a way of reading the page, not a
 * filter: putting it in the query string would mean two URLs for one page
 * and a shared link that arrives on a scale the sender happened to be using.
 *
 * **Centimetres collapse, and that is honest.** Half sizes often share a
 * last: EU 36.5 and 37.5 are both 23.5 cm on the Air Force 1. The CM tab
 * prints 23.5 once, and clicking it picks the rung a shopper can actually
 * buy -- the one in stock, or the smaller EU when neither is.
 */
export function SizeScalePicker({
  param,
  defaultScaleLabel,
  altScaleLabel,
  rungs,
  className,
}: {
  /** The query parameter this grid writes: the product's one axis. */
  param: "sizeEu" | "size";
  /** The tab that is open on arrival: `Големини EU` or `Возраст`. */
  defaultScaleLabel: string;
  /** The other tab, always centimetres here. */
  altScaleLabel: string;
  /** In display order. Every rung must carry a `cm` or the caller must not
   *  render this component -- a grid with holes is worse than one scale. */
  rungs: SizeRung[];
  className?: string;
}) {
  const [showCm, setShowCm] = useState(false);
  const pathname = usePathname();
  const params = useSearchParams();
  const current = params.get(param);

  const isSelected = (rung: SizeRung) => {
    if (current === null) return false;
    // EU numbers are compared as numbers: "42.0" in a pasted URL and the
    // API's 42 are the same rung, and the ⅓ sizes are stored to three
    // decimals.
    if (param === "sizeEu") {
      return Math.abs(Number(current) - Number(rung.value)) < 0.005;
    }
    return current === rung.value;
  };

  const href = (value: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (value === null) {
      next.delete(param);
    } else {
      next.set(param, value);
      // A product sits on one axis. An EU number left over from a footwear
      // page would filter a garment to nothing, and the other way round.
      next.delete(param === "sizeEu" ? "size" : "sizeEu");
    }
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };

  // One entry per centimetre value, in the order the rungs came in. The
  // representative is the rung a click lands on: in stock if any of them is,
  // otherwise the first, which is the smallest since the caller sorts.
  const cmGroups: Array<{ cm: string; rungs: SizeRung[] }> = [];
  for (const rung of rungs) {
    if (rung.cm === null) continue;
    const group = cmGroups.find((g) => g.cm === rung.cm);
    if (group) group.rungs.push(rung);
    else cmGroups.push({ cm: rung.cm, rungs: [rung] });
  }

  const shown = showCm
    ? cmGroups.map((group) => {
        const pick = group.rungs.find((r) => r.inStock) ?? group.rungs[0];
        return {
          key: group.cm,
          text: group.cm,
          href: href(isSelected(pick) ? null : pick.value),
          selected: group.rungs.some(isSelected),
          out: !group.rungs.some((r) => r.inStock),
        };
      })
    : rungs.map((rung) => ({
        key: rung.value,
        text: rung.label,
        href: href(isSelected(rung) ? null : rung.value),
        selected: isSelected(rung),
        out: !rung.inStock,
      }));

  const active = shown.find((chip) => chip.selected);

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-sm font-semibold">Избери големина:</p>

      {/* Inline text options separated by a slash, as the shops draw them.
          Buttons rather than links: the scale is client state, so switching
          it must not be a navigation. */}
      <p className="flex flex-wrap items-center gap-1.5 text-sm">
        <ScaleTab active={!showCm} onClick={() => setShowCm(false)}>
          {defaultScaleLabel}
        </ScaleTab>
        <span aria-hidden className="text-muted-foreground/50">
          /
        </span>
        <ScaleTab active={showCm} onClick={() => setShowCm(true)}>
          {altScaleLabel}
        </ScaleTab>
      </p>

      <div className="flex flex-wrap gap-1.5 pt-1">
        {shown.map((chip) => (
          <Link
            key={chip.key}
            href={chip.href}
            scroll={false}
            aria-pressed={chip.selected}
            className={cn(
              "tnum inline-flex h-9 min-w-[3rem] items-center justify-center rounded-md border px-2 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              chip.selected
                ? "border-primary bg-primary text-primary-foreground shadow-sm"
                : chip.out
                  ? // Still clickable, as the other grids are: hiding a
                    // sold-out size answers "do they make it?" with silence,
                    // which is a different claim from "yes, and nobody has
                    // it".
                    "border-dashed border-border bg-muted/40 text-muted-foreground/60 line-through hover:border-primary"
                  : "border-input bg-background hover:border-primary hover:bg-primary/5",
            )}
          >
            {chip.text}
          </Link>
        ))}
      </div>

      {active && (
        <Link
          href={href(null)}
          scroll={false}
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          <X className="size-3" />
          Откажи големина {active.text}
        </Link>
      )}
    </div>
  );
}

function ScaleTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "font-medium text-primary"
          : "text-foreground/80 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
