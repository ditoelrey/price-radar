package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The storefront's category scope.
 *
 * The pipeline crawls shops that also sell socks, ski leggings and helmets —
 * megasport's discovery walks a sitemap covering its entire range — so a
 * sneaker comparison site has to say which kinds it serves.
 */
class ProductControllerTest {

    @Test
    @DisplayName("the default storefront is footwear")
    void defaultsToFootwear() {
        assertThat(ProductController.kindsFor(null))
                .isEqualTo(CatalogRepository.FOOTWEAR_KINDS);
        assertThat(ProductController.kindsFor("  "))
                .isEqualTo(CatalogRepository.FOOTWEAR_KINDS);
        assertThat(CatalogRepository.FOOTWEAR_KINDS).containsExactly("footwear");
    }

    @Test
    @DisplayName("kind=all removes the filter entirely")
    void allDisablesIt() {
        // null is the repository's "no restriction" signal, not an empty
        // array — an empty array would match nothing and blank the site.
        assertThat(ProductController.kindsFor("all")).isNull();
        assertThat(ProductController.kindsFor("ALL")).isNull();
    }

    @Test
    @DisplayName("any other value selects that one kind")
    void selectsOneKind() {
        assertThat(ProductController.kindsFor("apparel")).containsExactly("apparel");
        assertThat(ProductController.kindsFor("  Accessory "))
                .containsExactly("accessory");
    }

    @Test
    @DisplayName("a blank category or gender is no filter at all")
    void blankIsNoFilter() {
        // Null, not "", because the SQL tests the parameter for NULL. An
        // empty string would be compared against cat.slug and match nothing,
        // which turns "no filter" into "empty page".
        assertThat(ProductController.normalize(null)).isNull();
        assertThat(ProductController.normalize("")).isNull();
        assertThat(ProductController.normalize("   ")).isNull();
    }

    @Test
    @DisplayName("filter values are lower-cased and trimmed")
    void normalizesCase() {
        assertThat(ProductController.normalize(" Cleats ")).isEqualTo("cleats");
        assertThat(ProductController.normalize("SHOES_BOOTS"))
                .isEqualTo("shoes_boots");
        assertThat(ProductController.normalize("Men")).isEqualTo("men");
    }

    @Test
    @DisplayName("an unknown filter value is passed through, not rejected")
    void unknownValuesSurvive() {
        // Deliberate: an unknown slug matches no row and the shopper gets an
        // empty listing, which is the truthful answer. Validating here would
        // turn a mistyped or stale link into an error page, and would also
        // mean this class had to keep its own copy of the taxonomy — a second
        // list to forget to update the next time the tree changes.
        assertThat(ProductController.normalize("running")).isEqualTo("running");
        assertThat(ProductController.normalize("nonsense"))
                .isEqualTo("nonsense");
    }
}
