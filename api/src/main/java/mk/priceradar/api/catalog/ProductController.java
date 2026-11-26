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
import java.util.List;

/**
 * Read endpoints for the storefront.
 *
 * <p>{@code size} is its counterpart for garments -- a letter from the
 * ladder, XXS to 5XL -- because a hoodie has no EU number and the rail would
 * otherwise be empty on every apparel listing. The two are alternatives, not
 * a pair: nothing in the catalogue carries both, and {@code sizeEu} wins if
 * both arrive.
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
     * @param category one canonical leaf: {@code sneakers}, {@code cleats},
     *        {@code shoes_boots} or {@code slides_sandals}. Matched exactly,
     *        so this never returns the generic {@code footwear} parent.
     * @param gender {@code men}, {@code women}, {@code kids} or
     *        {@code unisex}. Men and women include unisex articles, as the
     *        shops' own departments do; products whose gender is unknown are
     *        excluded, because unknown is not a department.
     */
    @GetMapping("/products")
    public Dtos.ProductPage search(
            @RequestParam(required = false) String q,
            // Every filter group takes a list. Spring binds a repeated
            // parameter (?brand=a&brand=b) and a comma-separated one
            // (?brand=a,b) to the same List, so the storefront may send
            // either and an old single-valued link keeps working as a
            // one-element list.
            @RequestParam(required = false) List<String> brand,
            @RequestParam(required = false) List<String> sizeEu,
            @RequestParam(required = false) List<String> size,
            @RequestParam(required = false) String kind,
            @RequestParam(required = false) List<String> category,
            @RequestParam(required = false) List<String> gender,
            @RequestParam(required = false) String concentration,
            @RequestParam(required = false) List<String> shop,
            // A price band id, or several: `0-1000`, `10000-`. Only a band
            // this API published is honoured; see CatalogService.PRICE_BANDS.
            @RequestParam(required = false) List<String> price,
            @RequestParam(required = false) String sort,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "24") @Min(1) @Max(MAX_PAGE_SIZE) int pageSize) {
        boolean isDefaultScope = kind == null || kind.isBlank();
        return catalog.search(q, csv(brand), csv(sizeEu), csv(size),
                kindsFor(kind), isDefaultScope,
                csvLower(category), csvLower(gender),
                concentration, csvLower(shop), csv(price),
                CatalogRepository.Sort.parse(sort),
                page, Math.min(pageSize, MAX_PAGE_SIZE));
    }

    /**
     * Every filter control for one listing scope, in one call.
     *
     * <p>Takes exactly what {@code /products} takes, minus the sort and the
     * page, and answers with each group's options and counts. Each group is
     * counted with every other group's filters applied and its own left out,
     * so a count means "this many if you tick it too" rather than "this many,
     * given what you already picked".
     *
     * <p>One call rather than five: the sidebar renders six sections and a
     * round trip per section would be six round trips on every listing, and
     * five of them would have to be sent the same filter state anyway.
     */
    @GetMapping("/facets")
    public Dtos.Facets facets(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) List<String> brand,
            @RequestParam(required = false) List<String> sizeEu,
            @RequestParam(required = false) List<String> size,
            @RequestParam(required = false) String kind,
            @RequestParam(required = false) List<String> category,
            @RequestParam(required = false) List<String> gender,
            @RequestParam(required = false) String concentration,
            @RequestParam(required = false) List<String> shop,
            @RequestParam(required = false) List<String> price,
            @RequestParam(defaultValue = "60") @Min(1) @Max(400) int limit) {
        boolean isDefaultScope = kind == null || kind.isBlank();
        return catalog.facets(q, csv(brand), csv(sizeEu), csv(size),
                kindsFor(kind), isDefaultScope,
                csvLower(category), csvLower(gender),
                concentration, csvLower(shop), csv(price), limit);
    }

    /**
     * Brands with products under the given scope, commonest first.
     *
     * <p>Same parameters as {@code /products} minus the brand itself, so the
     * sidebar can ask "which brands would this page offer" and get an answer
     * that matches the page.
     */
    @GetMapping("/brands")
    public List<Dtos.BrandFacet> brands(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String kind,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String gender,
            @RequestParam(required = false) String concentration,
            @RequestParam(defaultValue = "40") @Min(1) @Max(200) int limit) {
        boolean isDefaultScope = kind == null || kind.isBlank();
        return catalog.brands(q, kindsFor(kind), isDefaultScope,
                normalize(category), normalize(gender), concentration, limit);
    }

    /**
     * Shops with products under the given scope, biggest first.
     *
     * <p>Same parameters as {@code /brands}, and for the same reason: the
     * sidebar asks which shops this page actually compares, and the answer
     * has to be the page's own rather than a list written when the
     * catalogue was only trainers.
     */
    @GetMapping("/merchants")
    public List<Dtos.MerchantFacet> merchants(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String kind,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String gender,
            @RequestParam(required = false) String concentration,
            @RequestParam(defaultValue = "20") @Min(1) @Max(200) int limit) {
        boolean isDefaultScope = kind == null || kind.isBlank();
        return catalog.merchants(q, kindsFor(kind), isDefaultScope,
                normalize(category), normalize(gender), concentration, limit);
    }

    /**
     * Lower-cases and trims a filter value, or returns null for a blank one.
     *
     * <p>No validation beyond that, deliberately: an unknown category or
     * gender matches no row and the shopper gets an empty page, which is the
     * truthful answer. A 400 would be worse -- it turns a mistyped link into
     * an error page instead of a listing with nothing in it.
     */
    /**
     * A bound list back to the comma-separated string the repository reads.
     *
     * <p>Blank entries are dropped: "?brand=" and "?brand=,," both mean no
     * brand filter, and an empty element would become `slug = ''`, which
     * matches nothing and empties the page.
     */
    static String csv(List<String> values) {
        if (values == null || values.isEmpty()) {
            return null;
        }
        String joined = values.stream()
                .filter(v -> v != null && !v.isBlank())
                .map(String::trim)
                .collect(java.util.stream.Collectors.joining(","));
        return joined.isBlank() ? null : joined;
    }

    /** As {@link #csv}, lower-cased: slugs and genders are canonical. */
    static String csvLower(List<String> values) {
        String joined = csv(values);
        return joined == null
                ? null : joined.toLowerCase(java.util.Locale.ROOT);
    }

    static String normalize(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim().toLowerCase(java.util.Locale.ROOT);
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
            @RequestParam(required = false) Double sizeEu,
            @RequestParam(required = false) String size) {
        return catalog.detail(slug, sizeEu, size)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
