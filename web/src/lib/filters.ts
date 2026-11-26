/**
 * The listing's filter state, and the one place that changes it.
 *
 * Six groups -- Пол, Категорија, Големина, Бренд, Продавница, Цена -- and
 * every one of them multi-select: OR inside a group, AND across them, which
 * is what every shop a Macedonian shopper already uses does. The API reads
 * each as a comma-separated list, so `?brand=nike,adidas&size=42,42.5` is a
 * page about two brands in two sizes.
 *
 * Why lists and not client state: a filter is a navigation here, as it has
 * been since the first size rail. The whole listing renders on the server, so
 * a filtered page is a URL a shopper can share, bookmark and back out of, and
 * there is no client store to drift from what is on screen. Every control in
 * the sidebar is therefore a `<Link>`, and this module builds its href.
 */
import { listingHref, type ListingParams } from "@/lib/navigation";
import { type SortKey } from "@/lib/sort";

/** The six groups, in the order the sidebar renders them. */
export const GROUP_KEYS = [
  "gender",
  "category",
  "size",
  "brand",
  "shop",
  "price",
] as const;

export type GroupKey = (typeof GROUP_KEYS)[number];

/**
 * Macedonian headings, as the shops label the same controls.
 *
 * `Големина` covers all three ladders: a shoe's EU number, a garment's letter
 * and a bottle's millilitres are one question to a shopper, and three
 * headings would read as three filters.
 */
export const GROUP_LABELS: Record<GroupKey, string> = {
  gender: "Пол",
  // "Производи", not "Категорија": on Обувки the options are Патики and
  // Копачки, which are things a shopper buys, and on Парфеми they are EDT
  // and EDP, which are not categories at all. One word covers both, and it
  // is the word the shops use.
  category: "Производи",
  size: "Големина",
  brand: "Бренд",
  shop: "Продавница",
  price: "Цена",
};

/**
 * The whole filter state, with every multi-select group as a list.
 *
 * `q`, `kind`, `concentration` and `sort` are not filter groups in the
 * sidebar's sense: the first two say which page this is, and the other two
 * are set elsewhere. They are carried here anyway, because anything missing
 * from this object is silently dropped the moment a shopper ticks a box --
 * which is exactly what used to happen to the category and gender the mega
 * menu sets.
 */
export type Filters = {
  q?: string;
  kind?: string;
  concentration?: string;
  sort?: SortKey;
  gender: string[];
  category: string[];
  brand: string[];
  shop: string[];
  price: string[];
  /** EU numbers. Mutually exclusive with `size`; see {@link sizeHref}. */
  sizeEu: string[];
  /** Letters and millilitres, which share the API's `size` parameter. */
  size: string[];
};

/**
 * Read one parameter as a list.
 *
 * Both spellings are accepted because both exist in the wild: Next hands
 * repeated parameters (`?brand=a&brand=b`) over as an array, and this site
 * writes the comma form (`?brand=a,b`) because it is shorter in an address
 * bar and survives being pasted into a chat window. An older single-valued
 * link is just a one-element list, so nothing shared before this change
 * stops working.
 */
export function readList(
  value: string | string[] | undefined,
): string[] {
  const raw = Array.isArray(value) ? value : value === undefined ? [] : [value];
  const out: string[] = [];
  for (const part of raw.flatMap((v) => v.split(","))) {
    const one = part.trim();
    if (one.length > 0 && !out.includes(one)) {
      out.push(one);
    }
  }
  return out;
}

/** Add a value to a list, or take it out if it is already there. */
export function toggle(list: string[], value: string): string[] {
  return list.includes(value)
    ? list.filter((v) => v !== value)
    : [...list, value];
}

/**
 * The URL for the same listing with one change applied.
 *
 * Always without `page`. Staying on page 7 of a result set that just got
 * narrower is never what someone meant, and on a listing that shrank below
 * seven pages it is an empty page -- the reason every control reset paging
 * one by one before this existed.
 */
export function filterHref(
  filters: Filters,
  patch: Partial<Filters> = {},
): string {
  const next = { ...filters, ...patch };
  const params: ListingParams = {
    q: next.q,
    kind: next.kind,
    concentration: next.concentration,
    sort: next.sort,
    gender: next.gender,
    category: next.category,
    brand: next.brand,
    shop: next.shop,
    price: next.price,
    sizeEu: next.sizeEu,
    size: next.size,
  };
  return listingHref(params);
}

/**
 * Ticking a size, on whichever ladder it belongs to.
 *
 * The axes cannot both be filtered: no article carries an EU number and a
 * letter, so a URL holding both returns an empty page. Picking a rung on one
 * ladder therefore clears the other -- which is also what a shopper means,
 * since they have just moved from one vertical to another.
 */
export function sizeHref(
  filters: Filters,
  axis: string,
  value: string,
): string {
  return axis === "eu"
    ? filterHref(filters, { sizeEu: toggle(filters.sizeEu, value), size: [] })
    : filterHref(filters, { size: toggle(filters.size, value), sizeEu: [] });
}

