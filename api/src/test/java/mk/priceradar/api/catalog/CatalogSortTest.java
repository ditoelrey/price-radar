package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import mk.priceradar.api.catalog.CatalogRepository.Sort;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/**
 * The listing sort.
 *
 * <p>This text is concatenated into SQL, so the tests here are less about
 * ordering preferences than about the two ways that can go wrong: a sort key
 * from a query string reaching the query, and a clause that does not impose a
 * total order.
 */
class CatalogSortTest {

    @Test
    @DisplayName("no sort key means the default order, not cheapest")
    void absentKeyGivesTheDefault() {
        // POPULAR is what a shopper gets when they have not asked for an
        // order. It is not in the storefront's dropdown -- "by number of
        // shops" is a mechanism rather than something anyone thinks in --
        // so this parse is the only way it is ever selected.
        assertThat(Sort.parse(null)).isEqualTo(Sort.POPULAR);
        assertThat(Sort.parse("")).isEqualTo(Sort.POPULAR);
        assertThat(Sort.parse("   ")).isEqualTo(Sort.POPULAR);
    }

    @Test
    @DisplayName("an unknown sort key falls back rather than failing")
    void unknownKeyFallsBack() {
        // A shopper with a stale or hand-edited link still wants the listing.
        assertThat(Sort.parse("newest")).isEqualTo(Sort.POPULAR);
        assertThat(Sort.parse("merchants")).isEqualTo(Sort.POPULAR);
    }

    @Test
    @DisplayName("the default leads with the products worth comparing")
    void defaultSortsByShopCount() {
        String clause = Sort.POPULAR.orderBy("s.min_price_minor",
                                             "s.merchant_count");

        // Shops first, because a product four shops carry is one where the
        // comparison means something; price breaks the tie so equal-coverage
        // products still read cheapest-first; p.id makes paging stable.
        assertThat(clause)
                .isEqualTo("s.merchant_count DESC, s.min_price_minor ASC, p.id");
    }

    @Test
    @DisplayName("the shop-count column is substituted per query too")
    void merchantColumnIsSubstituted() {
        // The size-filtered listing counts shops in its own CTE, over the
        // offers that actually stock the requested size.
        assertThat(Sort.POPULAR.orderBy("z.from_price_minor", "z.merchant_count"))
                .isEqualTo("z.merchant_count DESC, z.from_price_minor ASC, p.id");
    }

    @Test
    @DisplayName("an explicit key still wins over the default")
    void explicitKeysStillWork() {
        assertThat(Sort.parse("cheapest")).isEqualTo(Sort.CHEAPEST);
        assertThat(Sort.parse("expensive")).isEqualTo(Sort.EXPENSIVE);
    }

    @Test
    @DisplayName("keys are matched case-insensitively and trimmed")
    void parseIsForgiving() {
        assertThat(Sort.parse("DISCOUNT")).isEqualTo(Sort.DISCOUNT);
        assertThat(Sort.parse("  title ")).isEqualTo(Sort.TITLE);
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "price; DROP TABLE product--",
        "min_price_minor ASC, (SELECT 1)",
        "1=1",
    })
    @DisplayName("an injection attempt yields the default clause, not itself")
    void injectionAttemptsNeverReachTheQuery(String hostile) {
        Sort sort = Sort.parse(hostile);

        assertThat(sort).isEqualTo(Sort.POPULAR);
        // The decisive assertion: nothing the caller supplied survives into
        // the SQL. The enum is the only source of this text.
        assertThat(sort.orderBy("s.min_price_minor", "s.merchant_count")).doesNotContain(hostile);
        assertThat(sort.orderBy("s.min_price_minor", "s.merchant_count"))
                .isEqualTo("s.merchant_count DESC, s.min_price_minor ASC, p.id");
    }

    @Test
    @DisplayName("every clause ends in a unique column, so paging is stable")
    void everyClauseIsATotalOrder() {
        // Without a tie-break, two products at the same price can swap
        // between page 1 and page 2: the shopper sees one twice and the
        // other never. p.id is the primary key, so it breaks every tie.
        for (Sort sort : Sort.values()) {
            assertThat(sort.orderBy("s.min_price_minor", "s.merchant_count"))
                    .as("%s must end in the primary key", sort)
                    .endsWith("p.id");
        }
    }

    @Test
    @DisplayName("the price column is substituted per query")
    void priceColumnIsSubstituted() {
        // The size-filtered listing prices each product in the requested
        // size, in its own CTE, so the sort has to name that column instead.
        assertThat(Sort.CHEAPEST.orderBy("z.from_price_minor", "z.merchant_count"))
                .isEqualTo("z.from_price_minor ASC, p.id");
        assertThat(Sort.EXPENSIVE.orderBy("z.from_price_minor", "z.merchant_count"))
                .startsWith("z.from_price_minor DESC");
    }

    @Test
    @DisplayName("undiscounted products sort below discounted ones, not above")
    void discountPutsNullsLast() {
        String clause = Sort.DISCOUNT.orderBy("s.min_price_minor", "s.merchant_count");

        // max_discount_pct is NULL for most of the catalogue. Postgres sorts
        // NULLs first under DESC, so without this the "biggest discount" page
        // would open with every product that has no discount at all.
        assertThat(clause).contains("max_discount_pct DESC NULLS LAST");
        // Equal discounts still read cheapest-first.
        assertThat(clause).contains("s.min_price_minor ASC");
    }

    @Test
    @DisplayName("no clause carries a format specifier into the SQL")
    void clausesAreFullyRendered() {
        // The queries contain '%' as ILIKE wildcards, so the ORDER BY is
        // substituted with String.replace. A leftover placeholder here would
        // reach Postgres verbatim.
        for (Sort sort : Sort.values()) {
            assertThat(sort.orderBy("s.min_price_minor", "s.merchant_count"))
                    .as("%s", sort)
                    .doesNotContain("{PRICE}")
                    .doesNotContain("{MERCHANTS}")
                    .doesNotContain("%s");
        }
    }
}
