package mk.priceradar.api.catalog;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Catalogue reads. All SQL for the serving layer lives here, on purpose.
 *
 * <p>Two rules this class exists to enforce:
 *
 * <p><b>The listing never aggregates.</b> It reads
 * {@code product_price_summary}, one pre-computed row per product, which the
 * loader refreshes after every promoted run. Computing {@code MIN(price)}
 * across {@code offer_variant} at request time would mean scanning ~1.2M rows
 * per search today and more with every merchant added.
 *
 * <p><b>A size filter changes the price.</b> The summary's minimum is the
 * product's overall cheapest offer, which is frequently *not* available in the
 * size the shopper asked for -- for the Stan Smith, the 4 072 MKD headline is
 * one shop with a single size in stock, and asking for EU 44 makes the real
 * cheapest 6 799. So the size-filtered query recomputes the minimum from the
 * variants of that size, and the response says which number it gave you.
 */
@Repository
public class CatalogRepository {

    /**
     * The storefront's categories.
     *
     * Note what the SQL does with this: it excludes products whose category
     * is a *known* non-footwear kind, and keeps products with no category at
     * all. That asymmetry is deliberate. Eleven of the catalogue's products
     * have no category because their titles never named one ("Adidas
     * Handball Spezial", "Hoka Clifton UTL") — and they are shoes, reached
     * through footwear facets and footwear sitemaps. Admitting only
     * confirmed footwear would hide them; excluding confirmed apparel
     * removes the socks and t-shirts we positively identified. Unknown is
     * not the same as wrong, here as everywhere else in this codebase.
     */
    public static final String[] FOOTWEAR_KINDS = {"footwear"};

    private final JdbcClient db;

    public CatalogRepository(JdbcClient db) {
        this.db = db;
    }

    // ------------------------------------------------------------------
    // Listing
    // ------------------------------------------------------------------

    // Every nullable parameter is cast explicitly. A bind parameter used only
    // in `IS NULL` gives Postgres nothing to infer a type from, and it
    // refuses to prepare the statement at all:
    //   ERROR: could not determine data type of parameter $2
    // The cast is load-bearing, not decoration.
    /**
     * The listing orders a shopper may ask for.
     *
     * <p>An enum, and the SQL fragments live here rather than coming in from
     * the request, because this text is concatenated into the query: a sort
     * key taken from a query string and pasted into {@code ORDER BY} is an
     * injection, and no amount of validating the string afterwards is as
     * convincing as never accepting one.
     *
     * <p>Substituted with {@code String.replace}, never {@code String.format}
     * -- the queries carry {@code '%'} as ILIKE wildcards and a formatter
     * reads those as conversion specifiers and throws.
     *
     * <p>Every clause ends in {@code p.id}. Without a total order, two
     * products sharing a price can swap places between page 1 and page 2 and
     * a shopper sees one of them twice and the other never -- the sort of
     * bug that looks like a phantom duplicate and is miserable to chase.
     */
    public enum Sort {
        /** Cheapest first: the default, and what the site is for. */
        CHEAPEST("{PRICE} ASC, p.id"),
        EXPENSIVE("{PRICE} DESC, p.id"),
        /**
         * Biggest advertised saving first.
         *
         * <p>{@code NULLS LAST} keeps undiscounted products below every
         * discounted one instead of letting them lead the page, and the
         * price tie-break means equal discounts still read cheapest-first.
         */
        DISCOUNT("max_discount_pct DESC NULLS LAST, {PRICE} ASC, p.id"),
        TITLE("p.canonical_name ASC, p.id");

        private final String template;

        Sort(String template) {
            this.template = template;
        }

        /** @param priceColumn the price expression of the query being built */
        String orderBy(String priceColumn) {
            return template.replace("{PRICE}", priceColumn);
        }

        public static Sort parse(String raw) {
            if (raw == null || raw.isBlank()) {
                return CHEAPEST;
            }
            try {
                return valueOf(raw.trim().toUpperCase(java.util.Locale.ROOT));
            } catch (IllegalArgumentException unknown) {
                // An unreadable sort key is not worth a 400: the shopper
                // still wants the listing, and cheapest is the honest default.
                return CHEAPEST;
            }
        }
    }

