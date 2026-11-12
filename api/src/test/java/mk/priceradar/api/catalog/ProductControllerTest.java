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
}
