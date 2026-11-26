/**
 * Client for the Price Radar serving API.
 *
 * Every call runs on the server (React Server Components), which is why
 * filtering is driven by URL search params rather than client state: the
 * browser never talks to the Spring API, so there is no CORS surface, no API
 * origin to expose, and a filtered page is a real URL a shopper can share or
 * bookmark.
 *
 * The types mirror `mk.priceradar.api.catalog.Dtos` exactly. They are hand
 * written rather than generated because they are small and because a drift
 * between the two is something a reader should be able to spot.
 */

const API_BASE =
  process.env.API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8080";

/** Integer money plus its exponent. MKD has none: 2863 means 2 863 denars. */
export type Money = {
  amountMinor: number;
  currency: string;
  minorUnit: number;
};

/** What we can honestly say about a size's availability. */
export type StockState =
  | "IN_STOCK"
  | "SOLD_OUT"
  /** The shop does not publish availability at all (sizeer). */
  | "NOT_PUBLISHED"
  /** Last checked too long ago to keep asserting "in stock". */
  | "STALE";

/**
 * One listing card.
 *
 * The three fields the fragrance vertical added are marked optional, and
 * that is about Next's fetch cache rather than about the API. A listing
 * response is cached for 60 seconds; deploy an API that gained a field and
 * the next render can still be served a body from before it existed. The
 * card then reads `.length` off undefined and takes the whole page down --
 * which is what happened to Обувки, Облека and Опрема the first time
 * these shipped, until a refresh picked up a fresh body.
 *
 * Optional here forces every reader to say what it does without them, so a
 * version skew degrades a card instead of breaking a vertical.
 */
export type ProductCard = {
  slug: string;
  name: string;
  brand: string;
  colorway: string | null;
  imageUrl: string | null;
  mpn: string | null;
  /**
   * Canonical category leaf, English: `sneakers`, `cleats`, `shoes_boots`,
   * `slides_sandals`, or the parent `footwear` meaning "a shoe, kind
   * unspecified". Null when nothing has said yet, which is a real answer and
   * not a bug: a guessed category is how a pack of socks once reached the
   * footwear storefront.
   */
  category: string | null;
  /** The same category in Macedonian. Display comes from the API, not here. */
  categoryMk: string | null;
  /**
   * `men`, `women`, `kids`, `unisex`, or null when no shop department or
   * title said. `unisex` is a finding -- the article is listed in both adult
   * departments -- not a fallback for silence.
   */
  gender: string | null;
  fromPrice: Money | null;
  /**
   * The dearest variant, or null when there is no range to show.
   *
   * Null in two cases, and the card must treat them the same: a product
   * sold in one size, and any size-filtered page, where the product's
   * overall maximum covers sizes the shopper has filtered out. Both mean
   * "quote one price, not a range".
   */
  toPrice?: Money | null;
  offerCount: number;
  merchantCount: number;
  /**
   * True when `fromPrice` was computed for the requested size rather than
   * taken from the product's overall minimum. The distinction is the whole
   * point of the size filter and the UI has to show it.
   */
  fromPriceIsSizeSpecific: boolean;
  availableSizesEu: number[];
  /**
   * Letter sizes, smallest first, already in ladder order from the API.
   * Never re-sorted here: sorting these as strings gives 3XL, L, M, S, XL.
   *
   * A product fills this or `availableSizesEu`, never both, so which one has
   * entries is how the rail knows which axis it is on.
   */
  availableSizes: string[];
  /**
   * Bottle volumes in millilitres a shopper can buy, smallest first.
   *
   * The third size axis. A product fills exactly one of the three -- EU
   * numbers for shoes, letters for garments, millilitres for fragrances --
   * so which list has entries tells the card which rail to draw.
   *
   * Empty is a real answer for a fragrance whose every bottle is sold out,
   * since the rail only ever lists what is buyable.
   */
  availableVolumesMl?: number[];
  /**
   * Normalised fragrance strength -- `EDP`, `EDT`, `EDC`, `PARFUM`,
   * `EXTRAIT`, `ELIXIR`, `ABSOLU`, `COLOGNE` -- or null outside the
   * fragrance vertical.
   */
  concentration?: string | null;
  /**
   * Best advertised saving on this product, as whole percent, or null when
   * no shop is discounting it. Null rather than 0, so the card can treat
   * "present" as "worth a badge".
   */
  discountPct: number | null;
  updatedAt: string | null;
};

