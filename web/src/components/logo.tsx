/**
 * The wordmark, the tag mark, and the one place the brand name is written.
 *
 * The name is still being chosen -- TopCena.mk, NajCena.mk,
 * NajdobraPonuda.mk -- so it lives in {@link SITE_NAME} as three parts and
 * nowhere else. Swapping it is one edit here; the header, the footer, the
 * page titles and the mobile drawer all read from it.
 *
 * The mark is a price tag reading `-50%`: the thing this site is for, drawn
 * as the thing every shop in the country puts in its window.
 *
 * It is drawn rather than borrowed, and drawn in a 24 box to the same
 * geometry as the category icons, so the header reads as one set.
 */

/**
 * The brand, in the three pieces the wordmark colours differently.
 *
 * Keep the split: the two-tone wordmark is the brand, and a single string
 * would have to be re-split at every call site to colour it.
 */
export const SITE_NAME = {
  /** Dark charcoal, the page's own text colour. */
  head: "Top",
  /** The emerald the site already prices in -- `--price`, not a new green. */
  accent: "Cena",
  /** Muted slate, and smaller: a domain suffix is not part of the name. */
  tld: ".mk",
} as const;

/** The name as prose: "TopCena". Used where the domain would read oddly. */
export const BRAND_NAME = `${SITE_NAME.head}${SITE_NAME.accent}`;

/** The name in full: "TopCena.mk". Page titles, metadata. */
export const BRAND_DOMAIN = `${BRAND_NAME}${SITE_NAME.tld}`;

/** Three verbs, in the order a shopper does them. */
export const SITE_TAGLINE = "Спореди, купи, заштеди";

import { cn } from "@/lib/utils";

/**
 * The tag on its own: the favicon, the phone's header, the home-screen icon.
 *
 * Everything in it is a path, because it has to survive 16px in a browser
 * tab with no page and no fonts around it. A logo that only works large is
 * a logo that is never seen at the size it is used most.
 *
 * `currentColor` is deliberately not used: this mark is red at every size,
 * on every background, in both themes. It is the one piece of the interface
 * that should not shift with the palette around it.
 *
 * The same paths live in `app/icon.svg`. They are duplicated rather than
 * imported because a favicon is a file the browser fetches, not a component
 * -- and the file is generated from this one by hand, which is why both
 * carry this note.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      {/* Tilted, as every paper tag in every shop window is. Twelve
          degrees: enough to read as pinned on rather than set square,
          little enough that the figure inside stays upright to the eye. */}
      <g transform="rotate(-12 12 12)">
        {/* Wide and shallow, because what goes inside is four characters
            rather than one symbol: the tag needs length, not height. A
            rounded label chamfered to a point at the left.

            No eyelet. The hole sat a couple of units from the minus sign
            and at header size the two read as one thing -- a pair of dots
            in front of the number, so the tag said `• • 50%`. A punched
            hole is a nice detail; a figure nobody can read is not. */}
        <path
          fill="#e11d48"
          d="M8.8 4.2h11A3.4 3.4 0 0 1 23.2 7.6v8.8a3.4 3.4 0 0 1-3.4 3.4h-11a2.7 2.7 0 0 1-1.95-.83l-4.3-4.45a3.6 3.6 0 0 1 0-5l4.3-4.45A2.7 2.7 0 0 1 8.8 4.2Z"
        />

        {/* `-50%`, drawn rather than typed.

            `<text>` is one line and renders a little heavier, and it was
            built and compared against this before being dropped: a favicon
            is an SVG the browser renders on its own, outside the page and
            outside its fonts, so the one that depends on a font stack is
            the one that can come back in something else -- or, in a few
            renderers, not at all. Six paths have no such dependency and
            look the same everywhere.

            The figure is illustrative, as it is on every shop's sale
            sticker. It is not read off the catalogue and does not claim a
            discount of any particular size. */}
        {/* Centred on the tag's own middle, which is a little right of
            the box's: the chamfered point is empty space and pulls the
            optical centre with it. The minus is wider and heavier than a
            hyphen would be, so it reads as a sign rather than as a gap. */}
        <rect x="5.7" y="11.2" width="3" height="1.7" rx=".85" fill="#fff" />
        <path
          d="M11.6 9.5H9.3v2.1h1.1a1.45 1.45 0 1 1-1.15 2.3"
          fill="none"
          stroke="#fff"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <ellipse
          cx="14.2"
          cy="11.9"
          rx="1.5"
          ry="2.3"
          fill="none"
          stroke="#fff"
          strokeWidth="1.3"
        />
        <circle cx="17.2" cy="10.4" r=".85" fill="none" stroke="#fff" strokeWidth=".85" />
        <circle cx="19.1" cy="13.4" r=".85" fill="none" stroke="#fff" strokeWidth=".85" />
        <path d="M16.8 13.8 19.5 10" stroke="#fff" strokeWidth="1" strokeLinecap="round" />
      </g>
    </svg>
  );
}

/**
 * The header lockup: the name on every screen, the motto only where there
 * is room for it.
 *
 * The phone used to get the tag alone, because a full lockup and a search
 * field do not both fit at 375px. The search field moved behind a magnifier
 * instead -- see `HeaderSearch` -- which buys back the width, and a name is
 * worth more than an icon: a shopper who lands on a page from a search
 * result should be told whose page it is.
 *
 * So the wordmark is always there, a size smaller below `sm`, and only the
 * tagline is held back. It is the line that can go: it explains the brand
 * to someone reading at leisure, and nobody reads at leisure on a phone
 * header.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex flex-col", className)}>
      <span className="flex items-start">
        <span className="text-lg font-extrabold leading-none tracking-tight sm:text-xl">
          <span className="text-foreground">{SITE_NAME.head}</span>
          <span className="text-price">{SITE_NAME.accent}</span>
          <span className="text-[0.72em] font-bold text-muted-foreground">
            {SITE_NAME.tld}
          </span>
        </span>
        {/* Perched on the corner like a sticker, and pulled into the
            wordmark so the two read as one object rather than a logo with
            something next to it. */}
        <LogoMark className="-ml-1 -mt-2 size-[25px] shrink-0 sm:-ml-1.5 sm:-mt-2.5 sm:size-[28px]" />
      </span>
      {/* Aligned to the wordmark's left edge, as price.com sets its own. */}
      <span className="hidden text-[11px] font-medium leading-tight text-muted-foreground sm:block">
        {SITE_TAGLINE}
      </span>
    </span>
  );
}
