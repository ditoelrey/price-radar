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
        /**
         * The default, and deliberately not offered in the sort control.
         *
         * <p>Products carried by several shops first. This is a comparison
         * site, and a product with four shops behind it is one where the
         * comparison is worth something -- 1,935 of the catalogue's products
         * have two or more offers and 42 have four, while the long tail is
         * single-shop listings where we can only repeat one price back.
         * Opening on cheapest-first instead leads with 219 MKD oddities that
         * exactly one shop sells.
         *
         * <p>It is absent from {@code SORTS} on the storefront on purpose:
         * "by number of shops" is a mechanism, not something a shopper
         * thinks in. They see the four orderings they might actually want,
         * and this is what they get when they have not asked for one.
         */
        POPULAR("{MERCHANTS} DESC, {PRICE} ASC, p.id"),
        /** Cheapest first: what the site is for, once someone asks. */
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

        /**
         * @param priceColumn the price expression of the query being built
         * @param merchantsColumn the shop-count expression of that query
         */
        String orderBy(String priceColumn, String merchantsColumn) {
            return template
                    .replace("{PRICE}", priceColumn)
                    .replace("{MERCHANTS}", merchantsColumn);
        }

        public static Sort parse(String raw) {
            if (raw == null || raw.isBlank()) {
                return POPULAR;
            }
            try {
                return valueOf(raw.trim().toUpperCase(java.util.Locale.ROOT));
            } catch (IllegalArgumentException unknown) {
                // An unreadable sort key is not worth a 400: the shopper
                // still wants the listing, and the default is the honest
                // answer to "I did not ask for an order".
                return POPULAR;
            }
        }
    }

    private static final String LIST_BASE = """
            SELECT p.slug, p.canonical_name, b.name AS brand, p.colorway,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   p.primary_mpn, cat.slug AS category, cat.name_mk AS category_mk,
                   p.gender::text AS gender,
                   s.min_price_minor, s.max_price_minor,
                   s.currency_code, s.offer_count,
                   s.merchant_count, s.available_sizes_eu,
                   s.available_sizes_alpha, s.available_volumes_ml,
                   p.concentration, s.updated_at,
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
               -- An exact leaf match, so asking for Копачки returns cleats
               -- and nothing else -- not the generic `footwear` parent, which
               -- means "a shoe, kind unspecified".
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = CAST(:category AS text))
               -- The men's and women's departments include unisex articles,
               -- which is not a convenience we invented: it is how every one
               -- of these shops publishes its own facets ("maski+unisex").
               -- Kids' does not, and an explicit `unisex` asks for only
               -- those. A NULL gender is excluded from every gender filter --
               -- unknown is not a department -- unlike the `kind` scope,
               -- where unknown products are admitted because the default
               -- storefront would otherwise hide most of the catalogue.
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = CAST(:gender AS text)
                    OR (CAST(:gender AS text) IN ('men', 'women')
                        AND p.gender = 'unisex'))
               -- Fragrances only, and an exact match. "Valentino Donna" in
               -- Eau de Parfum and in Eau de Toilette are different liquids
               -- at different prices, so a shopper asking for EDP must not
               -- be shown the EDT beside it.
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
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
     *
     * <p>One query for two size systems. The EU number and the letter are
     * different axes -- a shoe has one, a hoodie the other, and nothing has
     * both -- but everything after the match is identical, so only the
     * predicate is substituted. Duplicating the sixty lines around it is how
     * the kind, category and gender filters would come to exist in one copy
     * and not the other.
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
                   AND /*{SIZE_MATCH}*/
                   AND ov.in_stock IS NOT FALSE
                 GROUP BY mo.product_id
            )
            SELECT p.slug, p.canonical_name, b.name AS brand, p.colorway,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   p.primary_mpn, cat.slug AS category, cat.name_mk AS category_mk,
                   p.gender::text AS gender,
                   z.from_price_minor AS min_price_minor,
                   -- NULL by design on a size-filtered page. The summary's
                   -- maximum covers every size, and quoting it beside a
                   -- price computed for one size would advertise a range
                   -- the shopper cannot buy within.
                   NULL::bigint AS max_price_minor,
                   z.currency_code,
                   z.offer_count, z.merchant_count,
                   s.available_sizes_eu, s.available_sizes_alpha,
                   s.available_volumes_ml, p.concentration, s.updated_at,
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
               -- An exact leaf match, so asking for Копачки returns cleats
               -- and nothing else -- not the generic `footwear` parent, which
               -- means "a shoe, kind unspecified".
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = CAST(:category AS text))
               -- The men's and women's departments include unisex articles,
               -- which is not a convenience we invented: it is how every one
               -- of these shops publishes its own facets ("maski+unisex").
               -- Kids' does not, and an explicit `unisex` asks for only
               -- those. A NULL gender is excluded from every gender filter --
               -- unknown is not a department -- unlike the `kind` scope,
               -- where unknown products are admitted because the default
               -- storefront would otherwise hide most of the catalogue.
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = CAST(:gender AS text)
                    OR (CAST(:gender AS text) IN ('men', 'women')
                        AND p.gender = 'unisex'))
               -- Fragrances only, and an exact match. "Valentino Donna" in
               -- Eau de Parfum and in Eau de Toilette are different liquids
               -- at different prices, so a shopper asking for EDP must not
               -- be shown the EDT beside it.
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
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
                                       Double sizeEu, String sizeAlpha,
                                       String[] kinds,
                                       boolean includeUnclassified,
                                       String categorySlug, String gender,
                                       String concentration,
                                       Sort sort, int limit, int offset) {
        String alpha = blankToNull(sizeAlpha);
        // An EU number wins when both arrive. They cannot both be satisfied
        // -- no variant carries both -- so honouring both would return an
        // empty page for a shopper who merely changed vertical with a size
        // still in the URL.
        boolean byEu = sizeEu != null;
        boolean sized = byEu || alpha != null;
        // The price column differs between the two queries -- the size-
        // filtered one prices each product in the requested size -- so the
        // sort is rendered against whichever is in play.
        // Both expressions differ between the two queries: the size-filtered
        // one recomputes price and shop count in its own CTE.
        String sql = (sized ? LIST_BY_SIZE : LIST_BASE).replace(
                "/*{ORDER}*/",
                sort.orderBy(sized ? "z.from_price_minor" : "s.min_price_minor",
                             sized ? "z.merchant_count" : "s.merchant_count"));
        if (sized) {
            sql = sql.replace("/*{SIZE_MATCH}*/", sizeMatch(byEu));
        }
        var spec = db.sql(sql)
                .param("q", normalizeQuery(query))
                .param("brand", blankToNull(brandSlug))
                .param("kinds", kinds)
                .param("includeUnclassified", includeUnclassified)
                .param("category", blankToNull(categorySlug))
                .param("gender", blankToNull(gender))
                .param("concentration", blankToNull(concentration))
                .param("limit", limit)
                .param("offset", offset);
        if (byEu) {
            spec = spec.param("sizeEu", sizeEu);
        } else if (sized) {
            spec = spec.param("sizeAlpha", alpha);
        } else {
            spec = spec.param("country", country);
        }
        return spec.query((rs, rowNum) -> mapCard(rs, sized)).list();
    }

    /**
     * The predicate that narrows the sized CTE to one size.
     *
     * <p>Package-private so a test can assert which axis each flag selects
     * without a database: getting this backwards would quietly return every
     * garment for a shoe size and vice versa, and both read as "no results"
     * rather than as an error.
     */
    static String sizeMatch(boolean byEu) {
        // The letter side is a range test, not an equality, because a label
        // can name two sizes: "M/L" is stored as size_alpha M with
        // size_alpha_max L, and has to answer a shopper filtering either.
        // coalesce collapses the ordinary single-letter row to M..M, so the
        // same expression serves both and there is no second code path to
        // keep in step. A NULL size_alpha ranks NULL and matches nothing,
        // which is what a variant with no letter size should do.
        return byEu ? "ov.size_eu = CAST(:sizeEu AS numeric)"
                    : "alpha_size_rank(CAST(:sizeAlpha AS text)) BETWEEN "
                      + "alpha_size_rank(ov.size_alpha) AND "
                      + "alpha_size_rank(coalesce(ov.size_alpha_max, "
                      + "ov.size_alpha))";
    }

    /**
     * Brands that actually have something to show under the current scope.
     *
     * <p>The storefront rendered a hard-coded list of twelve sneaker brands,
     * which was right while the catalogue was shoes. It is now wrong in both
     * directions: Hoka and Jordan are offered on the apparel listing where
     * they have nothing, and the fragrance listing offers none of the brands
     * it carries -- Ajmal, Lattafa, Dolce &amp; Gabbana.
     *
     * <p>The WHERE here mirrors {@code LIST_BASE} clause for clause, minus
     * the brand filter itself. A facet counting on different terms from the
     * listing would offer a brand whose page then came back empty, which is
     * worse than offering nothing at all.
     */
    private static final String BRAND_FACETS = """
            SELECT b.slug, b.name, count(DISTINCT p.id) AS product_count
              FROM product_price_summary s
              JOIN product p ON p.id = s.product_id
              JOIN brand   b ON b.id = p.brand_id
              LEFT JOIN category cat ON cat.id = p.category_id
             WHERE s.country_code = CAST(:country AS text)
               AND s.min_price_minor IS NOT NULL
               AND (CAST(:kinds AS text[]) IS NULL
                    OR (cat.kind IS NULL AND :includeUnclassified)
                    OR cat.kind::text = ANY(CAST(:kinds AS text[])))
               AND (CAST(:q AS text) IS NULL
                    OR p.canonical_name ILIKE '%' || CAST(:q AS text) || '%'
                    OR p.primary_mpn    ILIKE CAST(:q AS text)
                    OR b.name           ILIKE '%' || CAST(:q AS text) || '%')
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = CAST(:category AS text))
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = CAST(:gender AS text)
                    OR (CAST(:gender AS text) IN ('men', 'women')
                        AND p.gender = 'unisex'))
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
             GROUP BY b.slug, b.name
             ORDER BY product_count DESC, b.name
             LIMIT :limit
            """;

    /** The facet SQL, exposed so a test can hold it beside the listing's. */
    static String brandFacetsSql() {
        return BRAND_FACETS;
    }

    public List<Dtos.BrandFacet> brandFacets(String country, String query,
                                             String[] kinds,
                                             boolean includeUnclassified,
                                             String categorySlug, String gender,
                                             String concentration, int limit) {
        return db.sql(BRAND_FACETS)
                .param("country", country)
                .param("q", normalizeQuery(query))
                .param("kinds", kinds)
                .param("includeUnclassified", includeUnclassified)
                .param("category", blankToNull(categorySlug))
                .param("gender", blankToNull(gender))
                .param("concentration", blankToNull(concentration))
                .param("limit", limit)
                .query((rs, rowNum) -> new Dtos.BrandFacet(
                        rs.getString("slug"),
                        rs.getString("name"),
                        rs.getInt("product_count")))
                .list();
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
                rs.getString("category"),
                rs.getString("category_mk"),
                rs.getString("gender"),
                Dtos.Money.of(rs.getLong("min_price_minor"), currency, minorUnit),
                toPrice(rs, currency, minorUnit),
                rs.getInt("offer_count"),
                rs.getInt("merchant_count"),
                sizeSpecific,
                readSizes(rs, "available_sizes_eu"),
                readLabels(rs, "available_sizes_alpha"),
                readVolumes(rs, "available_volumes_ml"),
                rs.getString("concentration"),
                nullableInt(rs, "max_discount_pct"),
                toInstant(rs, "updated_at"));
    }

    /**
     * The dearest bottle, when a range means anything.
     *
     * <p>Null whenever it equals the minimum: a product sold in one size has
     * no range, and rendering "4.240 - 4.240" reads as a bug.
     */
    private static Dtos.Money toPrice(ResultSet rs, String currency,
                                      int minorUnit) throws SQLException {
        long max = rs.getLong("max_price_minor");
        if (rs.wasNull() || max <= rs.getLong("min_price_minor")) {
            return null;
        }
        return Dtos.Money.of(max, currency, minorUnit);
    }

    private static List<Integer> readVolumes(ResultSet rs, String column)
            throws SQLException {
        var array = rs.getArray(column);
        if (array == null) {
            return List.of();
        }
        var out = new java.util.ArrayList<Integer>();
        for (Object value : (Object[]) array.getArray()) {
            if (value != null) {
                out.add(((Number) value).intValue());
            }
        }
        return out;
    }

    // ------------------------------------------------------------------
    // Detail
    // ------------------------------------------------------------------

    private static final String PRODUCT_BY_SLUG = """
            SELECT p.id, p.slug, p.canonical_name, b.name AS brand, p.colorway,
                   p.gender::text AS gender, p.primary_mpn,
                   cat.kind::text AS category_kind, cat.slug AS category,
                   cat.name_mk AS category_mk,
       -- Our own copy when we hold one, the shop's URL only while the
       -- image pipeline catches up. Resolved in SQL so every caller gets
       -- the same answer and no one can forget the fallback.
       coalesce('/media/' || ia.path, p.image_url) AS image_url,
                   s.min_price_minor, s.max_price_minor, s.currency_code,
                   s.offer_count, s.merchant_count, s.available_sizes_eu,
                   s.available_sizes_alpha,
                   -- When a shop was last *asked*, not when we last
                   -- recomputed this row. `product_price_summary.updated_at`
                   -- is stamped now() by every promotion and by any
                   -- maintenance pass that touches the summary, so the page
                   -- claimed a product had been refreshed today while each
                   -- of its offers said "checked 4 days ago" directly
                   -- underneath. Taking the newest offer check makes the two
                   -- read from the same source and agree by construction.
                   (SELECT max(ov.last_checked_at)
                      FROM offer_variant ov
                      JOIN merchant_offer mo ON mo.id = ov.offer_id
                      JOIN merchant m2 ON m2.id = mo.merchant_id
                     WHERE mo.product_id = p.id
                       AND mo.status = 'active'
                       AND m2.is_active) AS updated_at,
                   c.minor_unit
              FROM product p
              JOIN brand b ON b.id = p.brand_id
              LEFT JOIN category cat ON cat.id = p.category_id
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
                       -- The canonical letter, not `size_label`: Sport
                       -- Vision renders its whole size dictionary into every
                       -- garment page, so the raw labels include 2XLS, M-T
                       -- and YXS. `size_alpha` is what V18's parser could
                       -- actually place on the ladder.
                       ov.size_alpha, ov.size_alpha_max, ov.size_system,
                       -- Carried only so the ORDER BY below can reach them:
                       -- an age or height size has no place on the alpha
                       -- ladder and sorts on its own normalised number.
                       ov.size_age_min_months, ov.size_height_cm,
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
                      -- Every size system in one ordering, so the page can
                      -- render variants in arrival order whatever it is
                      -- looking at. Ordering on `size_label` alone put a
                      -- kids' rail in alphabetical order: "1-2 год.",
                      -- "11-12 год.", then "9-10 год.".
                      size_eu NULLS LAST,
                      alpha_size_rank(size_alpha) NULLS LAST,
                      size_age_min_months NULLS LAST,
                      size_height_cm NULLS LAST,
                      size_label
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
                        rs.getString("category_kind"),
                        rs.getString("category"),
                        rs.getString("category_mk"),
                        nullableLong(rs, "min_price_minor"),
                        nullableLong(rs, "max_price_minor"),
                        rs.getString("currency_code"),
                        rs.getInt("offer_count"),
                        rs.getInt("merchant_count"),
                        readSizes(rs, "available_sizes_eu"),
                        readLabels(rs, "available_sizes_alpha"),
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
                        rs.getString("size_alpha"),
                        rs.getString("size_alpha_max"),
                        rs.getString("size_system"),
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
                             String imageUrl, String categoryKind,
                             String category, String categoryMk,
                             Long minPriceMinor,
                             Long maxPriceMinor, String currency,
                             int offerCount, int merchantCount,
                             List<Double> availableSizesEu,
                             List<String> availableSizes, Instant updatedAt,
                             int minorUnit) {
    }

    public record OfferVariantRow(long offerId, String merchantSlug,
                                  String merchantName, Double rating,
                                  int reviewCount, boolean publishesStock,
                                  Integer deliveryDaysMin, Integer deliveryDaysMax,
                                  String relatedMerchantSlug, long variantId,
                                  String sizeLabel, Double sizeEu,
                                  String sizeAlpha, String sizeAlphaMax,
                                  String sizeSystem,
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

    /**
     * Text sizes, in the order the database put them.
     *
     * <p>Unsorted here on purpose, unlike {@link #readSizes}: the array is
     * built in ladder order by {@code alpha_size_rank}, and sorting the
     * strings again would hand the rail 3XL, L, M, S, XL, XS.
     */
    private static List<String> readLabels(ResultSet rs, String column) throws SQLException {
        var array = rs.getArray(column);
        if (array == null) {
            return List.of();
        }
        Object raw = array.getArray();
        List<String> out = new ArrayList<>();
        if (raw instanceof Object[] values) {
            for (Object value : values) {
                if (value != null) {
                    out.add(value.toString());
                }
            }
        }
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
