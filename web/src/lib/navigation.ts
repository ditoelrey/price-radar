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
 * What a listing link may narrow the audience to.
 *
 * `adults` is the extra one and it is not a department: it means men, women
 * and unisex together, but not kids. The Опрема menu needs it. That
 * vertical stopped splitting Мажи from Жени -- most equipment is unisex, so
 * the two columns were roughly 85 percent the same links -- while a leaf
 * link carrying no gender at all would show 19-21 baby socks beside a men's
 * three-pack, which is the mixing the split was made to end.
 *
 * The API reads it as `gender=adults`; see the predicate in
 * `CatalogRepository`, which also lets an unclassified article through,
 * because "we do not know who this is for" must not mean "hidden from the
 * only adult route there is".
 */
export type AudienceSlug = GenderSlug | "adults";

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
 * Ordered as a shopper meets them rather than by strength: the toilette
 * waters are the commonest shelf, the parfums the rarest, and a menu that
 * opened with the rarest would bury the entry most people want.
 *
 * `value` is what reaches the API's `?concentration=`, and the last entry
 * names four: PARFUM, EXTRAIT, ELIXIR and ABSOLU are all the concentrated
 * form, the shops shelve them together under Парфеми, and a shopper reading
 * that word does not separate them. Keeping them apart in the menu would
 * offer four entries whose difference nobody can act on -- while still
 * keeping them apart in the data, where "Parfum", "Extrait de Parfum",
 * "Elixir de Parfum" and "Absolu de Parfum" are genuinely different bottles
 * at different prices.
 *
 * The list has to hold every concentrated spelling the parser can produce,
 * because these four entries are the only route into the vertical from the
 * menu: a strength missing here is a product no shopper can reach. ELIXIR
 * and ABSOLU were missing, and six bottles -- Gucci Guilty Elixir among
 * them -- sat outside all four shortcuts.
 */
export const CONCENTRATIONS: ReadonlyArray<{
  value: string;
  label: string;
  /** The abbreviation a shopper scans for, or null where there is none. */
  short: string | null;
}> = [
  { value: "EDT", label: "Тоалетни води", short: "EDT" },
  { value: "EDP", label: "Парфимирани води", short: "EDP" },
  { value: "EDC", label: "Колонски води", short: "EDC" },
  // No abbreviation: "Парфем - Парфеми" would be the same word twice.
  { value: "PARFUM,EXTRAIT,ELIXIR,ABSOLU", label: "Парфеми", short: null },
];

/**
 * A gender, in the adjective form that labels a product rather than a
 * department.
 *
 * `FRAGRANCE_GENDER_COLUMNS` cannot serve here: it is a menu's three
 * columns and has no entry for деца, while a badge has to be able to
 * render whatever the catalogue holds.
 */
export const GENDER_LABEL_MK: Readonly<Record<string, string>> = {
  men: "Машки",
  women: "Женски",
  unisex: "Унисекс",
  kids: "Детски",
};

/**
 * Whether a card is showing a bottle of perfume.
 *
 * Gates the three things only a fragrance card does: name its audience,
 * list its volumes, and quote a price range.
 *
 * **The audience**, because fragrance names collide. The Arabic houses
 * and several western ones sell one line in a men's and a women's version
 * -- "Ajmal Amaze EDP" is two products at 2 145 and 3 065 den -- and the
 * catalogue gives both the same `canonical_name`, because the audience is
 * deliberately not in it: putting it there would stop e-elixir's "Moschino
 * Toy 2 ... for women" ever meeting Schatze's "Toy 2 - edt".
 *
 * So the badge is what distinguishes them on screen. A sneaker needs no
 * such badge: the listing that shows it is already scoped to a department.
 *
 * **The price range**, because for a fragrance the two ends are the same
 * article in two bottles -- 30ml and 100ml -- and the shopper is choosing
 * between them. For a shoe the two ends are two different shops, and the
 * dearer one is not an option anybody wants: the cheapest is the answer,
 * which is why every other card says "од" and one number.
 */
