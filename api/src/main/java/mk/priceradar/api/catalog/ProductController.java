package mk.priceradar.api.catalog;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Read endpoints for the storefront.
 *
 * <p>{@code sizeEu} is the parameter that matters most. Passing it switches
 * both the listing and the detail page from "cheapest offer for this product"
 * to "cheapest offer you can actually buy in your size" -- which for the
 * Adidas Stan Smith is the difference between a 4 072 MKD headline and the
 * 6 799 MKD a shopper asking for EU 44 really pays.
 */
@RestController
@RequestMapping("/api/v1")
@Validated
public class ProductController {

    private static final int MAX_PAGE_SIZE = 60;

    private final CatalogService catalog;

    public ProductController(CatalogService catalog) {
        this.catalog = catalog;
    }

    /**
     * @param kind which category kinds to list. Defaults to footwear, since
     *        this is a sneaker comparison site and the pipeline crawls shops
     *        that also sell socks and ski leggings. Pass {@code kind=all} to
     *        list everything; any other value is taken as a single kind
     *        ({@code apparel}, {@code accessory}, {@code equipment}).
     *        Products with no category are always included — their titles
     *        simply never said, and most of them are shoes.
     */
    @GetMapping("/products")
    public Dtos.ProductPage search(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String brand,
            @RequestParam(required = false) Double sizeEu,
            @RequestParam(required = false) String kind,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "24") @Min(1) @Max(MAX_PAGE_SIZE) int pageSize) {
        boolean isDefaultScope = kind == null || kind.isBlank();
        return catalog.search(q, brand, sizeEu, kindsFor(kind), isDefaultScope,
                page, Math.min(pageSize, MAX_PAGE_SIZE));
    }

    static String[] kindsFor(String kind) {
        if (kind == null || kind.isBlank()) {
            return CatalogRepository.FOOTWEAR_KINDS;
        }
        if ("all".equalsIgnoreCase(kind.trim())) {
            return null;
        }
        return new String[] {kind.trim().toLowerCase()};
    }

    @GetMapping("/products/{slug}")
    public ResponseEntity<Dtos.ProductDetail> detail(
            @PathVariable String slug,
            @RequestParam(required = false) Double sizeEu) {
        return catalog.detail(slug, sizeEu)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
