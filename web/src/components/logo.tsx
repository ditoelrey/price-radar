/**
 * The wordmark, the tag mark, and the one place the brand name is written.
 *
 * The name is still being chosen -- TopCena.mk, NajCena.mk,
 * NajdobraPonuda.mk -- so it lives in {@link SITE_NAME} as three parts and
 * nowhere else. Swapping it is one edit here; the header, the footer, the
 * page titles and the mobile drawer all read from it.
 *
 * The mark is a hang tag with a smiling percent in it. Both halves of what
 * this site is: a price tag is where a saving lives, and the percent's lower
 * counter is drawn as a smile rather than a second ring, so the discount cue
 * and the happy-shopper cue are one shape instead of two competing ones.
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
 * Kept to four shapes -- the tag, the eyelet punched out of it, the
 * percent's dot and slash, and the smile -- because it has to survive 16px
 * in a browser tab. Anything finer turns to mush there, and a logo that only
 * works large is a logo that is never seen at the size it is used most.
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
      {/* Tilted, as every paper tag in every shop window is. Twelve degrees:
          enough to read as pinned on rather than set square, little enough
          that the percent inside stays upright to the eye. */}
      <g transform="rotate(-12 12 12)">
        {/* The classic shape: a rounded label with a chamfered point at the
            left and the eyelet punched through it. One path, two subpaths,
            `evenodd`, so the hole is a hole and the background shows
            through rather than a white dot painted on red. */}
        <path
          fill="#e11d48"
          fillRule="evenodd"
          clipRule="evenodd"
          d="M9.1 2.6h10.4A3.5 3.5 0 0 1 23 6.1v11.8a3.5 3.5 0 0 1-3.5 3.5H9.1a2.8 2.8 0 0 1-2-.83L1.5 14.4a3.4 3.4 0 0 1 0-4.8l5.6-6.17A2.8 2.8 0 0 1 9.1 2.6Zm-3 8.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Z"
        />
        {/* A percent, drawn as a percent: two open counters and a slash. The
            first version folded the lower counter into the smile to make one
            clever shape, and one clever shape is what it looked like -- a
            squiggle. Two plain symbols, clearly apart, say both things.

            `-50%` was the other candidate and it is the better poster: at
            128px it is unmistakable. It is also four glyphs sharing eleven
            pixels of tag at favicon size, where it turns to mush. This mark
            is read at 16 to 32 far more often than at 128. */}
        <circle
          cx="12.5"
          cy="8.2"
          r="1.6"
          fill="none"
          stroke="#fff"
          strokeWidth="1.2"
        />
        <circle
          cx="17.3"
          cy="12.6"
          r="1.6"
          fill="none"
          stroke="#fff"
          strokeWidth="1.2"
        />
        <path
          d="M11.8 13.4 18 7.3"
          stroke="#fff"
          strokeWidth="1.7"
          strokeLinecap="round"
        />
        {/* Its own arc, under the percent and not touching it. */}
        <path
          d="M11.5 16.2q3.4 2.6 6.8 0"
          stroke="#fff"
          strokeWidth="1.55"
          strokeLinecap="round"
          fill="none"
        />
      </g>
    </svg>
  );
}

/**
 * The header lockup.
 *
 * Two renderings of one brand, chosen by width rather than by JavaScript, so
 * the server sends both and neither flashes.
 *
 * On a phone the wordmark goes and the tag stays. The header there is a
 * menu button, an identity and a search field, and the search field is what
 * people came for -- at 375px the full lockup left it about 150px, which is
 * not a search field. The tag alone is still the brand.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center", className)}>
      <LogoMark className="size-8 sm:hidden" />

      <span className="hidden flex-col sm:flex">
        <span className="flex items-start">
          <span className="text-xl font-extrabold tracking-tight leading-none">
            <span className="text-foreground">{SITE_NAME.head}</span>
            <span className="text-price">{SITE_NAME.accent}</span>
            <span className="text-[0.72em] font-bold text-muted-foreground">
              {SITE_NAME.tld}
            </span>
          </span>
          {/* Perched on the corner like a sticker, and pulled into the
              wordmark so the two read as one object rather than a logo with
              something next to it. */}
          <LogoMark className="-ml-1.5 -mt-2 size-[22px] shrink-0" />
        </span>
        {/* Aligned to the wordmark's left edge, as price.com sets its own.
            `hidden lg:block`: on a tablet the header is tight enough that
            the second line costs the search field more than it is worth. */}
        <span className="hidden text-[11px] font-medium leading-tight text-muted-foreground lg:block">
          {SITE_TAGLINE}
        </span>
      </span>
    </span>
  );
}
