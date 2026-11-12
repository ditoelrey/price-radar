import type { Money, StockState } from "@/lib/api";

/**
 * Money formatting.
 *
 * The API sends integer minor units plus the currency's exponent, and the
 * exponent is read rather than assumed: MKD is configured with `minorUnit: 0`
 * by the MK shops, so 2863 is 2 863 denars, not 28.63. Dividing by 100 out of
 * habit would show every price a hundred times too small.
 */
export function formatMoney(money: Money | null | undefined): string {
  if (!money) return "—";
  const value = money.amountMinor / 10 ** money.minorUnit;
  const formatted = new Intl.NumberFormat("mk-MK", {
    minimumFractionDigits: money.minorUnit,
    maximumFractionDigits: money.minorUnit,
  }).format(value);
  return `${formatted} ${currencySymbol(money.currency)}`;
}

export function currencySymbol(code: string): string {
  switch (code) {
    case "MKD":
      return "ден.";
    case "EUR":
      return "€";
    case "RSD":
      return "дин.";
    default:
      return code;
  }
}

/** Percentage saved against the list price, or null when there is no saving. */
export function discountPercent(
  price: Money | null | undefined,
  listPrice: Money | null | undefined,
): number | null {
  if (!price || !listPrice) return null;
  if (listPrice.amountMinor <= price.amountMinor) return null;
  const pct = Math.round(
    ((listPrice.amountMinor - price.amountMinor) / listPrice.amountMinor) * 100,
  );
  return pct > 0 ? pct : null;
}

/**
 * EU shoe sizes the way the shops write them.
 *
 * The pipeline stores 44.667 for "44 2/3"; showing the decimal would be
 * unreadable to a shopper who has only ever seen the fraction on a shoebox.
 */
export function formatSizeEu(
  size: number | null | undefined,
  fallback = "One size",
): string {
  // Null-safe because a size genuinely can be absent: dsport lists one-size
  // articles as "BEZ VELICINA" and the pipeline stores those with size_eu
  // NULL rather than inventing a number. The crash that exposed this came
  // from a different direction though -- a `sizeEu!` assertion on the detail
  // page's empty state, which told TypeScript a value was present when the
  // branch could be reached with nothing selected at all.
  if (size === null || size === undefined || Number.isNaN(size)) {
    return fallback;
  }
  const whole = Math.floor(size);
  const fraction = size - whole;
  if (fraction < 0.04) return String(whole);
  if (Math.abs(fraction - 1 / 3) < 0.04) return `${whole} ⅓`;
  if (Math.abs(fraction - 0.5) < 0.04) return `${whole} ½`;
  if (Math.abs(fraction - 2 / 3) < 0.04) return `${whole} ⅔`;
  return size.toFixed(1).replace(/\.0$/, "");
}

/** "checked 4 min ago" — shown against every price, never buried. */
export function formatCheckedAt(iso: string | null | undefined): string {
  if (!iso) return "not checked yet";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "not checked yet";
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (minutes < 1) return "checked just now";
  if (minutes < 60) return `checked ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `checked ${hours} h ago`;
  const days = Math.round(hours / 24);
  return `checked ${days} ${days === 1 ? "day" : "days"} ago`;
}

/**
 * How a stock state reads to a shopper.
 *
 * `NOT_PUBLISHED` must never render as "in stock" or as "sold out". sizeer
 * genuinely does not say, and inventing either answer is the failure the
 * whole pipeline is built to avoid.
 */
export function stockLabel(stock: StockState): {
  text: string;
  tone: "good" | "bad" | "unknown";
} {
  switch (stock) {
    case "IN_STOCK":
      return { text: "In stock", tone: "good" };
    case "SOLD_OUT":
      return { text: "Sold out", tone: "bad" };
    case "STALE":
      return { text: "Was in stock", tone: "unknown" };
    case "NOT_PUBLISHED":
    default:
      return { text: "Stock not published", tone: "unknown" };
  }
}