    private static final String LIST_BASE = """
            SELECT p.slug, p.canonical_name, b.name AS brand, p.colorway,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   p.primary_mpn,
                   s.min_price_minor, s.currency_code, s.offer_count,
                   s.merchant_count, s.available_sizes_eu, s.updated_at,
                   s.max_discount_pct, c.minor_unit
              FROM product_price_summary s
              JOIN product  p ON p.id = s.product_id
              JOIN brand    b ON b.id = p.brand_id
              JOIN currency c ON c.code = s.currency_code
              LEFT JOIN category cat ON cat.id = p.category_id
              LEFT JOIN image_asset ia ON ia.id = p.image_asset_id
             WHERE s.country_code = CAST(:country AS text)
               AND s.min_price_minor IS NOT NULL
               AND (CAST(:kinds AS text[]) IS NULL
                    OR (cat.kind IS NULL AND :includeUnclassified)
                    OR cat.kind::text = ANY(CAST(:kinds AS text[])))
               AND (CAST(:q AS text) IS NULL
                    OR p.canonical_name ILIKE '%' || CAST(:q AS text) || '%'
                    OR p.primary_mpn    ILIKE CAST(:q AS text)
                    OR b.name           ILIKE '%' || CAST(:q AS text) || '%')
               AND (CAST(:brand AS text) IS NULL OR b.slug = CAST(:brand AS text))
             ORDER BY /*{ORDER}*/
             LIMIT :limit OFFSET :offset
            """;

    /**
     * Size-filtered listing.
     *
     * <p>The {@code from_price} here is the cheapest offer <em>in that
     * size</em>, computed from {@code offer_variant}. Unknown stock
     * ({@code in_stock IS NULL}) counts as a candidate: sizeer does not
     * publish availability, and excluding it would hide real offers.
     */
    private static final String LIST_BY_SIZE = """
            WITH sized AS (
                SELECT mo.product_id,
                       min(ov.price_minor) AS from_price_minor,
                       count(DISTINCT mo.id)          AS offer_count,
                       count(DISTINCT mo.merchant_id) AS merchant_count,
                       max(ov.currency_code)          AS currency_code,
                       -- Computed here rather than read off the summary: the
                       -- summary's figure covers every size, and on a page
                       -- filtered to EU 42 the only saving that means
                       -- anything is one a shopper can buy in 42.
                       max(round(100.0 * (ov.list_price_minor - ov.price_minor)
                                       / ov.list_price_minor))
                           FILTER (WHERE ov.list_price_minor IS NOT NULL
                                     AND ov.list_price_minor > ov.price_minor)
                                                      AS max_discount_pct
                  FROM offer_variant ov
                  JOIN merchant_offer mo ON mo.id = ov.offer_id
                  JOIN merchant m        ON m.id = mo.merchant_id
                 WHERE mo.status = 'active'
                   AND m.is_active
                   AND mo.product_id IS NOT NULL
                   AND ov.size_eu = CAST(:sizeEu AS numeric)
                   AND ov.in_stock IS NOT FALSE
                 GROUP BY mo.product_id
            )
            SELECT p.slug, p.canonical_name, b.name AS brand, p.colorway,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   p.primary_mpn,
                   z.from_price_minor AS min_price_minor, z.currency_code,
                   z.offer_count, z.merchant_count,
                   s.available_sizes_eu, s.updated_at,
                   z.max_discount_pct, c.minor_unit
              FROM sized z
              JOIN product  p ON p.id = z.product_id
              JOIN brand    b ON b.id = p.brand_id
              JOIN currency c ON c.code = z.currency_code
              LEFT JOIN product_price_summary s ON s.product_id = z.product_id
              LEFT JOIN category cat ON cat.id = p.category_id
              LEFT JOIN image_asset ia ON ia.id = p.image_asset_id
             WHERE (CAST(:kinds AS text[]) IS NULL
                    OR (cat.kind IS NULL AND :includeUnclassified)
                    OR cat.kind::text = ANY(CAST(:kinds AS text[])))
               AND (CAST(:q AS text) IS NULL
                    OR p.canonical_name ILIKE '%' || CAST(:q AS text) || '%'
                    OR p.primary_mpn    ILIKE CAST(:q AS text)
                    OR b.name           ILIKE '%' || CAST(:q AS text) || '%')
               AND (CAST(:brand AS text) IS NULL OR b.slug = CAST(:brand AS text))
             ORDER BY /*{ORDER}*/
             LIMIT :limit OFFSET :offset
            """;

    /**
     * @param kinds category kinds to admit, or null for every category
     * @param includeUnclassified whether products with no category join them.
     *        True for the default footwear storefront, where a null category
     *        means "the title never said" and most of those are shoes. False
     *        for an explicit kind, where someone asking for apparel plainly
     *        does not want twelve uncategorised sneakers as well.
     */
    public List<Dtos.ProductCard> list(String country, String query, String brandSlug,
                                       Double sizeEu, String[] kinds,
                                       boolean includeUnclassified,
                                       Sort sort, int limit, int offset) {
        boolean sized = sizeEu != null;
        // The price column differs between the two queries -- the size-
        // filtered one prices each product in the requested size -- so the
        // sort is rendered against whichever is in play.
        String sql = (sized ? LIST_BY_SIZE : LIST_BASE).replace(
                "/*{ORDER}*/",
                sort.orderBy(sized ? "z.from_price_minor" : "s.min_price_minor"));
        var spec = db.sql(sql)
                .param("q", normalizeQuery(query))
                .param("brand", blankToNull(brandSlug))
                .param("kinds", kinds)
                .param("includeUnclassified", includeUnclassified)
                .param("limit", limit)
                .param("offset", offset);
        if (sized) {
            spec = spec.param("sizeEu", sizeEu);
        } else {
            spec = spec.param("country", country);
        }
        return spec.query((rs, rowNum) -> mapCard(rs, sized)).list();
    }