export type ProductPage = {
  items: ProductCard[];
  page: number;
  pageSize: number;
  hasMore: boolean;
  /**
   * Every product the filters match, not just this page's worth.
   *
   * Optional for cache skew: an ISR payload rendered before the API served
   * this field has none, and the pagination bar falls back to what it can
   * infer from `hasMore` rather than claiming "page 3 of 1".
   */
  total?: number;
  appliedSizeFilter: string | null;
};

export type OfferVariant = {
  id: number;
  /** Whatever the shop printed, junk included. Prefer `displaySize`. */
  sizeLabel: string;
  sizeEu: number | null;
  /** The canonical letter, or null when this variant is not on that ladder. */
  sizeAlpha: string | null;
  /**
   * `alpha`, `age`, `height`, `numeric`, or null.
   *
   * `numeric` is the sizing parser's catch-all rather than a system, and on
   * apparel it is almost entirely Sport Vision's template dictionary -- NS,
   * 1X, YMD, 2XLT -- rendered into every garment page and sold in none of
   * them. 2 479 NS variants exist and not one is in stock.
   */
  sizeSystem: string | null;
  /**
   * The upper letter when the shop's label names a span ("M/L"), with
   * `sizeAlpha` the lower. Null for an ordinary single letter.
   */
  sizeAlphaMax?: string | null;
  price: Money | null;
  listPrice: Money | null;
  shipping: Money | null;
  totalPrice: Money | null;
  stock: StockState;
  stockQty: number | null;
  checkedAt: string | null;
  /** Always our own endpoint, never the shop's URL. */
  outUrl: string;
};

export type Offer = {
  id: number;
  merchantSlug: string;
  merchantName: string;
  merchantRating: number | null;
  merchantReviewCount: number;
  publishesStock: boolean;
  deliveryEstimate: string | null;
  fromPrice: Money | null;
  fromTotalPrice: Money | null;
  /** Set when another shop on this page shares an operator with it. */
  sameOperatorAs: string | null;
  variants: OfferVariant[];
};

export type ProductDetail = {
  slug: string;
  name: string;
  brand: string;
  /**
   * The brand's own slug, as `?brand=` wants it.
   *
   * Optional only for cache skew: a payload rendered before the API served
   * this field has none, and the breadcrumb falls back to dropping the
   * brand filter rather than guessing a slug. Guessing is what it used to
   * do -- lower-case the name, spaces to hyphens -- and that is wrong for
   * 18 brands, most of them perfumeries: `dolce-&-gabbana`, `lancôme`,
   * `joop!`, `van-cleef-&-arpels`.
   */
  brandSlug?: string;
  colorway: string | null;
  gender: string | null;
  mpn: string | null;
  imageUrl: string | null;
  /** `footwear`, `apparel`, ... or null when nothing has classified it. */
  categoryKind: string | null;
  category: string | null;
  /** The leaf in Macedonian, for the breadcrumb. */
  categoryMk: string | null;
  lowestPrice: Money | null;
  highestPrice: Money | null;
  offerCount: number;
  merchantCount: number;
  availableSizesEu: number[];
  availableSizes: string[];
  updatedAt: string | null;
  priceDisclaimer: string;
  offers: Offer[];
};

/**
 * One option of one filter group, with the number beside it.
 *
 * The shape every control shares. `value` is what travels in the URL, `label`
 * is what the API knows to call it -- a brand's own name, a leaf's Macedonian
 * name, a bare gender or price band id the storefront words itself.
 */
export type FacetOption = {
  value: string;
  label: string;
  productCount: number;
};

/** One size option, and which of the three ladders it is a rung of. */
export type SizeFacetOption = {
  /** `eu`, `alpha` or `ml`. */
  axis: string;
  value: string;
  productCount: number;
};

/**
 * Every filter control for one listing scope, in one response.
 *
 * Each group is counted with every other group's filters applied and its own
 * left out, so a count reads as "this many if you tick this too" rather than
 * "this many, given what you have already picked". That is what makes a
 * multi-select usable: with its own filter applied, every unticked option in
 * a group would count zero.
 *
 * Optional fields for cache skew, the same reason the card's are: a body
 * cached by `fetch` before the API served a group has none, and a missing
 * group renders as no section rather than taking the page down.
 */
