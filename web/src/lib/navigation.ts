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
import {
  Backpack,
  Footprints,
  Shirt,
  SprayCan,
  type LucideIcon,
} from "lucide-react";

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
/**
 * The three departments a fragrance is sold to.
 *
 * Not `GENDER_COLUMNS`, and the third column is why: that one ends in Деца,
 * which no perfumery here has a shelf for, while Унисекс is a real and large
 * department -- 218 of e-elixir's 697 bottles, and the only one of the three
 * that the catalogue infers rather than reads (a fragrance listed in both
 * adult departments).
 *
 * Adjective forms, because each heading sits above a noun the shopper
 * completes: Машки · Тоалетни води.
 */
export const FRAGRANCE_GENDER_COLUMNS: ReadonlyArray<{
  slug: string;
  label: string;
}> = [
  { slug: "men", label: "Машки" },
  { slug: "women", label: "Женски" },
  { slug: "unisex", label: "Унисекс" },
];

/**
 * The four strengths, as a shopper asks for them.
 *
 * `value` is what reaches the API's `?concentration=`, and the last entry
 * names two: the shops shelve PARFUM and EXTRAIT together under Парфеми and
 * a shopper reading that word does not separate them. Keeping them apart in
 * the menu would offer two entries whose difference nobody can act on --
 * while still keeping them apart in the data, where "Parfum" and "Extrait
 * de Parfum" are genuinely different bottles at different prices.
 */
export const CONCENTRATIONS: ReadonlyArray<{
  value: string;
  label: string;
  short: string;
}> = [
  { value: "EDP", label: "Парфимирани води", short: "EDP" },
  { value: "EDT", label: "Тоалетни води", short: "EDT" },
  { value: "EDC", label: "Колонски води", short: "EDC" },
  { value: "PARFUM,EXTRAIT", label: "Парфеми", short: "Парфем" },
];

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

/**
 * The Опрема leaves, as V23 seeded them.
 *
 * `hidden` keeps a leaf out of the menu and the sidebar while it exists in
 * the database. Four of these draw on only two or three shops and may come
 * in under a hundred products; an entry serving six percent of the stock
 * reads as an empty site rather than an unfinished one. The data still has
 * somewhere truthful to go, the URL still works, and flipping one on after
 * the first sweep is a one-line change with no migration.
 *
 * `genders` is unused here, unlike apparel. Equipment has no leaf that one
 * department does not stock: sports bras had zero men's products, while a
 * backpack is a backpack.
 */
export const ACCESSORY_CATEGORIES: ReadonlyArray<{
  slug: string;
  label: string;
  hidden?: boolean;
}> = [
  { slug: "bags_backpacks", label: "Торби и ранци" },
  { slug: "caps_hats", label: "Капи, качкети и бандани" },
  { slug: "socks", label: "Чорапи" },
  { slug: "protective_gear", label: "Кациги, наочари и ракавици" },
  { slug: "balls_training", label: "Топки и фитнес опрема" },
  { slug: "skates_scooters", label: "Ролери и тротинети" },
  // Shown from 2026-11-21: 106 products, once sport-m and Sport Vision
  // completed the Опрема vertical. The threshold this clears is the comment
  // above -- a leaf under a hundred products reads as an empty site.
  { slug: "swim_gear", label: "Опрема за пливање" },
  { slug: "bottles_thermos", label: "Шишиња и термоси", hidden: true },
  { slug: "wallets", label: "Паричници", hidden: true },
  { slug: "shoe_care_laces", label: "Врвки и нега на обувки", hidden: true },
  { slug: "other_accessories", label: "Друго", hidden: true },
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
    hidden?: boolean;
  }>;
  /**
   * Whether the menu splits into Мажи / Жени / Деца columns.
   *
   * True for shoes and clothing, where the departments hold different
   * stock. False for Опрема, where they would not: 55 percent of Sport
   * Vision's equipment is unisex and 66 percent of Sport Reality's, and
   * since a men's listing already includes unisex, the two adult columns
   * would be roughly 85 percent the same links. Two of the six shops do not
   * gender their equipment section at all -- Sport Reality's sits outside
   * the gender tabs entirely, and Sport-M publishes 758 articles with no
   * gender in any URL.
   *
   * Kids is the one cut that earns its place -- ролери, тротинети, кациги
   * are a different shelf -- so it gets a link rather than a column.
   */
  /**
   * Whether this vertical's menu lists strengths rather than category
   * leaves, in Машки / Женски / Унисекс columns.
   *
   * A separate flag rather than a third value of `genderColumns`, because
   * the two questions are independent: this one is about what the links
   * narrow *by*, and the columns it draws are a different triple.
   */
  byConcentration?: boolean;
  genderColumns?: boolean;
};

export const VERTICALS: ReadonlyArray<Vertical> = [
  {
    kind: "footwear",
    label: "Обувки",
    status: "live",
    icon: Footprints,
    allLabel: "Сите обувки",
    categories: FOOTWEAR_CATEGORIES,
    genderColumns: true,
  },
  {
    kind: "apparel",
    label: "Облека",
    status: "live",
    icon: Shirt,
    allLabel: "Сета облека",
    categories: APPAREL_CATEGORIES,
    genderColumns: true,
  },
  {
    // `accessory`, not `equipment`: V23 folded the two kinds into one and
    // kept the larger. The label is unchanged, because it was never the
    // slug that shoppers read.
    kind: "accessory",
    label: "Опрема",
    status: "live",
    icon: Backpack,
    allLabel: "Сета опрема",
    categories: ACCESSORY_CATEGORIES,
    genderColumns: false,
  },
  {
    // The fourth vertical, V27. Its menu is the only one not built from
    // category leaves: the catalogue has exactly one fragrance leaf
    // (`perfume`), because the thing a shopper narrows by is not the article
    // type -- every one of them is a bottle -- but its strength.
    kind: "fragrance",
    label: "Парфеми",
    status: "live",
    icon: SprayCan,
    allLabel: "Сите парфеми",
    byConcentration: true,
  },
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
  const categories = (
    VERTICALS.find((v) => v.kind === kind)?.categories ?? []
  ).filter((c) => !c.hidden);
  if (!gender) return categories;
  return categories.filter((c) => !c.genders || c.genders.includes(gender));
}

/** Every leaf of a vertical, hidden ones included, for titling a listing. */
export function allCategoriesFor(
  kind: string | undefined,
): ReadonlyArray<{ slug: string; label: string }> {
  return VERTICALS.find((v) => v.kind === kind)?.categories ?? [];
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
  /**
   * A fragrance strength, or several separated by commas. Carried here
   * rather than assembled at the call site for the reason the whole builder
   * exists: anything not in this type is silently dropped the moment a
   * shopper touches another filter.
   */
  concentration?: string;
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
  if (params.concentration) sp.set("concentration", params.concentration);
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
  const category = [
    ...FOOTWEAR_CATEGORIES,
    ...APPAREL_CATEGORIES,
    ...ACCESSORY_CATEGORIES,
  ].find((c) => c.slug === params.category)?.label;
  const vertical = VERTICALS.find((v) => v.kind === params.kind)?.label;
  const gender = GENDER_COLUMNS.find(
    (g) => g.slug === params.gender,
  )?.adjectiveLabel;

  const noun = category ?? vertical ?? "Обувки";
  return gender ? `${gender} ${noun.toLowerCase()}` : noun;
}
