/**
 * Listing sort keys, shared by the server page and the client control.
 *
 * Deliberately NOT in `sort-select.tsx`. That file is `"use client"`, and
 * every export of a client module becomes a client reference when a server
 * component imports it -- so `isSortKey` arrived on the server as a proxy
 * rather than a function and the listing answered 500:
 *
 *     Attempted to call isSortKey() from the server but isSortKey is on
 *     the client.
 *
 * Plain data and plain functions that both sides need belong in a module
 * with no directive at all, which is this one.
 *
 * The keys match `CatalogRepository.Sort` on the API side. Labels are
 * Macedonian because the storefront is, and these are the words the local
 * shops use for the same controls -- someone arriving from sportvision.mk
 * reads "Најевтино" and already knows what it does.
 */
export const SORTS = [
  { value: "cheapest", label: "Најевтино" },
  { value: "expensive", label: "Најскапо" },
  { value: "discount", label: "Најголем попуст" },
  { value: "title", label: "По наслов" },
] as const;

export type SortKey = (typeof SORTS)[number]["value"];

/**
 * What the listing shows when `sort` is absent, named for the control rather
 * than for the mechanism.
 *
 * The API's own default orders by how many shops carry each product, so the
 * page opens with the products where a comparison is worth something -- and
 * not with the 219 MKD oddity that exactly one shop sells. That ordering is
 * deliberately NOT one of `SORTS`: "by number of shops" is a mechanism, not
 * something a shopper thinks in, and offering it would clutter a control
 * whose job is the four orderings they might actually want.
 *
 * It is a `<option hidden>`, so the closed control can say what the page is
 * doing without the open list growing a fifth entry. Showing "Најевтино"
 * instead would be the control lying about the order on screen.
 */
export const DEFAULT_SORT_LABEL = "Препорачано";

export function isSortKey(value: string | undefined): value is SortKey {
  return SORTS.some((sort) => sort.value === value);
}
