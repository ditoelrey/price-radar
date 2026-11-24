package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The brand slug the product detail serves, and why it is served at all.
 *
 * <p>The product page's breadcrumb used to build the brand link by hand:
 * {@code /products?brand=} plus the display name lower-cased with spaces
 * turned into hyphens. Both halves of that were wrong.
 *
 * <p>The scope was missing, so the link fell into {@code /products}' own
 * default — footwear. Clicking Calvin Klein on a perfume page asked for
 * Calvin Klein <em>trainers</em> and got nothing; clicking Adidas on a
 * hoodie asked for Adidas shoes and got sandals.
 *
 * <p>And the slug was a guess. Measured against the brand table, it is
 * wrong for 18 brands the catalogue carries, most of them perfumeries:
 * "Dolce &amp; Gabbana" became {@code dolce-&-gabbana} rather than
 * {@code dolce-gabbana}, "Lancôme" kept its circumflex, "Joop!" its
 * exclamation mark, "Victoria's Secret" its apostrophe. Every one of those
 * was a dead link whatever the scope.
 *
 * <p>A slug is a fact the database holds. The detail now serves it, so the
 * client has nothing left to guess.
 */
class BrandSlugOnDetailTest {

    @Test
    @DisplayName("the detail query reads the brand's own slug")
    void detailSelectsBrandSlug() {
        assertThat(CatalogRepository.productBySlugSql())
                .contains("b.slug AS brand_slug");
    }

    @Test
    @DisplayName("the slug travels beside the name, not instead of it")
    void nameAndSlugBothTravel() {
        // The page shows "Dolce & Gabbana" and links to `dolce-gabbana`.
        // Dropping the display name in favour of the slug would put a
        // hyphenated lower-case string in the breadcrumb.
        String sql = CatalogRepository.productBySlugSql();
        assertThat(sql).contains("b.name AS brand");
        assertThat(sql).contains("b.slug AS brand_slug");
    }

    @Test
    @DisplayName("it is the same slug the brand facet offers")
    void sameSlugAsTheFacet() {
        // The sidebar's brand links come from `brandFacets`, the breadcrumb's
        // from here. Both are `?brand=` values for the same listing, so both
        // have to be `brand.slug` and not a derivation of the name.
        assertThat(CatalogRepository.brandFacetsSql()).contains("b.slug");
        assertThat(CatalogRepository.productBySlugSql()).contains("b.slug");
    }
}
