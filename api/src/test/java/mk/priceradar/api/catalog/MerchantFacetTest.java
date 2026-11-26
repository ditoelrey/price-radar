package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The shop rail, which claimed a comparison the page did not make.
 *
 * <p>"Продавници што ги споредуваме" was a fixed array of the six sneaker
 * shops, written while the catalogue was only trainers and left behind by
 * three verticals. On Машки парфеми it named Sport Vision, Sport Reality,
 * Buzz Sneakers, Megasport, Sport-M and Sizeer — none of which sells
 * perfume — and named neither of the two perfumeries every offer on that
 * page came from.
 *
 * <p>It survived the brand-list fix because it looked like a static fact
 * about the site rather than a filter. It is not: which shops we compare
 * depends entirely on where in the catalogue the shopper is standing.
 */
class MerchantFacetTest {

    @Test
    @DisplayName("the shop facet is scoped exactly like the listing")
    void facetMirrorsListing() {
        // Same contract as the brand facet: a rail scoped differently from
        // the listing would name a shop whose products the page does not
        // show, which is the bug being fixed rather than a smaller version
        // of it.
        String facets = CatalogRepository.merchantFacetsSql();
        for (String clause : new String[] {
                "s.country_code = CAST(:country AS text)",
                "s.min_price_minor IS NOT NULL",
                "cat.kind::text = ANY(CAST(:kinds AS text[]))",
                "cat.slug = ANY(",
                "p.gender::text = ANY(",
                "string_to_array(CAST(:concentration AS text), ',')"}) {
            assertThat(facets).contains(clause);
        }
    }

    @Test
    @DisplayName("only a live offer puts a shop on the rail")
    void onlyActiveOffers() {
        // A shop whose listing went away keeps its `merchant_offer` row with
        // a non-active status. Counting those would name a shop the page
        // cannot send anyone to.
        assertThat(CatalogRepository.merchantFacetsSql())
                .contains("mo.status = 'active'");
    }

    @Test
    @DisplayName("the count is products, not listings")
    void countsProducts() {
        // `count(DISTINCT p.id)`, so the number beside a shop means what the
        // number beside a brand means. Counting offer rows would inflate
        // every shop that lists one product under several SKUs.
        assertThat(CatalogRepository.merchantFacetsSql())
                .contains("count(DISTINCT p.id) AS product_count");
    }

    @Test
    @DisplayName("the shop rail is not narrowed by the shop")
    void noMerchantPredicate() {
        // There is no merchant filter on /products, and there must be none
        // here either: the rail enumerates shops, so narrowing by one would
        // reduce the answer to the shop already shown.
        assertThat(CatalogRepository.merchantFacetsSql())
                .doesNotContain(":merchant");
    }
}
