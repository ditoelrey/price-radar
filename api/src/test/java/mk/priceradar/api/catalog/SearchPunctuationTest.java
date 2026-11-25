package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Search, when the shopper pastes what the shop printed.
 *
 * <p>Both halves of this were silent empty result sets on products we hold.
 *
 * <p><b>Article codes.</b> Sport Vision, Buzz and Nike print
 * {@code HV0949-313} and {@code 9A0693-AA7}. `normalize_sku` stored
 * {@code HV0949313} and {@code 9A0693AA7} — measured, all 29 498 stored
 * MPNs are free of punctuation — and the predicate compared the raw query
 * to the stored column, so the hyphen the shopper copied matched nothing.
 *
 * <p><b>Names.</b> `clean_model_name` drops the punctuation too, and not
 * consistently: the catalogue holds "Adidas 3 Stripes" and "Adidas
 * 3stripes" for the same brand's line. A shopper pasting "adidas
 * 3-stripes" matched neither spelling.
 */
class SearchPunctuationTest {

    // ----------------------------------------------------------- article codes

    @Test
    @DisplayName("a pasted article code finds the product")
    void hyphenatedSku() {
        // The two live rows this was found on: puma-caven-2-0-39229002 is
        // stored 39229002 and printed 392290-02; jordan-cuffed-9a0693aa7 is
        // stored 9A0693AA7 and printed 9A0693-AA7.
        assertThat(CatalogRepository.skuQuery("HV0949-313")).isEqualTo("HV0949313");
        assertThat(CatalogRepository.skuQuery("9A0693-AA7")).isEqualTo("9A0693AA7");
        assertThat(CatalogRepository.skuQuery("392290-02")).isEqualTo("39229002");
    }

    @Test
    @DisplayName("and so does the code typed without punctuation")
    void bareSkuStillWorks() {
        assertThat(CatalogRepository.skuQuery("HV0949313")).isEqualTo("HV0949313");
        assertThat(CatalogRepository.skuQuery("hv0949313")).isEqualTo("HV0949313");
    }

    @Test
    @DisplayName("spaces and slashes come out too, not only hyphens")
    void anyPunctuation() {
        assertThat(CatalogRepository.skuQuery(" HV0949 / 313 ")).isEqualTo("HV0949313");
        assertThat(CatalogRepository.skuQuery("HV0949.313")).isEqualTo("HV0949313");
    }

    @Test
    @DisplayName("a query of pure punctuation is not an empty code")
    void punctuationOnlyIsNotACode() {
        // Otherwise it becomes `ILIKE ''`, which matches any article whose
        // MPN is the empty string rather than nothing at all.
        assertThat(CatalogRepository.skuQuery("---")).isNull();
        assertThat(CatalogRepository.skuQuery("   ")).isNull();
        assertThat(CatalogRepository.skuQuery(null)).isNull();
    }

    // ------------------------------------------------------------------ names

    @Test
    @DisplayName("a hyphen in a name matches the space or the nothing we stored")
    void hyphenatedName() {
        // "adidas 3%stripes" matches "Adidas 3 Stripes" and "Adidas
        // 3stripes", which are both in the catalogue.
        assertThat(CatalogRepository.likeQuery("adidas 3-stripes"))
                .isEqualTo("adidas 3%stripes");
        assertThat(CatalogRepository.likeQuery("dri-fit")).isEqualTo("dri%fit");
        assertThat(CatalogRepository.likeQuery("air-max")).isEqualTo("air%max");
    }

    @Test
    @DisplayName("a space separates words rather than becoming a wildcard")
    void spacesSeparateTokens() {
        // `likeQuery` leaves the space alone; `tokenQuery` then splits on
        // it. Turning it into a wildcard instead would make one pattern of
        // the whole query and lose the per-word matching the paste case
        // needs.
        assertThat(CatalogRepository.likeQuery("nike air")).isEqualTo("nike air");
        assertThat(CatalogRepository.tokenQuery("nike air"))
                .containsExactly("nike", "air");
    }

    @Test
    @DisplayName("an ILIKE metacharacter is escaped, not obeyed")
    void wildcardsAreEscaped() {
        // Before this, a % in the query was obeyed rather than searched for.
        assertThat(CatalogRepository.likeQuery("50_60")).isEqualTo("50\\_60");
        assertThat(CatalogRepository.likeQuery("a%b_c")).isEqualTo("a\\%b\\_c");
        assertThat(CatalogRepository.likeQuery("100% cotton"))
                .isEqualTo("100\\% cotton");
    }

    @Test
    @DisplayName("the escape is not eaten by the punctuation rule")
    void escapesSurvive() {
        // The punctuation rule runs after the escaping and has to leave the
        // backslashes it just introduced alone, or `\%` becomes `%%` and the
        // metacharacter is back.
        assertThat(CatalogRepository.likeQuery("100%-cotton"))
                .isEqualTo("100\\%%cotton");
    }

    @Test
    @DisplayName("letters outside ASCII are not punctuation")
    void cyrillicSurvives() {
        // `\p{L}` and not `a-z`: most of this catalogue's category names and
        // a good share of its titles are Macedonian, and stripping them
        // would turn every such search into a wildcard.
        assertThat(CatalogRepository.likeQuery("патики")).isEqualTo("патики");
        assertThat(CatalogRepository.likeQuery("машки чорапи"))
                .isEqualTo("машки чорапи");
    }

    @Test
    @DisplayName("nothing in, nothing out")
    void blankIsNoFilter() {
        assertThat(CatalogRepository.likeQuery(null)).isNull();
        assertThat(CatalogRepository.likeQuery("   ")).isNull();
    }

    @Test
    @DisplayName("punctuation alone does not become a match-all")
    void punctuationOnlyIsNotAWildcard() {
        // Caught live: "---" reduced to "%", the predicate wrapped it in two
        // more, and the search returned the entire catalogue. A query with
        // no letters and no digits in it matches nothing.
        assertThat(CatalogRepository.likeQuery("---")).isNull();
        assertThat(CatalogRepository.likeQuery("...")).isNull();
        assertThat(CatalogRepository.likeQuery("%%%")).isNull();
        assertThat(CatalogRepository.likeQuery("%")).isNull();
    }

    // ------------------------------------------------------------- the wiring

    @Test
    @DisplayName("every query predicate reads the normalised forms")
    void allFourPredicatesUseThem() {
        // Four copies of this predicate exist -- the listing, its sized
        // variant, the brand facet and the shop facet -- and a facet that
        // searched on different terms from the listing would offer a brand
        // whose page then came back empty.
        for (String sql : new String[] {
                CatalogRepository.listBaseSql(),
                CatalogRepository.brandFacetsSql(),
                CatalogRepository.merchantFacetsSql()}) {
            assertThat(sql).contains(":qTokens");
            assertThat(sql).contains(":qSku");
        }
    }
}
