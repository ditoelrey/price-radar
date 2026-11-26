package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * `gender=adults`, which is not a department.
 *
 * <p>The Опрема menu stopped splitting Мажи from Жени: 55 percent of Sport
 * Vision's equipment is unisex and 66 percent of Sport Reality's, and since
 * a men's listing already includes unisex the two adult columns came out
 * roughly 85 percent the same links. The kids cut stayed, because 717
 * products -- 19 percent of the vertical -- are children's.
 *
 * <p>That leaves one general column, and its leaf links need an audience.
 * Carrying no gender at all would return the kids' stock too, which is the
 * mixing the split was made to end: a shopper looking at socks was shown
 * 19-21 baby socks beside a men's three-pack.
 */
class AdultsAudienceTest {

    @Test
    @DisplayName("every query predicate understands adults")
    void allFourPredicates() {
        // Four copies of the gender predicate exist -- the listing, its
        // sized variant, the brand facet and the shop facet. A facet that
        // read the audience differently from the listing would offer a
        // brand whose page then came back empty.
        for (String sql : new String[] {
                CatalogRepository.listBaseSql(),
                CatalogRepository.brandFacetsSql(),
                CatalogRepository.merchantFacetsSql()}) {
            assertThat(sql).contains("'adults' = ANY(");
        }
    }

    @Test
    @DisplayName("adults excludes kids and keeps unisex")
    void excludesKidsKeepsUnisex() {
        // `<> 'kids'` rather than an IN list of the other three: a value
        // added to the enum later should land in the adult shelf by
        // default, not vanish from every route.
        assertThat(CatalogRepository.listBaseSql())
                .contains("p.gender <> 'kids'");
    }

    @Test
    @DisplayName("an unclassified article is still reachable")
    void nullGenderSurvives() {
        // 45 accessory products have no gender at all. "We do not know who
        // this is for" must not mean "hidden from the only adult route".
        assertThat(CatalogRepository.listBaseSql())
                .contains("p.gender IS NULL OR p.gender <> 'kids'");
    }

    @Test
    @DisplayName("the men and women departments still include unisex")
    void departmentsUnchanged() {
        // Now an overlap test, because the filter is a list: picking
        // Мажи and Жени together must still admit unisex once.
        assertThat(CatalogRepository.listBaseSql())
                .contains("&& ARRAY['men', 'women']");
    }
}