export type Facets = {
  genders?: FacetOption[];
  categories?: FacetOption[];
  /**
   * Fragrance strengths, which are that vertical's product types.
   *
   * `fragrances` is its only category leaf, so the Производи control is
   * filled from here instead: EDT, EDP, a cologne, a parfum -- the thing a
   * shopper on that storefront actually picks between.
   */
  concentrations?: FacetOption[];
  sizes?: SizeFacetOption[];
  brands?: FacetOption[];
  shops?: FacetOption[];
  prices?: FacetOption[];
};

export type SearchParams = {
  q?: string;
  /**
   * Every filter group takes a comma-separated list now: `nike,adidas` is a
   * page about both. One value is still one value, so every link written
   * before this change means what it meant.
   */
  brand?: string;
  sizeEu?: string;
  /** Letters and millilitres, which share this parameter. */
  size?: string;
  /** Merchant slugs. */
  shop?: string;
  /** Price band ids: `0-1000`, `10000-`. */
  price?: string;
  /**
   * Which category kinds the listing serves: `footwear` (the default on the
   * API side), `apparel`, `accessory`, `equipment`, or `all`.
   */
  kind?: string;
  /** One canonical leaf. Matched exactly, so it never returns the parent. */
  category?: string;
  /** `men` and `women` include unisex, as the shops' own departments do. */
  gender?: string;
  /** A fragrance strength, or several separated by commas. */
  concentration?: string;
  /** One of `SORTS` in `sort-select`; the API falls back to cheapest. */
  sort?: string;
  page?: number;
  pageSize?: number;
};

function buildQuery(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && !Number.isNaN(value)) {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    // Prices move. A short revalidate keeps listing pages cheap without
    // serving a figure that is materially older than the API's own data.
    next: { revalidate: 60 },
  });
  if (!response.ok) {
    throw new Error(`API ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

export async function searchProducts(params: SearchParams): Promise<ProductPage> {
  return get<ProductPage>(
    `/api/v1/products${buildQuery({
      q: params.q,
      brand: params.brand,
      sizeEu: params.sizeEu,
      size: params.size,
      kind: params.kind,
      category: params.category,
      gender: params.gender,
      shop: params.shop,
      price: params.price,
      concentration: params.concentration,
      sort: params.sort,
      page: params.page ?? 0,
      pageSize: params.pageSize ?? 24,
    })}`,
  );
}

/**
 * Every filter control for the current scope.
 *
 * Asked with the listing's own filters, all of them: the API leaves each
 * group's own filter out of that group's count, which is the only way the
 * numbers beside the boxes mean anything in a multi-select.
 *
 * Failure is survivable and silent, like the two facet calls it replaces. A
 * listing with no filters is still a usable listing; a listing that throws
 * because a facet call failed is not. Every group comes back empty and the
 * sidebar renders nothing rather than a guess -- guessing is what the old
 * hardcoded brand list and shop rail did.
 */
export async function fetchFacets(
  params: Omit<SearchParams, "sort" | "page" | "pageSize">,
): Promise<Facets> {
  try {
    return await get<Facets>(
      `/api/v1/facets${buildQuery({
        q: params.q,
        brand: params.brand,
        sizeEu: params.sizeEu,
        size: params.size,
        kind: params.kind,
        category: params.category,
        gender: params.gender,
        shop: params.shop,
        price: params.price,
        concentration: params.concentration,
        limit: 120,
      })}`,
    );
  } catch {
    return {};
  }
}

export async function getProduct(
  slug: string,
  sizeEu?: number,
  /** The non-EU axis: a letter, or a kids' age or height band. */
  size?: string,
): Promise<ProductDetail | null> {
  const response = await fetch(
    `${API_BASE}/api/v1/products/${encodeURIComponent(slug)}${buildQuery({ sizeEu, size })}`,
    { headers: { Accept: "application/json" }, next: { revalidate: 60 } },
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API ${response.status} for ${slug}`);
  return (await response.json()) as ProductDetail;
}

/** Where an outbound click goes. Our endpoint logs it, then 302s to the shop. */
export function outboundUrl(variantId: number): string {
  return `${
    process.env.NEXT_PUBLIC_OUT_BASE_URL?.replace(/\/$/, "") ?? ""
  }/out/${variantId}`;
}
