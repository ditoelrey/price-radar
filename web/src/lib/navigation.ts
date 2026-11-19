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
 * The three columns of every vertical's menu.
 *
 * Two forms, and which is which matters. `label` is the noun -- Мажи / Жени
 * / Деца -- and it is what every menu shows, because a column heading is a
 * department, the way the shops label their own. The footwear menu used the
 * adjectives here and the apparel menu the nouns, so the same three columns
 * were called different things one tab apart.
 *
 * `adjectiveLabel` survives because a heading and a sentence need different
 * words. It is only ever used to compose a listing's title, where the gender
 * agrees with a following noun: "Машки патики", "Женски маици". Putting the
 * noun form there would read "Мажи патики", which is not Macedonian.
 */
export const GENDER_COLUMNS: ReadonlyArray<{
  slug: GenderSlug;
  label: string;
  adjectiveLabel: string;
}> = [
  { slug: "men", label: "Мажи", adjectiveLabel: "Машки" },
  { slug: "women", label: "Жени", adjectiveLabel: "Женски" },
  { slug: "kids", label: "Деца", adjectiveLabel: "Детски" },
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

/**
 * The apparel leaves, as V18 seeded them.
 *
 * Labels are copied from `category.name_mk` rather than written again here,
 * so the menu and the listing heading cannot drift apart -- the API returns
 * `categoryMk` from the same column.
 *
 * `genders` is the exception list, and it is here rather than in the
 * database because it is a statement about this menu, not about the
 * catalogue: V18 says as much in its own comment. Sports bras and dresses
 * have no men's stock at all (0 of 190 and 0 of 159 live products), so a
 * men's column offering them would promise a page that comes back empty.
 * Everything else is sold in all three departments.
 *
 * The order is by live stock, which is also roughly how the shops rank their
 * own menus: tees and hoodies first, swimwear and underwear last.
 */
export const APPAREL_CATEGORIES: ReadonlyArray<{
  slug: string;
  label: string;
  genders?: ReadonlyArray<GenderSlug>;
}> = [
  { slug: "tshirts", label: "Маици" },
  { slug: "hoodies", label: "Дуксери и блузони" },
  { slug: "jackets", label: "Јакни и елеци" },
  { slug: "trousers", label: "Долни делови и панталони" },
  { slug: "shorts", label: "Шорцеви" },
  { slug: "tracksuits", label: "Тренерки" },
  { slug: "leggings", label: "Хеланки и бициклистички" },
  { slug: "sports_bras", label: "Градници и топови", genders: ["women", "kids"] },
  { slug: "dresses_skirts", label: "Фустани и сукњи", genders: ["women", "kids"] },
  { slug: "swimwear", label: "Костими за капење" },
  { slug: "underwear", label: "Долна облека" },
];

/**
 * Letter sizes, smallest first. The same ladder as
 * `mkagg.sizing.ALPHA_LADDER` and `alpha_size_rank` in V21.
 *
 * The API returns each product's sizes in this order already, but a listing
 * merges the sizes of 24 products, and first appearance across cards is not
 * the ladder: a page whose first card is S/M/XL and whose second adds L and
 * XXL yields "S M XL L XXL". So the merged list is ranked here.
 */
export const ALPHA_LADDER: ReadonlyArray<string> = [
  "XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL",
];

/** Order a merged set of letter sizes; anything off the ladder goes last. */
export function byAlphaLadder(a: string, b: string): number {
  const rank = (s: string) => {
    const i = ALPHA_LADDER.indexOf(s);
    return i === -1 ? ALPHA_LADDER.length : i;
  };
  return rank(a) - rank(b) || a.localeCompare(b);
}

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
  /**
   * The escape-hatch wording, which cannot be composed from `label`:
   * обувки is a plural ("Сите обувки") and облека a feminine collective
   * singular ("Сета облека"). Two words, two agreements, so each vertical
   * carries its own.
   */
  allLabel?: string;
  /** The leaves of this vertical's menu. Absent means there is no menu. */
  categories?: ReadonlyArray<{
    slug: string;
    label: string;
    genders?: ReadonlyArray<GenderSlug>;
  }>;
};

export const VERTICALS: ReadonlyArray<Vertical> = [
  {
    kind: "footwear",
    label: "Обувки",
    status: "live",
    icon: Footprints,
    allLabel: "Сите обувки",
    categories: FOOTWEAR_CATEGORIES,
  },
  {
    kind: "apparel",
    label: "Облека",
    status: "live",
    icon: Shirt,
    allLabel: "Сета облека",
    categories: APPAREL_CATEGORIES,
  },
  { kind: "equipment", label: "Опрема", status: "soon", icon: Backpack },
];

/**
 * The leaves one column of one vertical's menu should show.
 *
 * One function so the desktop menu, the mobile drawer and the listing rail
 * cannot disagree about whether the men's column has sports bras in it.
 */
export function categoriesFor(
  kind: string | undefined,
  gender?: GenderSlug,
): ReadonlyArray<{ slug: string; label: string }> {
  const categories = VERTICALS.find((v) => v.kind === kind)?.categories ?? [];
  if (!gender) return categories;
  return categories.filter((c) => !c.genders || c.genders.includes(gender));
}

export const COMING_SOON = "Наскоро";

/** Every parameter the listing page reads out of the URL. */
export type ListingParams = {
  q?: string;
  brand?: string;
  sizeEu?: number;
  /** A letter from the ladder. Mutually exclusive with `sizeEu`. */
  size?: string;
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
  // One axis or the other, never both: no article carries an EU number and
  // a letter, so a URL holding both would return an empty page. Whichever
  // the caller set last is the one it meant, and clearing happens by passing
  // `undefined` for the other.
  if (params.sizeEu !== undefined) sp.set("sizeEu", String(params.sizeEu));
  else if (params.size) sp.set("size", params.size);
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
  // Both trees, because a listing can be either vertical now. Looked up by
  // slug across all of them rather than by `params.kind`, so a link that
  // carries a category but no kind still gets its real heading.
  const category = [...FOOTWEAR_CATEGORIES, ...APPAREL_CATEGORIES].find(
    (c) => c.slug === params.category,
  )?.label;
  const vertical = VERTICALS.find((v) => v.kind === params.kind)?.label;
  const gender = GENDER_COLUMNS.find(
    (g) => g.slug === params.gender,
  )?.adjectiveLabel;

  const noun = category ?? vertical ?? "Обувки";
  return gender ? `${gender} ${noun.toLowerCase()}` : noun;
}