export function isFragrance(category: string | null): boolean {
  return category === "perfume";
}

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
  /** Which Опрема column this leaf appears in. Absent means both. */
  audiences?: ReadonlyArray<AudienceSlug>;
  hidden?: boolean;
}> = [
  // `audiences` is which of the two Опрема columns a leaf appears in, and
  // every entry below is set from a count, not a guess. Measured
  // 2026-11-25, live products per leaf, kids column first:
  //
  //     caps_hats        208 kids   socks            151
  //     gloves            90        bags_backpacks    84
  //     skates_scooters   47        swim_gear         36
  //     protective_gear   31        balls_training    21
  //     other_accessories  2        bottles/laces/wallets 0
  //
  // The line is drawn at 30. Below it a column entry promises a shelf and
  // delivers a handful, which is the dead-facet failure this menu already
  // removed from the brand list -- so `Топки и тренинг опрема` (21, because
  // balls are unisex) and `Останата опрема` (2) are adults-only.
  { slug: "bags_backpacks", label: "Торби и ранци" },
  { slug: "caps_hats", label: "Капи, качкети и бандани" },
  { slug: "socks", label: "Чорапи" },
  // V33 split this out of `protective_gear`, where 298 gloves sat beside
  // helmets and shin guards. Not "winter gloves": of those 298 only 115
  // state a kind at all -- 183 are "Brugi Rakavici Crni", brand, article
  // and colour -- and no shop publishes a winter-glove shelf.
  { slug: "gloves", label: "Ракавици" },
  { slug: "protective_gear", label: "Кациги, наочари и заштитници" },
  {
    slug: "balls_training",
    label: "Топки и тренинг опрема",
    audiences: ["adults"],
  },
  // Kids only, and measured rather than assumed: 47 of its 48 products are
  // children's, leaving one for the adult shelf.
  {
    slug: "skates_scooters",
    label: "Ролери и тротинети",
    audiences: ["kids"],
  },
  { slug: "swim_gear", label: "Опрема за пливање" },
  // Unhidden 2026-11-25: 126 products no menu entry reached -- hair ties,
  // phone covers, Crocs charms, face masks. The shops' own word for the
  // shelf is "Останата опрема", so the menu uses that rather than the bare
  // "Друго" the category row carries.
  {
    slug: "other_accessories",
    label: "Останата опрема",
    audiences: ["adults"],
  },
  // Visible from 2026-11-25 at 11 products, which is the one leaf that
  // gets to break the hundred-product rule. A wallet is a thing a shopper
  // arrives looking for by name, and the leaf exists because megasport
  // publishes one combined "Ранци и Паричници" facet that nothing but a
  // wallet's own name can be separated out of -- see the ordering note in
  // `taxonomy._RULES`. Kids: zero, so it is adults-only.
  { slug: "wallets", label: "Паричници", audiences: ["adults"] },
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
    /** Which Опрема column this leaf appears in. Absent means both. */
    audiences?: ReadonlyArray<AudienceSlug>;
    hidden?: boolean;
  }>;
  /**
   * Whether the menu splits into Мажи / Жени / Деца columns.
   *
   * True for all three stocked verticals now, Опрема included.
   *
   * Опрема was false, and the reasoning was about the adult columns: 55
   * percent of Sport Vision's equipment is unisex and 66 percent of Sport
   * Reality's, a men's listing already includes unisex, so Мажи and Жени
   * are roughly 85 percent the same links. That is still true, and it is
   * still the weakest part of this menu.
   *
   * What it missed is the other direction. Without columns the only route
   * to a leaf is ungendered -- `?kind=accessory&category=socks` -- and that
   * listing holds every kids' item in the leaf. Measured: 151 of the 712
   * products under Чорапи are kids', 210 of 1 060 under Капи, 117 of 444
   * under Кациги, 717 across the vertical, 19 percent of it. A shopper
   * looking at socks was shown 19-21 baby socks next to a men's three-pack
   * and had no way to ask for one without the other.
   *
   * The "Опрема за деца" link in the old menu did not address that: it
   * helps someone who wants kids' things find them, and does nothing for
   * someone who does not. A gendered leaf link does, because `gender=men`
   * excludes kids while still including unisex.
   *
   * So the duplication between the two adult columns is accepted as the
   * price of the kids cut, rather than the kids cut being dropped to avoid
   * it.
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
  /**
   * Whether this vertical's menu is one general column plus a kids one,
   * rather than Мажи / Жени / Деца.
   *
   * True only for Опрема, and the measurement is the reason: 55 percent of
   * Sport Vision's equipment is unisex and 66 percent of Sport Reality's,
   * and since a men's listing already includes unisex the two adult columns
   * came out roughly 85 percent the same links. Two of the six shops do not
   * gender their equipment at all.
   *
   * The kids cut still earns its place -- 717 products, 19 percent of the
   * vertical -- so it keeps a column while the adult departments collapse
   * into one. A shopper who does want Мажи or Жени has the gender rail on
   * the listing page.
   */
  adultsAndKids?: boolean;
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
    adultsAndKids: true,
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
  audience?: AudienceSlug,
): ReadonlyArray<{ slug: string; label: string }> {
  const categories = (
    VERTICALS.find((v) => v.kind === kind)?.categories ?? []
  ).filter((c) => !c.hidden);
  if (!audience) return categories;
  // Two fields, because the two questions are different. `genders` is which
  // department stocks a garment -- a sports bra is not in the men's. The
  // Опрема leaves use `audiences`, which is which of that menu's two
  // columns a leaf is worth a line in. Absent means every column.
  return categories.filter(
    (c) =>
      (!c.genders || c.genders.includes(audience as GenderSlug)) &&
      (!c.audiences || c.audiences.includes(audience)),
  );
}

