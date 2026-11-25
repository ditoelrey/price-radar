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

/**
 * One brand the current listing scope actually has products in.
 *
 * Replaces the sidebar's own fixed list. `productCount` is what the listing
 * would return for that brand under the same filters, so the facet and the
 * page it leads to cannot disagree.
 */
export type BrandFacet = {
  slug: string;
  name: string;
  productCount: number;
};

/**
 * One shop that sells inside the current listing scope.
 *
 * Same shape and same reason as `BrandFacet`. The sidebar's "Продавници
 * што ги споредуваме" rail was a fixed array of the six sneaker shops, so
 * a shopper on Машки парфеми read that we compare Sport Vision and Sizeer
 * -- neither of which sells perfume -- and was not told about e-elixir or
 * Schatze, which is where every offer on that page came from.
 */
export type MerchantFacet = {
  slug: string;
  name: string;
  productCount: number;
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

export type SearchParams = {
  q?: string;
  brand?: string;
  sizeEu?: number;
  /** A letter from the ladder, XXS to 5XL. The garment half of `sizeEu`. */
  size?: string;
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
      concentration: params.concentration,
      sort: params.sort,
      page: params.page ?? 0,
      pageSize: params.pageSize ?? 24,
    })}`,
  );
}

/**
 * Brands with products under the given scope, commonest first.
 *
 * Asked with the listing's own filters minus the brand, so the sidebar
 * offers exactly the brands whose pages would return something. The
 * sidebar used to render a fixed list of twelve sneaker brands, which was
 * right while the catalogue was shoes and is now wrong in both directions:
 * Hoka and Jordan on the apparel listing where they have nothing, and none
 * of Ajmal, Lattafa or Dolce & Gabbana under Парфеми.
 *
 * Failure is survivable and silent on purpose. A listing that cannot show a
 * brand filter is still a usable listing, whereas a listing that throws
 * because a facet call failed is not.
 */
export async function fetchBrandFacets(
  params: Pick<SearchParams, "q" | "kind" | "category" | "gender" | "concentration">,
): Promise<BrandFacet[]> {
  try {
    return await get<BrandFacet[]>(
      `/api/v1/brands${buildQuery({
        q: params.q,
        kind: params.kind,
        category: params.category,
        gender: params.gender,
        concentration: params.concentration,
        limit: 40,
      })}`,
    );
  } catch {
    return [];
  }
}

/**
 * The shops this listing actually compares.
 *
 * Silent on failure like `fetchBrandFacets`, and for the same reason: a
 * listing missing its shop rail is still a usable listing. The caller
 * renders nothing rather than falling back to a guess, because a wrong
 * rail is what this replaced.
 */
export async function fetchMerchantFacets(
  params: Pick<SearchParams, "q" | "kind" | "category" | "gender" | "concentration">,
): Promise<MerchantFacet[]> {
  try {
    return await get<MerchantFacet[]>(
      `/api/v1/merchants${buildQuery({
        q: params.q,
        kind: params.kind,
        category: params.category,
        gender: params.gender,
        concentration: params.concentration,
        limit: 20,
      })}`,
    );
  } catch {
    return [];
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