    private Dtos.ProductCard mapCard(ResultSet rs, boolean sizeSpecific) throws SQLException {
        int minorUnit = rs.getInt("minor_unit");
        String currency = rs.getString("currency_code");
        return new Dtos.ProductCard(
                rs.getString("slug"),
                rs.getString("canonical_name"),
                rs.getString("brand"),
                rs.getString("colorway"),
                rs.getString("image_url"),
                rs.getString("primary_mpn"),
                Dtos.Money.of(rs.getLong("min_price_minor"), currency, minorUnit),
                rs.getInt("offer_count"),
                rs.getInt("merchant_count"),
                sizeSpecific,
                readSizes(rs, "available_sizes_eu"),
                nullableInt(rs, "max_discount_pct"),
                toInstant(rs, "updated_at"));
    }

    // ------------------------------------------------------------------
    // Detail
    // ------------------------------------------------------------------

    private static final String PRODUCT_BY_SLUG = """
            SELECT p.id, p.slug, p.canonical_name, b.name AS brand, p.colorway,
                   p.gender::text AS gender, p.primary_mpn,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   s.min_price_minor, s.max_price_minor, s.currency_code,
                   s.offer_count, s.merchant_count, s.available_sizes_eu,
                   s.updated_at, c.minor_unit
              FROM product p
              JOIN brand b ON b.id = p.brand_id
              LEFT JOIN product_price_summary s ON s.product_id = p.id
              LEFT JOIN currency c ON c.code = s.currency_code
              LEFT JOIN image_asset ia ON ia.id = p.image_asset_id
             WHERE p.slug = :slug
            """;

    /**
     * Every offer for a product, cheapest <em>total</em> first.
     *
     * <p>Total, not sticker price: a 2 863 MKD shoe with 300 MKD postage is
     * dearer than a 3 000 MKD shoe delivered free, and sorting on the sticker
     * would mislead on exactly the comparison the site exists to make.
     * Shipping resolves per variant, then per merchant flat rate, then free
     * above the merchant's threshold.
     */
    private static final String OFFERS_FOR_PRODUCT = """
            WITH priced AS (
                SELECT mo.id AS offer_id, m.slug AS merchant_slug,
                       m.name AS merchant_name, m.rating, m.review_count,
                       m.publishes_stock, m.delivery_days_min, m.delivery_days_max,
                       m.related_merchant_id, m.id AS merchant_id,
                       ov.id AS variant_id, ov.size_label, ov.size_eu,
                       ov.price_minor, ov.list_price_minor, ov.currency_code,
                       ov.in_stock, ov.stock_qty, ov.last_checked_at,
                       CASE
                           WHEN m.free_shipping_threshold_minor IS NOT NULL
                            AND ov.price_minor >= m.free_shipping_threshold_minor
                               THEN 0
                           ELSE coalesce(ov.shipping_cost_minor,
                                         m.flat_shipping_minor, 0)
                       END AS shipping_minor,
                       cur.minor_unit
                  FROM merchant_offer mo
                  JOIN merchant m        ON m.id = mo.merchant_id
                  JOIN offer_variant ov  ON ov.offer_id = mo.id
                  JOIN currency cur      ON cur.code = ov.currency_code
                 WHERE mo.product_id = :productId
                   AND mo.status = 'active'
                   AND m.is_active
            )
            SELECT priced.*,
                   (price_minor + shipping_minor) AS total_minor,
                   min(price_minor + shipping_minor) OVER (PARTITION BY offer_id)
                       AS offer_from_total_minor,
                   min(price_minor) OVER (PARTITION BY offer_id)
                       AS offer_from_price_minor,
                   (SELECT r.slug FROM merchant r
                     WHERE r.id = priced.related_merchant_id) AS related_slug
              FROM priced
             -- NULLS LAST: an offer with no published price is sold out,
             -- and it belongs below every offer a shopper can actually buy.
             ORDER BY offer_from_total_minor ASC NULLS LAST, merchant_name,
                      size_eu NULLS LAST, size_label
            """;

