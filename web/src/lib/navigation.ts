/**
 * The storefront's navigation taxonomy, and the one place that builds a
 * listing URL.
 *
 * Two jobs, together on purpose.
 *
 * **The taxonomy.** Slugs are English because they are identifiers -- they
 * travel in the URL, reach the API as `?kind=`, `?category=` and `?gender=`,
 * and match `category.slug` in the database. Labels are Macedonian because
 * they are read by people. Nothing in this file translates one into the
 * other at runtime; the pairing is the data.
 *
 * The verticals are the top level rather than gender, which inverts how the
 * MK shops do it. Sport Vision opens with Мажи / Жени / Деца and nests the
 * verticals underneath, and that works for one shop selling one kind of
 * thing. A price comparison site that will grow into perfume -- which is
 * largely unisex -- cannot put gender above the vertical without later
 * having to apologise for it.
 *
 * **The URL builder.** `listingHref` exists because there were already two
 * places assembling these links by hand (the pager and the brand rail), each
 * rebuilding the query string from scratch. Every time the listing gains a
 * parameter, every such place has to learn about it or it silently drops the
 * shopper's filter -- which is exactly what would have happened to `kind`,
 * `category` and `gender` here. One builder, one contract.
 */
import { Backpack, Footprints, Shirt, type LucideIcon } from "lucide-react";

import { type SortKey } from "@/lib/sort";

/** A gender column, as the API's `?gender=` understands it. */
export type GenderSlug = "men" | "women" | "kids";

/**
 * The three columns of the footwear menu.
 *
 * Adjectival forms, because they agree with the vertical they sit under:
 * "Машки обувки". The apparel menu uses the noun forms (Мажи / Жени / Деца),
 * which is how the shops label their own departments.
 */
export const GENDER_COLUMNS: ReadonlyArray<{
  slug: GenderSlug;
  label: string;
  nounLabel: string;
}> = [
  { slug: "men", label: "Машки", nounLabel: "Мажи" },
  { slug: "women", label: "Женски", nounLabel: "Жени" },
  { slug: "kids", label: "Детски", nounLabel: "Деца" },
];

/**
 * The four canonical footwear leaves, in the order the shops list them.
 *
 * These are the V17 buckets, and the storefront is the reason they were
 * consolidated: sportm and sizeer split sneakers into low-top and high-top,
 * but that is derivable for 6.2 percent of the catalogue, and a menu entry
 * that works for 6 percent of the stock is worse than no entry at all --
 * a shopper who clicks it concludes the site is empty rather than unlabelled.
 */
export const FOOTWEAR_CATEGORIES: ReadonlyArray<{
  slug: string;
  label: string;
}> = [
  { slug: "sneakers", label: "Патики" },
  { slug: "cleats", label: "Копачки" },
  { slug: "shoes_boots", label: "Кондури и чизми" },
  { slug: "slides_sandals", label: "Папучи и сандали" },
];

export type Vertical = {
  /** `category_kind` on the API side. */
  kind: string;
  label: string;
  /**
   * Kept here rather than in the nav component, so a vertical cannot be
   * added in one file and acquire its icon in another. The icon is part of
   * what the vertical *is*, the same way its Macedonian label is.
   */
  icon: LucideIcon;
  /**
   * `live` has a real menu and real links. `soon` renders the same shape
   * with a muted note and no links at all -- a disabled span, not an `<a>`
   * to a page that would come back empty. A dead link is a worse promise
   * than an honest "Наскоро".
   */
  status: "live" | "soon";
};

export const VERTICALS: ReadonlyArray<Vertical> = [
  { kind: "footwear", label: "Обувки", status: "live", icon: Footprints },
  { kind: "apparel", label: "Облека", status: "soon", icon: Shirt },
  { kind: "equipment", label: "Опрема", status: "soon", icon: Backpack },
];

export const COMING_SOON = "Наскоро";

/** Every parameter the listing page reads out of the URL. */
export type ListingParams = {
  q?: string;
  brand?: string;
  sizeEu?: number;
  kind?: string;
  category?: string;
  gender?: string;
  sort?: SortKey;
  page?: number;
};

/**
 * Build a `/products` URL.
 *
 * Defaults are left out rather than written down: the default sort and page
 * zero produce the shortest URL that means the same thing, so the link a
 * shopper copies from the address bar is the one a person would have typed.
 */
export function listingHref(params: ListingParams = {}): string {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.kind) sp.set("kind", params.kind);
  if (params.gender) sp.set("gender", params.gender);
  if (params.category) sp.set("category", params.category);
  if (params.brand) sp.set("brand", params.brand);
  if (params.sizeEu !== undefined) sp.set("sizeEu", String(params.sizeEu));
  // Every explicit sort goes in the URL now. There is no visible default to
  // leave out: an absent `sort` means the API's hidden shop-count ordering,
  // which is a different thing from any of the four the control offers.
  if (params.sort) sp.set("sort", params.sort);
  if (params.page && params.page > 0) sp.set("page", String(params.page));
  const qs = sp.toString();
  return `/products${qs ? `?${qs}` : ""}`;
}

/**
 * The heading for a filtered listing, in Macedonian.
 *
 * Built from the same data the menu is, so a link and the page it lands on
 * cannot disagree about what the shopper asked for.
 */
export function listingTitle(params: ListingParams): string {
  if (params.q) {
    return `Резултати за „${params.q}“`;
  }
  const category = FOOTWEAR_CATEGORIES.find(
    (c) => c.slug === params.category,
  )?.label;
  const vertical = VERTICALS.find((v) => v.kind === params.kind)?.label;
  const gender = GENDER_COLUMNS.find((g) => g.slug === params.gender)?.label;

  const noun = category ?? vertical ?? "Обувки";
  return gender ? `${gender} ${noun.toLowerCase()}` : noun;
}