/**
 * The audience the Опрема menu sets, which is not a department.
 *
 * `adults` means men, women and unisex together but not kids. It arrives in
 * the gender parameter because that is the predicate it narrows, but it is
 * scope rather than a ticked box: nothing in the Пол control offers it, and
 * it survives Исчисти сè exactly as the vertical does. Ticking a real
 * department replaces it -- `adults,men` would be read as "adults OR men",
 * which is every adult product and not the men's department.
 */
export const AUDIENCE = "adults";

/** The departments a shopper actually ticked, without the menu's audience. */
export function tickedGenders(filters: Filters): string[] {
  return filters.gender.filter((value) => value !== AUDIENCE);
}

/** The audience to put back when no department is ticked, if there was one. */
export function audienceOf(filters: Filters): string[] {
  return filters.gender.includes(AUDIENCE) ? [AUDIENCE] : [];
}

/**
 * The URL with every group cleared.
 *
 * `q`, `kind`, `concentration` and the menu's audience survive: they are the
 * page a shopper is on, not a filter they applied. Clearing the filters on
 * Машки парфеми has to leave them on Парфеми, and on Опрема it has to leave
 * them among the adults' equipment rather than mixing 19-21 baby socks back
 * in beside a men's three-pack.
 */
export function clearedHref(filters: Filters): string {
  return filterHref(filters, {
    gender: audienceOf(filters),
    category: [],
    brand: [],
    shop: [],
    price: [],
    sizeEu: [],
    size: [],
  });
}

/**
 * One tickable option, with the link that ticks it.
 *
 * The href is built on the server, where the whole filter state already is,
 * so the controls carry no logic of their own -- the desktop rail and the
 * mobile drawer render the same objects and cannot disagree about what a box
 * does. `count` is the facet's promise: this many products, under exactly
 * these filters, with this box ticked too.
 */
export type FilterOption = {
  value: string;
  label: string;
  count: number;
  selected: boolean;
  href: string;
};

/**
 * One group of the sidebar, ready to render.
 *
 * `sections` is for size alone: a mixed result set can hold shoes, garments
 * and bottles, and their ladders are three lists that must not be mixed into
 * one row of chips. Every other group has a flat `options`.
 */
export type FilterGroupModel = {
  key: GroupKey;
  title: string;
  options: FilterOption[];
  sections?: Array<{ title: string; options: FilterOption[] }>;
  /** Only Бренд. Any other group is short enough to read. */
  search?: boolean;
  /**
   * One at a time, drawn as radio rows rather than checkboxes.
   *
   * Производи alone. Two product types side by side is a page about nothing
   * in particular -- patike and kopachki have different sizes, different
   * prices and different reasons to be bought -- and every shop a Macedonian
   * shopper uses makes it a choice too. Clicking the active one clears it
   * and returns the whole vertical.
   */
  single?: boolean;
  selectedCount: number;
  /**
   * Whether the section starts open on the desktop rail.
   *
   * Decided per listing rather than by position: a shopper who has not
   * picked a product type yet should land with that list open, and one who
   * arrived by clicking Патики should not have to close it again.
   */
  open?: boolean;
};

/**
 * One active filter, as the chips above the grid show it.
 *
 * `href` removes it, which is the only thing a chip does.
 */
export type ActiveChip = {
  key: GroupKey;
  value: string;
  label: string;
  href: string;
};

/**
 * The price bands, mirroring `CatalogService.PRICE_BANDS`.
 *
 * The ids are the API's and travel in the URL; the words are ours, because
 * every other label on this page is written on this side. They are repeated
 * here rather than read from the facet response so a band can be rendered
 * before its count arrives, and `hi: null` is the open top band.
 */
export const PRICE_BANDS: ReadonlyArray<{
  id: string;
  lo: number;
  hi: number | null;
}> = [
  { id: "0-1000", lo: 0, hi: 1000 },
  { id: "1000-2500", lo: 1000, hi: 2500 },
  { id: "2500-5000", lo: 2500, hi: 5000 },
  { id: "5000-10000", lo: 5000, hi: 10000 },
  { id: "10000-", lo: 10000, hi: null },
];

const DENARS = new Intl.NumberFormat("mk-MK", {
  maximumFractionDigits: 0,
});

/** "До 1.000 ден.", "1.000 – 2.500 ден.", "Над 10.000 ден." */
export function priceBandLabel(id: string): string {
  const band = PRICE_BANDS.find((b) => b.id === id);
  if (!band) return id;
  if (band.hi === null) return `Над ${DENARS.format(band.lo)} ден.`;
  if (band.lo === 0) return `До ${DENARS.format(band.hi)} ден.`;
  return `${DENARS.format(band.lo)} – ${DENARS.format(band.hi)} ден.`;
}
