package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Letter sizes, the garment half of the size rail.
 *
 * <p>A shoe is filtered by an EU number and a hoodie by a letter. Nothing in
 * the catalogue carries both — {@code size_eu} is NULL on all 74 716 Sport
 * Vision apparel variants and {@code size_alpha} is NULL on every shoe — so
 * these are two axes, not two spellings of one. The failure mode they share
 * is silence: asking for the wrong one returns an empty page, which reads to
 * a shopper as "this shop has nothing" rather than as a bug.
 */
class AlphaSizeFilterTest {

    @Test
    @DisplayName("each flag selects its own column")
    void predicatePerAxis() {
        assertThat(CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.EU))
                .isEqualTo("ov.size_eu = CAST(:sizeEu AS numeric)");
        // A range test, not an equality: "M/L" is stored as size_alpha M
        // with size_alpha_max L and has to answer either letter. coalesce
        // collapses a single-letter row to M..M, so one expression serves
        // both cases.
        assertThat(CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.ALPHA)).isEqualTo(
                "alpha_size_rank(CAST(:sizeAlpha AS text)) BETWEEN "
                + "alpha_size_rank(ov.size_alpha) AND "
                + "alpha_size_rank(coalesce(ov.size_alpha_max, "
                + "ov.size_alpha))");
    }

    @Test
    @DisplayName("the predicate names exactly one size column")
    void neverBoth() {
        // The two branches are substituted into the same CTE, so a predicate
        // mentioning both columns would match nothing at all.
        assertThat(CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.EU)).doesNotContain("size_alpha");
        assertThat(CatalogRepository.sizeMatch(CatalogRepository.SizeAxis.ALPHA)).doesNotContain("size_eu");
    }

    @Test
    @DisplayName("a letter is upper-cased, because the column is canonical")
    void upperCased() {
        assertThat(CatalogService.normalizeAlpha("xl")).isEqualTo("XL");
        assertThat(CatalogService.normalizeAlpha(" m ")).isEqualTo("M");
        assertThat(CatalogService.normalizeAlpha("3xl")).isEqualTo("3XL");
    }

    @Test
    @DisplayName("a blank letter is no filter at all")
    void blankIsNoFilter() {
        // Null, not "": the repository tests this for null to decide whether
        // to run the sized query at all, and an empty string would send every
        // listing through the CTE to match nothing.
        assertThat(CatalogService.normalizeAlpha(null)).isNull();
        assertThat(CatalogService.normalizeAlpha("")).isNull();
        assertThat(CatalogService.normalizeAlpha("   ")).isNull();
    }

    @Test
    @DisplayName("an unknown letter is passed through, not corrected")
    void unknownSurvives() {
        // "YMD" is one of Sport Vision's template sizes. It matches no row,
        // and an empty page is the truthful answer to a size we do not
        // carry — guessing a near match would price a shopper's basket in a
        // size they did not ask for.
        assertThat(CatalogService.normalizeAlpha("ymd")).isEqualTo("YMD");
    }

    @Test
    @DisplayName("a detail chip matches the string the page shows")
    void detailMatchesWhatIsRendered() {
        // The page renders `sizeAlpha ?? sizeLabel`, so both have to match or
        // a visible chip would filter to nothing. The letter side carries
        // adidas's own spellings, which the parser folds in: a variant
        // labelled "LG" is rendered "L" and must answer to "L".
        var ladder = row(1L, "LG", "L");
        assertThat(CatalogService.sameLabel(ladder, "L")).isTrue();
        assertThat(CatalogService.sameLabel(ladder, "l")).isTrue();
        assertThat(CatalogService.sameLabel(ladder, "LG")).isTrue();
        assertThat(CatalogService.sameLabel(ladder, "M")).isFalse();
    }

    @Test
    @DisplayName("a span chip matches the shop's own label")
    void spanMatchesPrintedLabel() {
        // The page shows "M/L" for a span rather than either end, because
        // that is what the shop prints and what the shopper reads there.
        // sameLabel has to accept it, or a visible chip filters to nothing.
        var span = new CatalogRepository.OfferVariantRow(
                3L, "buzz", "Buzz Sneakers", 4.0, 10, true, 2, 4, null,
                3L, "M/L", null, "M", "L", "alpha",
                100L, null, 0L, 100L, 100L, 100L, "MKD", true, 1,
                java.time.Instant.now(), 0);
        assertThat(CatalogService.sameLabel(span, "M/L")).isTrue();
        assertThat(CatalogService.sameLabel(span, "M")).isTrue();
        assertThat(CatalogService.sameLabel(span, "XL")).isFalse();
    }

    @Test
    @DisplayName("a kids size matches on its label, having no letter")
    void kidsMatchOnLabel() {
        // "9-10 год." is on no ladder and has no canonical form, so the
        // shop's own label is the only thing to compare.
        var kid = row(2L, "9-10 год.", null);
        assertThat(CatalogService.sameLabel(kid, "9-10 год.")).isTrue();
        assertThat(CatalogService.sameLabel(kid, "11-12 год.")).isFalse();
    }

    private static CatalogRepository.OfferVariantRow row(
            long id, String label, String alpha) {
        return new CatalogRepository.OfferVariantRow(
                id, "sportvision", "Sport Vision", 4.0, 10, true, 2, 4, null,
                id, label, null, alpha, null, "alpha",
                100L, null, 0L, 100L, 100L, 100L, "MKD", true, 1,
                java.time.Instant.now(), 0);
    }
}
