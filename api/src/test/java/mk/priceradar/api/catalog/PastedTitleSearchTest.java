package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Search, when the shopper pastes a title off a shop's page.
 *
 * <p>The words in a paste are the merchant's; the words we store are ours.
 * `clean_model_name` drops the shop's category noun, so buzz's "Juicy
 * Couture Дуксер Classic Velour" is stored as "Juicy Couture Classic
 * Velour" -- and a search that matched the query as one contiguous
 * substring could never join the two.
 */
class PastedTitleSearchTest {

    @Test
    @DisplayName("a pasted title becomes one pattern per word")
    void tokenised() {
        assertThat(CatalogRepository.tokenQuery(
                "Juicy Couture Дуксер Classic Velour"))
                .containsExactly("Juicy", "Couture", "Дуксер", "Classic",
                                 "Velour");
    }

    @Test
    @DisplayName("punctuation inside a word stays permissive")
    void punctuationWithinAToken() {
        // The hyphen rule still applies per word: `3-stripes` has to match
        // the "3 Stripes" and "3stripes" spellings we hold.
        assertThat(CatalogRepository.tokenQuery("adidas 3-stripes"))
                .containsExactly("adidas", "3%stripes");
    }

    @Test
    @DisplayName("a single word is still a single token")
    void oneWord() {
        assertThat(CatalogRepository.tokenQuery("патики")).containsExactly("патики");
        assertThat(CatalogRepository.tokenQuery("дуксер")).containsExactly("дуксер");
    }

    @Test
    @DisplayName("collapsed whitespace does not become an empty token")
    void noEmptyTokens() {
        // An empty token is `ILIKE '%%'`, which every row satisfies -- so it
        // would silently turn an AND of words into no filter at all.
        assertThat(CatalogRepository.tokenQuery("  nike   air  "))
                .containsExactly("nike", "air");
        assertThat(CatalogRepository.tokenQuery("---")).isNull();
        assertThat(CatalogRepository.tokenQuery("%")).isNull();
        assertThat(CatalogRepository.tokenQuery("   ")).isNull();
        assertThat(CatalogRepository.tokenQuery(null)).isNull();
    }

    @Test
    @DisplayName("every word is looked for in the shop's own title and URL")
    void merchantWordsAreSearched() {
        // This is what makes the paste work: `raw_title` holds what the
        // merchant printed, which is where "Дуксер" actually lives.
        for (String sql : new String[] {
                CatalogRepository.listBaseSql(),
                CatalogRepository.brandFacetsSql(),
                CatalogRepository.merchantFacetsSql()}) {
            assertThat(sql).contains("qmo.raw_title ILIKE");
            assertThat(sql).contains("qmo.product_url ILIKE");
            assertThat(sql).contains("qmo.status = 'active'");
        }
    }

    @Test
    @DisplayName("and in the leaf's Macedonian name, instead of a stop-word list")
    void categoryNameIsSearched() {
        // Discarding generic nouns would widen every search holding one:
        // "патики nike" would return Nike perfume. Requiring the word to
        // describe the product keeps it a filter, and there is no
        // vocabulary to maintain as leaves are added.
        assertThat(CatalogRepository.listBaseSql())
                .contains("cat.name_mk");
    }

    @Test
    @DisplayName("every word must be found, not just one of them")
    void allTokensRequired() {
        // `NOT EXISTS (... WHERE <no field matched>)` -- a product survives
        // only when no token is left unmatched. An OR would make a
        // five-word paste return everything sharing any one word.
        assertThat(CatalogRepository.listBaseSql())
                .contains("AND NOT EXISTS (");
        assertThat(CatalogRepository.listBaseSql())
                .contains("unnest(CAST(:qTokens AS text[]))");
    }

    @Test
    @DisplayName("a query with no usable word matches nothing, not everything")
    void unusableQueryMatchesNothing() {
        // Caught live: gating the predicate on `:qTokens IS NULL` made "%"
        // read as "no query" and return the whole catalogue. The gate has
        // to be `:q`, which is null only when nothing was typed.
        assertThat(CatalogRepository.listBaseSql())
                .contains("AND (CAST(:q AS text) IS NULL");
        assertThat(CatalogRepository.listBaseSql())
                .contains("CAST(:qTokens AS text[]) IS NOT NULL");
        assertThat(CatalogRepository.listBaseSql())
                .doesNotContain("CAST(:qTokens AS text[]) IS NULL");
    }

    @Test
    @DisplayName("an exact article code still short-circuits the word matching")
    void skuStillWins() {
        // `9A0693-AA7` tokenises to one word that appears in no name. The
        // MPN branch is what answers it, and it sits before the token
        // predicate for that reason.
        assertThat(CatalogRepository.listBaseSql())
                .contains("p.primary_mpn ILIKE CAST(:qSku AS text)");
    }
}
