import { Shirt } from "lucide-react";

/**
 * The four verticals' icons, as one family.
 *
 * They were four Lucide glyphs chosen for being roughly the right noun --
 * `Footprints` for shoes, `SprayCan` for perfume, `Backpack` for equipment --
 * and side by side they read as four icons borrowed from four places: a pair
 * of footprints is a trail rather than a shoe, and a spray can is deodorant.
 *
 * These are drawn to one spec: a 24×24 box, no fill, `currentColor`, 1.75
 * stroke, round caps and joins. That matters more than any one shape. A
 * navigation bar's icons are read as a set, and one heavier or larger than
 * its neighbours makes that vertical look selected when it is not.
 *
 * Облека keeps Lucide's `Shirt`, with the stroke brought down from 2 to
 * 1.75 so it sits at the same weight as the other three.
 *
 * Sizing is the caller's: every one takes `className`, and the bar gives
 * them all the same one.
 */
export type CategoryIcon = React.ComponentType<{ className?: string }>;

/** Shared across all four, so none can drift. */
const BASE = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function ShirtIcon({ className }: { className?: string }) {
  return <Shirt className={className} strokeWidth={1.75} />;
}

/** Обувки: a trainer in profile, laces and sole. */
export function SneakerIcon({ className }: { className?: string }) {
  return (
    <svg {...BASE} className={className} aria-hidden>
      <path d="M1.5 15v-4c0-2.643.776-3.992 1.303-4.732A.65.65 0 0 1 3.333 6c.369 0 .66.302.739.661C4.268 7.552 4.91 8.5 6.5 8.5c1.721 0 2.578-1.605 3.209-2.902c.178-.367.549-.598.957-.598c.217 0 .43.066.61.19L19 10.5c3 1 3.5 2.5 3.5 4.5" />
      <path d="M19 10.5c0 .5-.5 1.5-2 1.643c-1.991.19-3 1.857-3 2.857" />
      <path d="M1.5 13v2c0 1.414 0 2.121.44 2.56c.439.44 1.146.44 2.56.44h15c1.414 0 2.121 0 2.56-.44c.44-.439.44-1.146.44-2.56H8.743a3 3 0 0 1-2.122-.879l-.242-.242A3 3 0 0 0 4.257 13zm11.896-6.296l-1.242 1.56M15.5 8.5l-.941 1.302" />
    </svg>
  );
}

/** Парфеми: a bottle with its collar and cap. */
export function PerfumeIcon({ className }: { className?: string }) {
  return (
    <svg {...BASE} className={className} aria-hidden>
      {/* The glass, as a wash rather than an outline. The only fill in the
          set, and it is what keeps a bottle from reading as a jar: at 20px
          the silhouette alone is a rounded square. */}
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M5.18 19.52a3 3 0 0 0 2.96 2.6h8.69c1.5 0 2.77-1.11 2.95-2.6l.2-1.55a7.56 7.56 0 1 0-15 0z"
        clipRule="evenodd"
        opacity={0.14}
        stroke="none"
      />
      <path d="M7.33 22.27h10.61a2 2 0 0 0 1.84-1.65l.04-.28l.27-2.37A7.64 7.64 0 1 0 4.9 18l.27 2.36l.03.27a2 2 0 0 0 1.85 1.65z" />
      <path d="M9.2 10.13V8.36c0-.95 0-1.42.3-1.71s.77-.3 1.7-.3h2.57c.94 0 1.41 0 1.7.3s.3.76.3 1.7v1.78" />
      <path d="M10.88 6.36V3.52c0-.57 0-.86.11-1.07a1 1 0 0 1 .43-.43c.21-.11.5-.11 1.07-.11s.85 0 1.07.11a1 1 0 0 1 .43.43c.1.21.1.5.1 1.07v2.84" />
    </svg>
  );
}

/**
 * Опрема: a backpack — handle, body, front pocket.
 *
 * Drawn here rather than taken from Bootstrap's `bi:backpack`, which is a
 * solid 16×16 glyph. Dropped in beside three 24×24 outlines it would be the
 * only filled shape in the bar and would read as the selected tab from
 * across the room, so the silhouette is redrawn at this family's box and
 * stroke.
 */
export function BackpackIcon({ className }: { className?: string }) {
  return (
    <svg {...BASE} className={className} aria-hidden>
      <path d="M9 6V5a3 3 0 0 1 6 0v1" />
      <path d="M4 12.5A6.5 6.5 0 0 1 10.5 6h3a6.5 6.5 0 0 1 6.5 6.5v6a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5z" />
      <path d="M8.5 21v-5a1.5 1.5 0 0 1 1.5-1.5h4a1.5 1.5 0 0 1 1.5 1.5v5" />
      <path d="M10.25 17.75h3.5" />
    </svg>
  );
}
