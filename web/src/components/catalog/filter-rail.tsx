import {
  FilterSection,
  GroupBody,
} from "@/components/catalog/filter-controls";
import { SearchableGroup } from "@/components/catalog/searchable-group";
import { type FilterGroupModel } from "@/lib/filters";

/**
 * The desktop filter rail.
 *
 * Six accordion sections in the same order on every vertical -- Пол,
 * Категорија, Големина, Бренд, Продавница, Цена -- because a shopper who
 * learns where the size control is on Обувки should find it in the same place
 * on Парфеми. A group with nothing to offer is left out entirely rather than
 * rendered empty: a heading over nothing reads as a broken page, and `Пол` on
 * a listing where every product is unisex has nothing to say.
 *
 * `Сортирај` is not here any more. It is not a filter -- it does not change
 * what the page holds, only the order -- and it sat at the top of this rail
 * where it was both the first thing a shopper read and the thing they were
 * least likely to want. It now lives at the top right of the grid, where
 * every shop a Macedonian shopper already uses puts it.
 *
 * Hidden below `lg`, where the same groups are reached through the pill row.
 * Rendered for both, from the same models.
 */
export function FilterRail({ groups }: { groups: FilterGroupModel[] }) {
  const shown = groups.filter(
    (group) => group.options.length > 0 || (group.sections?.length ?? 0) > 0,
  );
  if (shown.length === 0) return null;

  return (
    <aside className="hidden w-64 shrink-0 lg:block">
      <div className="rounded-lg border bg-card px-4 py-1">
        {shown.map((group, index) => (
          <FilterSection
            key={group.key}
            title={group.title}
            selectedCount={group.selectedCount}
            // The first three open, the rest closed. Пол, Категорија and
            // Големина are what a shopper narrows by first, and opening all
            // six would put Цена below the fold of a laptop screen.
            defaultOpen={index < 3}
          >
            {group.search ? (
              <SearchableGroup group={group} />
            ) : (
              <GroupBody group={group} />
            )}
          </FilterSection>
        ))}
      </div>

      <p className="mt-3 px-1 text-[11px] leading-relaxed text-muted-foreground">
        Понудите се подредени според вкупна цена со достава — никогаш според
        тоа колку продавницата ни плаќа.
      </p>
    </aside>
  );
}
