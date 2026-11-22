package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The fragrance vertical's two filters, and the facet that stops a brand
 * list leaking across verticals.
 *
 * <p>Concentration is not a size or a category — it is part of what the
 * product <em>is</em>. "Valentino Donna" exists as an Eau de Parfum and as
 * an Eau de Toilette, different liquids at different prices, so a shopper
 * asking for one must never be shown the other.
 */
class ConcentrationAndBrandFacetTest {

    @Test
    @DisplayName("a concentration is upper-cased, because the column is canonical")
    void upperCased() {
        assertThat(CatalogService.normalizeConcentration("edp")).isEqualTo("EDP");
        assertThat(CatalogService.normalizeConcentration(" edt ")).isEqualTo("EDT");
        assertThat(CatalogService.normalizeConcentration("Parfum")).isEqualTo("PARFUM");
    }

    @Test
    @DisplayName("a blank concentration is no filter at all")
    void blankIsNoFilter() {
        // Null, not "": the repository tests for null to decide whether the
        // predicate applies, and an empty string would match no row and
        // empty every fragrance page.
        assertThat(CatalogService.normalizeConcentration(null)).isNull();
        assertThat(CatalogService.normalizeConcentration("")).isNull();
        assertThat(CatalogService.normalizeConcentration("   ")).isNull();
    }

    @Test
    @DisplayName("an unknown strength is passed through, not corrected")
    void unknownSurvives() {
        // The same refusal normalizeAlpha makes. An empty page is the
        // truthful answer to a strength we do not carry; guessing a near
        // match would price a basket in a strength nobody asked for, and
        // "Absolu de Parfum" is a real Gucci label we do not yet read.
        assertThat(CatalogService.normalizeConcentration("absolu"))
                .isEqualTo("ABSOLU");
    }

    @Test
    @DisplayName("the facet counts on the same terms as the listing")
    void facetMirrorsListing() {
        // A facet that counted differently from the listing would offer a
        // shopper a brand whose page then came back empty -- worse than
        // offering nothing. These are the clauses both have to share; the
        // brand filter itself is the one the facet must NOT have, since it
        // is what the facet is enumerating.
        String facets = CatalogRepository.brandFacetsSql();
        for (String clause : new String[] {
                "s.country_code = CAST(:country AS text)",
                "s.min_price_minor IS NOT NULL",
                "cat.kind::text = ANY(CAST(:kinds AS text[]))",
                "cat.slug = CAST(:category AS text)",
                "p.gender::text = CAST(:gender AS text)",
                "p.concentration = CAST(:concentration AS text)"}) {
            assertThat(facets).contains(clause);
        }
        assertThat(facets).doesNotContain("b.slug = CAST(:brand AS text)");
    }

    @Test
    @DisplayName("a unisex article counts under men and under women")
    void unisexCountsInBothDepartments() {
        // Not a convenience we invented: every one of these shops publishes
        // its own facets that way ("maski+unisex"). The facet has to agree
        // with the listing or the counts drift.
        assertThat(CatalogRepository.brandFacetsSql())
                .contains("AND p.gender = 'unisex'");
    }
}
