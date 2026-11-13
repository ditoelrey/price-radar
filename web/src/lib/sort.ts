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

/** The order the listing falls back to, and the one we keep out of the URL. */
export const DEFAULT_SORT: SortKey = "cheapest";

export function isSortKey(value: string | undefined): value is SortKey {
  return SORTS.some((sort) => sort.value === value);
}