/** Every leaf of a vertical, hidden ones included, for titling a listing. */
export function allCategoriesFor(
  kind: string | undefined,
): ReadonlyArray<{ slug: string; label: string }> {
  return VERTICALS.find((v) => v.kind === kind)?.categories ?? [];
}

export const COMING_SOON = "Наскоро";

/**
 * One filter group's value: nothing, one thing, or several.
 *
 * Every group is multi-select now, and a single string is still accepted
 * because most links carry exactly one value -- the mega menu's leaves, a
 * breadcrumb, a brand link on a product page. Writing `["sneakers"]` at forty
 * call sites to say the same thing would be worse.
 */
export type Multi = string | readonly string[] | undefined;

/** Every parameter the listing page reads out of the URL. */
export type ListingParams = {
  q?: string;
  brand?: Multi;
  sizeEu?: Multi | number;
  /** A letter or a volume. Mutually exclusive with `sizeEu`. */
  size?: Multi;
  kind?: string;
  category?: Multi;
  gender?: Multi;
  /** Merchant slugs: which shops the listing is narrowed to. */
  shop?: Multi;
  /** Price band ids, as `lib/filters` spells them: `0-1000`, `10000-`. */
  price?: Multi;
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
  // The comma form rather than a repeated parameter: both reach the API as a
  // list, and this one is short enough to read in an address bar and to
  // survive being pasted into a message.
  const list = (value: ListingParams[keyof ListingParams]): string[] => {
    if (value === undefined || value === null || value === "") return [];
    if (Array.isArray(value)) return value.map(String).filter((v) => v !== "");
    return [String(value)];
  };
  const set = (
    key: string,
    value: ListingParams[keyof ListingParams],
  ): boolean => {
    const values = list(value);
    if (values.length === 0) return false;
    sp.set(key, values.join(","));
    return true;
  };

  if (params.q) sp.set("q", params.q);
  if (params.kind) sp.set("kind", params.kind);
  set("gender", params.gender);
  set("category", params.category);
  if (params.concentration) sp.set("concentration", params.concentration);
  set("brand", params.brand);
  set("shop", params.shop);
  set("price", params.price);
  // One axis or the other, never both: no article carries an EU number and
  // a letter, so a URL holding both would return an empty page. Whichever
  // the caller set last is the one it meant, and clearing happens by passing
  // `undefined` or an empty list for the other.
  if (!set("sizeEu", params.sizeEu)) set("size", params.size);
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
  //
  // One value per group, even though a group can hold several. "Машки патики
  // и копачки, Adidas и Nike" is not a heading anyone wants; with two leaves
  // ticked the title falls back to the vertical, and the chips above the grid
  // say exactly what is filtered.
  const only = (value: ListingParams[keyof ListingParams]) => {
    const values = Array.isArray(value) ? value : value ? [String(value)] : [];
    return values.length === 1 ? String(values[0]) : undefined;
  };
  const category = [
    ...FOOTWEAR_CATEGORIES,
    ...APPAREL_CATEGORIES,
    ...ACCESSORY_CATEGORIES,
  ].find((c) => c.slug === only(params.category))?.label;
  const vertical = VERTICALS.find((v) => v.kind === params.kind)?.label;
  const gender = GENDER_COLUMNS.find(
    (g) => g.slug === only(params.gender),
  )?.adjectiveLabel;

  const noun = category ?? vertical ?? "Обувки";
  return gender ? `${gender} ${noun.toLowerCase()}` : noun;
}
