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
                "cat.slug = ANY(",
                "p.gender::text = ANY(",
                // A list, not a single value: one menu entry ("Парфеми")
                // names both PARFUM and EXTRAIT.
                "string_to_array(CAST(:concentration AS text), ',')"}) {
            assertThat(facets).contains(clause);
        }
        assertThat(facets).doesNotContain("b.slug = ANY(");
    }

    @Test
    @DisplayName("a volume is read as a volume, not offered to the ladder")
    void volumeAxis() {
        // Letters and millilitres share the `size` parameter, because to a
        // shopper they are one question. Read in the wrong order, "30ml"
        // is upper-cased to "30ML" and asked of the letter ladder, which
        // has no such rung -- and the page comes back empty.
        assertThat(CatalogService.normalizeVolumeMl("30ml")).isEqualTo(30);
        assertThat(CatalogService.normalizeVolumeMl("100ML")).isEqualTo(100);
        assertThat(CatalogService.normalizeVolumeMl(" 50 ml ")).isEqualTo(50);
    }

    @Test
    @DisplayName("a letter is not a volume")
    void lettersFallThrough() {
        for (String size : new String[] {"XL", "M", "9-10 год.", "", "ml", null}) {
            assertThat(CatalogService.normalizeVolumeMl(size)).isNull();
        }
    }

    @Test
    @DisplayName("an implausible volume is refused, not clamped")
    void implausibleVolume() {
        // Mirrors mkagg.sizing: four digits of millilitres is more likely a
        // weight or a code than a bottle, and 0ml is nothing at all.
        assertThat(CatalogService.normalizeVolumeMl("2500ml")).isNull();
        assertThat(CatalogService.normalizeVolumeMl("0ml")).isNull();
    }

    @Test
    @DisplayName("each axis selects its own column, and only its own")
    void onePredicatePerAxis() {
        var eu = CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.EU);
        var alpha = CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.ALPHA);
        var ml = CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.VOLUME);

        assertThat(ml).isEqualTo("ov.size_ml = ANY(string_to_array("
                + "CAST(:sizeMl AS text), ',')::integer[])");
        // The three are substituted into one CTE, so a predicate naming a
        // second column would match nothing at all.
        assertThat(eu).doesNotContain("size_alpha").doesNotContain("size_ml");
        assertThat(alpha).doesNotContain("size_eu").doesNotContain("size_ml");
        assertThat(ml).doesNotContain("size_eu").doesNotContain("size_alpha");
    }

    @Test
    @DisplayName("a unisex article counts under men and under women")
    void unisexCountsInBothDepartments() {
        // Not a convenience we invented: every one of these shops publishes
        // its own facets that way ("maski+unisex"). The facet has to agree
        // with the listing or the counts drift.
        assertThat(CatalogRepository.brandFacetsSql())
                .contains("p.gender = 'unisex'");
    }
}
