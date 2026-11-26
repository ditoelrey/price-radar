"use client";

import { useState } from "react";

import { GroupBody } from "@/components/catalog/filter-controls";
import { filterBrands } from "@/lib/brand-match";
import { type FilterGroupModel } from "@/lib/filters";

/**
 * The Бренд list, with the only search box in the sidebar.
 *
 * The one group that needs client state, and the only one that gets any: a
 * footwear listing carries sixty brands and a shopper usually arrives knowing
 * the word they want. Everything else in the rail is a link rendered on the
 * server.
 *
 * The matching is in `lib/brand-match`, which is the point of this control:
 * the catalogue holds the brands' own Latin names and a Macedonian shopper
 * types `адидас`, `најк`, `нју баланс`. A plain `includes` answers all three
 * with "Нема резултати", which reads as a catalogue that does not carry them.
 *
 * The query is not in the URL. It picks nothing -- the boxes still do that --
 * and putting it there would make "I was looking for Puma" part of a link a
 * shopper shares.
 */
export function SearchableGroup({ group }: { group: FilterGroupModel }) {
  const [query, setQuery] = useState("");
  const shown = query.trim()
    ? filterBrands(group.options, query)
    : group.options;

  return (
    <GroupBody
      group={{ ...group, options: shown }}
      query={query}
      onQueryChange={setQuery}
    />
  );
}