    public Optional<ProductRow> findProductBySlug(String slug) {
        return db.sql(PRODUCT_BY_SLUG).param("slug", slug)
                .query((rs, rowNum) -> new ProductRow(
                        rs.getLong("id"),
                        rs.getString("slug"),
                        rs.getString("canonical_name"),
                        rs.getString("brand"),
                        rs.getString("colorway"),
                        rs.getString("gender"),
                        rs.getString("primary_mpn"),
                        rs.getString("image_url"),
                        nullableLong(rs, "min_price_minor"),
                        nullableLong(rs, "max_price_minor"),
                        rs.getString("currency_code"),
                        rs.getInt("offer_count"),
                        rs.getInt("merchant_count"),
                        readSizes(rs, "available_sizes_eu"),
                        toInstant(rs, "updated_at"),
                        rs.getInt("minor_unit")))
                .optional();
    }

    public List<OfferVariantRow> findOffers(long productId) {
        return db.sql(OFFERS_FOR_PRODUCT).param("productId", productId)
                .query((rs, rowNum) -> new OfferVariantRow(
                        rs.getLong("offer_id"),
                        rs.getString("merchant_slug"),
                        rs.getString("merchant_name"),
                        nullableDouble(rs, "rating"),
                        rs.getInt("review_count"),
                        rs.getBoolean("publishes_stock"),
                        nullableInt(rs, "delivery_days_min"),
                        nullableInt(rs, "delivery_days_max"),
                        rs.getString("related_slug"),
                        rs.getLong("variant_id"),
                        rs.getString("size_label"),
                        nullableDouble(rs, "size_eu"),
                        // nullableLong, not getLong: a sold-out offer whose
                        // shop publishes no price has price_minor NULL, and
                        // getLong would silently turn that into 0 -- which
                        // renders as "0 ден." and reads as free.
                        nullableLong(rs, "price_minor"),
                        nullableLong(rs, "list_price_minor"),
                        rs.getLong("shipping_minor"),
                        nullableLong(rs, "total_minor"),
                        nullableLong(rs, "offer_from_price_minor"),
                        nullableLong(rs, "offer_from_total_minor"),
                        rs.getString("currency_code"),
                        nullableBoolean(rs, "in_stock"),
                        nullableInt(rs, "stock_qty"),
                        toInstant(rs, "last_checked_at"),
                        rs.getInt("minor_unit")))
                .list();
    }

    // ------------------------------------------------------------------
    // Row records
    // ------------------------------------------------------------------

    public record ProductRow(long id, String slug, String name, String brand,
                             String colorway, String gender, String mpn,
                             String imageUrl, Long minPriceMinor,
                             Long maxPriceMinor, String currency,
                             int offerCount, int merchantCount,
                             List<Double> availableSizesEu, Instant updatedAt,
                             int minorUnit) {
    }

    public record OfferVariantRow(long offerId, String merchantSlug,
                                  String merchantName, Double rating,
                                  int reviewCount, boolean publishesStock,
                                  Integer deliveryDaysMin, Integer deliveryDaysMax,
                                  String relatedMerchantSlug, long variantId,
                                  String sizeLabel, Double sizeEu,
                                  Long priceMinor, Long listPriceMinor,
                                  long shippingMinor, Long totalMinor,
                                  Long offerFromPriceMinor,
                                  Long offerFromTotalMinor, String currency,
                                  Boolean inStock, Integer stockQty,
                                  Instant checkedAt, int minorUnit) {
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private static String normalizeQuery(String query) {
        if (query == null || query.isBlank()) {
            return null;
        }
        return query.trim();
    }

    private static String blankToNull(String value) {
        return (value == null || value.isBlank()) ? null : value.trim();
    }

    private static List<Double> readSizes(ResultSet rs, String column) throws SQLException {
        var array = rs.getArray(column);
        if (array == null) {
            return List.of();
        }
        Object raw = array.getArray();
        List<Double> out = new ArrayList<>();
        if (raw instanceof Object[] values) {
            for (Object value : values) {
                if (value instanceof Number number) {
                    out.add(number.doubleValue());
                }
            }
        }
        out.sort(Double::compareTo);
        return out;
    }

    private static Instant toInstant(ResultSet rs, String column) throws SQLException {
        var ts = rs.getTimestamp(column);
        return ts == null ? null : ts.toInstant();
    }

    private static Long nullableLong(ResultSet rs, String column) throws SQLException {
        long value = rs.getLong(column);
        return rs.wasNull() ? null : value;
    }

    private static Integer nullableInt(ResultSet rs, String column) throws SQLException {
        int value = rs.getInt(column);
        return rs.wasNull() ? null : value;
    }

    private static Double nullableDouble(ResultSet rs, String column) throws SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }

    private static Boolean nullableBoolean(ResultSet rs, String column) throws SQLException {
        boolean value = rs.getBoolean(column);
        return rs.wasNull() ? null : value;
    }
}
