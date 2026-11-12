import { cn } from "@/lib/utils";

/**
 * A merchant's logo, sized so a column of them reads as one column.
 *
 * Every logo renders inside the same fixed box with `object-contain` and is
 * centred, which is the only way a set of differently-proportioned wordmarks
 * can look deliberate. Their trimmed aspect ratios run from 3.08 (Buzz) to
 * 5.51 (Megasport), all wider than the box, so each one is width-limited:
 * identical widths, varying heights, vertically centred. Forcing a common
 * height instead would give a ragged column of widths from 111px to 229px.
 *
 * The source files are trimmed to their content by `tools/prepare_logos.py`.
 * Without that step the box letterboxes each logo by its *canvas* rather than
 * its artwork -- Sport Vision ships a wide wordmark inside a 400x400 square,
 * and would have rendered at a third the size of the others for no visible
 * reason.
 */

/**
 * Logos matted onto opaque white, which need multiply blending to sit on a
 * tinted row.
 *
 * Measured rather than assumed, and the result was not what it looked like:
 * Buzz is 28% opaque white, while Sport-M -- the one that appears white --
 * is fully transparent already, as are the other four. Blending a
 * transparent logo achieves nothing and risks washing it out, so this list
 * stays empty except where the pixels say otherwise.
 */
const NEEDS_MULTIPLY = new Set(["buzz"]);

/** Merchants we ship a logo file for. Anything else falls back to its name. */
const HAS_LOGO = new Set([
  "sportvision",
  "sportreality",
  "sizeer",
  "sportm",
  "buzz",
  "megasport",
]);

export function MerchantLogo({
  slug,
  name,
  className,
}: {
  slug: string;
  name: string;
  className?: string;
}) {
  // A missing file must never leave a hole: merchants are added from the
  // database, and the logo is a separate asset that can lag behind.
  if (!HAS_LOGO.has(slug)) {
    return (
      <div
        className={cn(
          "flex h-10 w-28 items-center justify-center rounded-md border bg-muted/40 px-2",
          className,
        )}
      >
        <span className="line-clamp-2 text-center text-[11px] font-medium leading-tight text-muted-foreground">
          {name}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex h-10 w-28 items-center justify-center", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/logos/${slug}.png`}
        alt={name}
        loading="lazy"
        className={cn(
          "max-h-full max-w-full object-contain",
          // Scoped to light mode on purpose: multiply against a dark
          // background turns a black wordmark invisible, and the dark theme
          // tokens already exist even though nothing toggles them yet.
          NEEDS_MULTIPLY.has(slug) && "mix-blend-multiply dark:mix-blend-normal",
        )}
      />
    </div>
  );
}
