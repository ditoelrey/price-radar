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
               -- Every word of the query has to be found somewhere, and
               -- "somewhere" is wider than our own name for the product.
               -- See `tokenQuery` for why this is word-wise and what the
               -- shop's own title and URL are doing in here.
               -- Gated on `:q`, not on `:qTokens`. The two say different
               -- things: no query at all means no filter, while a query
               -- that yields no usable token -- "%" or "---" -- must match
               -- nothing. Keying the gate on the token array conflated
               -- them and answered "%" with the whole catalogue.
               AND (CAST(:q AS text) IS NULL
                    OR p.primary_mpn ILIKE CAST(:qSku AS text)
                    OR (CAST(:qTokens AS text[]) IS NOT NULL
                        AND NOT EXISTS (
                        SELECT 1
                          FROM unnest(CAST(:qTokens AS text[])) AS needle(tok)
                         WHERE p.canonical_name NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(b.name, '') NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(p.primary_mpn, '') NOT ILIKE '%' || needle.tok || '%'
                           -- The leaf's Macedonian name, which is what makes
                           -- a pasted "Дуксер" or "Патики" resolve without a
                           -- stop-word list: the word is not discarded, it is
                           -- required to describe the product.
                           AND coalesce(cat.name_mk, '') NOT ILIKE '%' || needle.tok || '%'
                           -- And the shop's own words. `raw_title` carries
                           -- what the merchant printed, `product_url` its
                           -- Latin shelf -- so `dukser` and `patiki` match
                           -- the same products `Дуксер` and `Патики` do,
                           -- with no transliteration table to maintain.
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM merchant_offer qmo
                                WHERE qmo.product_id = p.id
                                  AND qmo.status = 'active'
                                  AND (qmo.raw_title ILIKE '%' || needle.tok || '%'
                                       OR qmo.product_url ILIKE '%' || needle.tok || '%')))))
               AND (CAST(:brand AS text) IS NULL
                    OR b.slug = ANY(
                           string_to_array(CAST(:brand AS text), ',')))
               -- Which shops carry it. A group of its own, so picking two
               -- shops widens within the group and narrows against every
               -- other one, the same as the rest.
               --
               -- EXISTS rather than a join: `merchant_offer` has many rows
               -- per product, and joining would multiply the result before
               -- the LIMIT ever saw it.
               AND (CAST(:shop AS text) IS NULL
                    OR EXISTS (
                        SELECT 1
                          FROM merchant_offer smo
                          JOIN merchant sm ON sm.id = smo.merchant_id
                         WHERE smo.product_id = p.id
                           AND smo.status = 'active'
                           AND sm.slug = ANY(
                                   string_to_array(CAST(:shop AS text), ','))))
               -- An exact leaf match, so asking for Копачки returns cleats
               -- and nothing else -- not the generic `footwear` parent, which
               -- means "a shoe, kind unspecified".
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = ANY(
                           string_to_array(CAST(:category AS text), ',')))
               -- The men's and women's departments include unisex articles,
               -- which is not a convenience we invented: it is how every one
               -- of these shops publishes its own facets ("maski+unisex").
               -- Kids' does not, and an explicit `unisex` asks for only
               -- those. A NULL gender is excluded from every gender filter --
               -- unknown is not a department -- unlike the `kind` scope,
               -- where unknown products are admitted because the default
               -- storefront would otherwise hide most of the catalogue.
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = ANY(
                           string_to_array(CAST(:gender AS text), ','))
                    OR (p.gender = 'unisex'
                        AND string_to_array(CAST(:gender AS text), ',')
                            && ARRAY['men', 'women'])
                    -- `adults` is "everything a grown-up buys": men, women
                    -- and unisex, but not kids. It exists because the Опрема
                    -- menu stopped splitting the adult departments -- most
                    -- equipment is unisex, so Мажи and Жени were roughly 85
                    -- percent the same links -- and a leaf link carrying no
                    -- gender at all would put 19-21 baby socks back beside a
                    -- men's three-pack, which is the mixing that split was
                    -- made to end.
                    --
                    -- An unclassified article is included: `gender IS NULL`
                    -- means we do not know who it is for, and hiding it from
                    -- the only adult route there is would lose it entirely.
                    OR ('adults' = ANY(
                            string_to_array(CAST(:gender AS text), ','))
                        AND (p.gender IS NULL OR p.gender <> 'kids')))
               -- Fragrances only, and an exact match. "Valentino Donna" in
               -- Eau de Parfum and in Eau de Toilette are different liquids
               -- at different prices, so a shopper asking for EDP must not
               -- be shown the EDT beside it.
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
               -- A price band, or several. The bounds arrive as two parallel
               -- lists -- `:priceLo` and `:priceHi`, one pair per band -- so
               -- nothing of the shopper's is ever spliced into SQL and a
               -- malformed band cannot reach the database at all; the service
               -- drops it. An open top band carries -1.
               --
               -- Lower bound inclusive, upper exclusive, so the bands a
               -- shopper reads as "1 000 - 2 500" and "2 500 - 5 000" cannot
               -- both claim a product at exactly 2 500.
               AND (CAST(:priceLo AS text) IS NULL
                    OR EXISTS (
                        SELECT 1
                          FROM unnest(
                                   string_to_array(CAST(:priceLo AS text), ',')::bigint[],
                                   string_to_array(CAST(:priceHi AS text), ',')::bigint[])
                               AS band(lo, hi)
                         WHERE s.min_price_minor >= band.lo
                           AND (band.hi < 0 OR s.min_price_minor < band.hi)))
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
               -- Every word of the query has to be found somewhere, and
               -- "somewhere" is wider than our own name for the product.
               -- See `tokenQuery` for why this is word-wise and what the
               -- shop's own title and URL are doing in here.
               -- Gated on `:q`, not on `:qTokens`. The two say different
               -- things: no query at all means no filter, while a query
               -- that yields no usable token -- "%" or "---" -- must match
               -- nothing. Keying the gate on the token array conflated
               -- them and answered "%" with the whole catalogue.
               AND (CAST(:q AS text) IS NULL
                    OR p.primary_mpn ILIKE CAST(:qSku AS text)
                    OR (CAST(:qTokens AS text[]) IS NOT NULL
                        AND NOT EXISTS (
                        SELECT 1
                          FROM unnest(CAST(:qTokens AS text[])) AS needle(tok)
                         WHERE p.canonical_name NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(b.name, '') NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(p.primary_mpn, '') NOT ILIKE '%' || needle.tok || '%'
                           -- The leaf's Macedonian name, which is what makes
                           -- a pasted "Дуксер" or "Патики" resolve without a
                           -- stop-word list: the word is not discarded, it is
                           -- required to describe the product.
                           AND coalesce(cat.name_mk, '') NOT ILIKE '%' || needle.tok || '%'
                           -- And the shop's own words. `raw_title` carries
                           -- what the merchant printed, `product_url` its
                           -- Latin shelf -- so `dukser` and `patiki` match
                           -- the same products `Дуксер` and `Патики` do,
                           -- with no transliteration table to maintain.
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM merchant_offer qmo
                                WHERE qmo.product_id = p.id
                                  AND qmo.status = 'active'
                                  AND (qmo.raw_title ILIKE '%' || needle.tok || '%'
                                       OR qmo.product_url ILIKE '%' || needle.tok || '%')))))
               AND (CAST(:brand AS text) IS NULL
                    OR b.slug = ANY(
                           string_to_array(CAST(:brand AS text), ',')))
               -- Which shops carry it. A group of its own, so picking two
               -- shops widens within the group and narrows against every
               -- other one, the same as the rest.
               --
               -- EXISTS rather than a join: `merchant_offer` has many rows
               -- per product, and joining would multiply the result before
               -- the LIMIT ever saw it.
               AND (CAST(:shop AS text) IS NULL
                    OR EXISTS (
                        SELECT 1
                          FROM merchant_offer smo
                          JOIN merchant sm ON sm.id = smo.merchant_id
                         WHERE smo.product_id = p.id
                           AND smo.status = 'active'
                           AND sm.slug = ANY(
                                   string_to_array(CAST(:shop AS text), ','))))
               -- An exact leaf match, so asking for Копачки returns cleats
               -- and nothing else -- not the generic `footwear` parent, which
               -- means "a shoe, kind unspecified".
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = ANY(
                           string_to_array(CAST(:category AS text), ',')))
               -- The men's and women's departments include unisex articles,
               -- which is not a convenience we invented: it is how every one
               -- of these shops publishes its own facets ("maski+unisex").
               -- Kids' does not, and an explicit `unisex` asks for only
               -- those. A NULL gender is excluded from every gender filter --
               -- unknown is not a department -- unlike the `kind` scope,
               -- where unknown products are admitted because the default
               -- storefront would otherwise hide most of the catalogue.
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = ANY(
                           string_to_array(CAST(:gender AS text), ','))
                    OR (p.gender = 'unisex'
                        AND string_to_array(CAST(:gender AS text), ',')
                            && ARRAY['men', 'women'])
                    -- `adults` is "everything a grown-up buys": men, women
                    -- and unisex, but not kids. It exists because the Опрема
                    -- menu stopped splitting the adult departments -- most
                    -- equipment is unisex, so Мажи and Жени were roughly 85
                    -- percent the same links -- and a leaf link carrying no
                    -- gender at all would put 19-21 baby socks back beside a
                    -- men's three-pack, which is the mixing that split was
                    -- made to end.
                    --
                    -- An unclassified article is included: `gender IS NULL`
                    -- means we do not know who it is for, and hiding it from
                    -- the only adult route there is would lose it entirely.
                    OR ('adults' = ANY(
                            string_to_array(CAST(:gender AS text), ','))
                        AND (p.gender IS NULL OR p.gender <> 'kids')))
               -- Fragrances only, and an exact match. "Valentino Donna" in
               -- Eau de Parfum and in Eau de Toilette are different liquids
               -- at different prices, so a shopper asking for EDP must not
               -- be shown the EDT beside it.
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
               -- A price band, or several. The bounds arrive as two parallel
               -- lists -- `:priceLo` and `:priceHi`, one pair per band -- so
               -- nothing of the shopper's is ever spliced into SQL and a
               -- malformed band cannot reach the database at all; the service
               -- drops it. An open top band carries -1.
               --
               -- Lower bound inclusive, upper exclusive, so the bands a
               -- shopper reads as "1 000 - 2 500" and "2 500 - 5 000" cannot
               -- both claim a product at exactly 2 500.
               AND (CAST(:priceLo AS text) IS NULL
                    OR EXISTS (
                        SELECT 1
                          FROM unnest(
                                   string_to_array(CAST(:priceLo AS text), ',')::bigint[],
                                   string_to_array(CAST(:priceHi AS text), ',')::bigint[])
                               AS band(lo, hi)
                         WHERE z.from_price_minor >= band.lo
                           AND (band.hi < 0 OR z.from_price_minor < band.hi)))
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
                                       String sizeEu, String sizeAlpha,
                                       String sizeMl,
                                       String[] kinds,
                                       boolean includeUnclassified,
                                       String categorySlug, String gender,
                                       String concentration, String shopSlug,
                                       String priceLo, String priceHi,
                                       Sort sort, int limit, int offset) {
        String alpha = blankToNull(sizeAlpha);
        // An EU number wins when both arrive. They cannot both be satisfied
        // -- no variant carries both -- so honouring both would return an
        // empty page for a shopper who merely changed vertical with a size
        // still in the URL.
        // One axis wins when several arrive, and the order is deliberate:
        // the EU number is the most specific thing a shopper can have asked
        // for, and a volume is unambiguous where a letter is a fallback.
        // Honouring two at once cannot work -- no variant carries two -- so
        // it would empty the page for a shopper who merely changed vertical
        // with a size still in the URL.
        SizeAxis axis = blankToNull(sizeEu) != null ? SizeAxis.EU
                : blankToNull(sizeMl) != null ? SizeAxis.VOLUME
                : alpha != null ? SizeAxis.ALPHA
                : null;
        boolean sized = axis != null;
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
            sql = sql.replace("/*{SIZE_MATCH}*/", sizeMatch(axis));
        }
        var spec = db.sql(sql)
                .param("q", normalizeQuery(query))
                .param("qTokens", tokenQuery(query))
                .param("qSku", skuQuery(query))
                .param("brand", blankToNull(brandSlug))
                .param("kinds", kinds)
                .param("includeUnclassified", includeUnclassified)
                .param("category", blankToNull(categorySlug))
                .param("gender", blankToNull(gender))
                .param("concentration", blankToNull(concentration))
                .param("shop", blankToNull(shopSlug))
                .param("priceLo", blankToNull(priceLo))
                .param("priceHi", blankToNull(priceHi))
                .param("limit", limit)
                .param("offset", offset);
        if (axis == SizeAxis.EU) {
            spec = spec.param("sizeEu", blankToNull(sizeEu));
        } else if (axis == SizeAxis.VOLUME) {
            spec = spec.param("sizeMl", blankToNull(sizeMl));
        } else if (axis == SizeAxis.ALPHA) {
            spec = spec.param("sizeAlpha", alpha);
        } else {
            spec = spec.param("country", country);
        }
        return spec.query((rs, rowNum) -> mapCard(rs, sized)).list();
    }

    /**
     * How many products the same filters match, ignoring the page.
     *
     * <p>Built from the listing's own SQL rather than from a second copy of
     * its WHERE clause: everything up to the `ORDER BY` is wrapped in a
     * `count(*)`, so the two cannot drift. That matters here more than
     * usual -- there are already four copies of the search predicate in
     * this file, and a count that disagreed with the listing would number
     * pages that come back empty.
     *
     * <p>It is a second query, which the comment on `hasMore` calls pure
     * waste, and that was right while nothing needed the figure. A numbered
     * pagination bar does: it cannot say "page 3 of 50", or offer the last
     * page, without knowing. Measured on the full catalogue unfiltered --
     * the worst case, 30 000 products and no predicate to narrow it -- the
     * count runs in about 31 ms against a request that already takes 150,
     * and `hasMore` keeps its cheap `pageSize + 1` trick for the rows
     * themselves so the fast LIMIT path is untouched.
     */
    public int count(String country, String query, String brandSlug,
                     String sizeEu, String sizeAlpha, String sizeMl,
                     String[] kinds, boolean includeUnclassified,
                     String categorySlug, String gender,
                     String concentration, String shopSlug,
                     String priceLo, String priceHi) {
        String alpha = blankToNull(sizeAlpha);
        SizeAxis axis = blankToNull(sizeEu) != null ? SizeAxis.EU
                : blankToNull(sizeMl) != null ? SizeAxis.VOLUME
                : alpha != null ? SizeAxis.ALPHA
                : null;
        boolean sized = axis != null;
        String listing = sized ? LIST_BY_SIZE : LIST_BASE;
        int orderAt = listing.indexOf("ORDER BY /*{ORDER}*/");
        if (orderAt < 0) {
            throw new IllegalStateException(
                    "listing SQL lost its ORDER BY marker; the count is "
                    + "derived from it and would silently count the wrong rows");
        }
        String sql = "SELECT count(*) FROM ("
                + listing.substring(0, orderAt) + ") AS matched";
        if (sized) {
            sql = sql.replace("/*{SIZE_MATCH}*/", sizeMatch(axis));
        }
        var spec = db.sql(sql)
                .param("q", normalizeQuery(query))
                .param("qTokens", tokenQuery(query))
                .param("qSku", skuQuery(query))
                .param("brand", blankToNull(brandSlug))
                .param("kinds", kinds)
                .param("includeUnclassified", includeUnclassified)
                .param("category", blankToNull(categorySlug))
                .param("gender", blankToNull(gender))
                .param("concentration", blankToNull(concentration))
                .param("shop", blankToNull(shopSlug))
                .param("priceLo", blankToNull(priceLo))
                .param("priceHi", blankToNull(priceHi));
        if (axis == SizeAxis.EU) {
            spec = spec.param("sizeEu", blankToNull(sizeEu));
        } else if (axis == SizeAxis.VOLUME) {
            spec = spec.param("sizeMl", blankToNull(sizeMl));
        } else if (axis == SizeAxis.ALPHA) {
            spec = spec.param("sizeAlpha", alpha);
        } else {
            spec = spec.param("country", country);
        }
        return spec.query(Integer.class).single();
    }

    /**
     * The predicate that narrows the sized CTE to one size.
     *
     * <p>Package-private so a test can assert which axis each flag selects
     * without a database: getting this backwards would quietly return every
     * garment for a shoe size and vice versa, and both read as "no results"
     * rather than as an error.
     */
    /**
     * Which column a size filter is asking about.
     *
     * <p>Three axes, and nothing carries two of them: a shoe has an EU
     * number, a garment a letter, a fragrance a volume in millilitres. The
     * axis therefore has to be decided before the query is built, and
     * asking the wrong one of a product returns an empty page -- which a
     * shopper reads as "this shop has nothing" rather than as a bug.
     */
    public enum SizeAxis { EU, ALPHA, VOLUME }

    static String sizeMatch(SizeAxis axis) {
        // The letter side is a range test, not an equality, because a label
        // can name two sizes: "M/L" is stored as size_alpha M with
        // size_alpha_max L, and has to answer a shopper filtering either.
        // coalesce collapses the ordinary single-letter row to M..M, so the
        // same expression serves both and there is no second code path to
        // keep in step. A NULL size_alpha ranks NULL and matches nothing,
        // which is what a variant with no letter size should do.
        //
        // Millilitres are a plain equality, unlike the letters. A bottle is
        // 50ml or it is not; there is no span to straddle, because no shop
        // here prints one.
        // Each axis takes a list now, because a shopper who wears 42 is
        // served by 42 and 42.5 both and should not have to choose. The
        // CTE's `min(ov.price_minor)` then prices the product at the
        // cheapest offer in ANY selected size, which is the figure the card
        // should show.
        return switch (axis) {
            case EU -> "ov.size_eu = ANY(string_to_array("
                    + "CAST(:sizeEu AS text), ',')::numeric[])";
            case VOLUME -> "ov.size_ml = ANY(string_to_array("
                    + "CAST(:sizeMl AS text), ',')::integer[])";
            // The letters stay a range test per selected value -- "M/L" is
            // stored M..L and has to answer a shopper filtering either --
            // so the list is unnested rather than compared with ANY.
            case ALPHA -> "EXISTS (SELECT 1 FROM unnest(string_to_array("
                    + "CAST(:sizeAlpha AS text), ',')) AS want(v) "
                    + "WHERE alpha_size_rank(want.v) BETWEEN "
                    + "alpha_size_rank(ov.size_alpha) AND "
                    + "alpha_size_rank(coalesce(ov.size_alpha_max, "
                    + "ov.size_alpha)))";
        };
    }

    /**
     * The predicates a facet shares with the listing, in pieces.
     *
     * <p>There are six filter groups and five facet queries, and every one of
     * them has to narrow on exactly the same terms as the listing: a facet
     * counting differently would offer a shopper an option whose page then
     * came back empty, which is worse than offering nothing. Written out per
     * query that was five copies of this clause set -- the search predicate
     * alone is thirty-five lines -- so they are assembled from one copy here
     * instead, and {@link #facetWhere} leaves out whichever group the facet
     * is enumerating.
     *
     * <p>Whitespace is the only thing that differs from {@code LIST_BASE}'s
     * own copy, which still stands apart because the listing selects columns
     * these do not and is substituted twice over for sort and size.
     */
    private static final String FACET_FROM = """
              FROM product_price_summary s
              JOIN product p ON p.id = s.product_id
              JOIN brand   b ON b.id = p.brand_id
              LEFT JOIN category cat ON cat.id = p.category_id
            """;

    /**
     * How a shop facet reaches a product: through an active offer, never a
     * dead one. A shop whose listing went away keeps its rows, and naming it
     * would claim a comparison the page cannot make.
     */
    private static final String SHOP_JOIN = """
              JOIN merchant_offer mo
                   ON mo.product_id = p.id AND mo.status = 'active'
              JOIN merchant m ON m.id = mo.merchant_id
            """;

    private static final String W_SCOPE = """
             WHERE s.country_code = CAST(:country AS text)
               AND s.min_price_minor IS NOT NULL
               AND (CAST(:kinds AS text[]) IS NULL
                    OR (cat.kind IS NULL AND :includeUnclassified)
                    OR cat.kind::text = ANY(CAST(:kinds AS text[])))
            """;

    private static final String W_QUERY = """
               -- Every word of the query has to be found somewhere, and
               -- "somewhere" is wider than our own name for the product.
               -- See `tokenQuery` for why this is word-wise and what the
               -- shop's own title and URL are doing in here.
               -- Gated on `:q`, not on `:qTokens`. The two say different
               -- things: no query at all means no filter, while a query
               -- that yields no usable token -- "%" or "---" -- must match
               -- nothing. Keying the gate on the token array conflated
               -- them and answered "%" with the whole catalogue.
               AND (CAST(:q AS text) IS NULL
                    OR p.primary_mpn ILIKE CAST(:qSku AS text)
                    OR (CAST(:qTokens AS text[]) IS NOT NULL
                        AND NOT EXISTS (
                        SELECT 1
                          FROM unnest(CAST(:qTokens AS text[])) AS needle(tok)
                         WHERE p.canonical_name NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(b.name, '') NOT ILIKE '%' || needle.tok || '%'
                           AND coalesce(p.primary_mpn, '') NOT ILIKE '%' || needle.tok || '%'
                           -- The leaf's Macedonian name, which is what makes
                           -- a pasted "Дуксер" or "Патики" resolve without a
                           -- stop-word list: the word is not discarded, it is
                           -- required to describe the product.
                           AND coalesce(cat.name_mk, '') NOT ILIKE '%' || needle.tok || '%'
                           -- And the shop's own words. `raw_title` carries
                           -- what the merchant printed, `product_url` its
                           -- Latin shelf -- so `dukser` and `patiki` match
                           -- the same products `Дуксер` and `Патики` do,
                           -- with no transliteration table to maintain.
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM merchant_offer qmo
                                WHERE qmo.product_id = p.id
                                  AND qmo.status = 'active'
                                  AND (qmo.raw_title ILIKE '%' || needle.tok || '%'
                                       OR qmo.product_url ILIKE '%' || needle.tok || '%')))))
            """;

    private static final String W_BRAND = """
               AND (CAST(:brand AS text) IS NULL
                    OR b.slug = ANY(
                           string_to_array(CAST(:brand AS text), ',')))
            """;

    private static final String W_SHOP = """
               AND (CAST(:shop AS text) IS NULL
                    OR EXISTS (
                        SELECT 1
                          FROM merchant_offer smo
                          JOIN merchant sm ON sm.id = smo.merchant_id
                         WHERE smo.product_id = p.id
                           AND smo.status = 'active'
                           AND sm.slug = ANY(
                                   string_to_array(CAST(:shop AS text), ','))))
            """;

    private static final String W_CATEGORY = """
               AND (CAST(:category AS text) IS NULL
                    OR cat.slug = ANY(
                           string_to_array(CAST(:category AS text), ',')))
            """;

    private static final String W_GENDER = """
               AND (CAST(:gender AS text) IS NULL
                    OR p.gender::text = ANY(
                           string_to_array(CAST(:gender AS text), ','))
                    OR (p.gender = 'unisex'
                        AND string_to_array(CAST(:gender AS text), ',')
                            && ARRAY['men', 'women'])
                    -- `adults` is "everything a grown-up buys": men, women
                    -- and unisex, but not kids. It exists because the Опрема
                    -- menu stopped splitting the adult departments -- most
                    -- equipment is unisex, so Мажи and Жени were roughly 85
                    -- percent the same links -- and a leaf link carrying no
                    -- gender at all would put 19-21 baby socks back beside a
                    -- men's three-pack, which is the mixing that split was
                    -- made to end.
                    --
                    -- An unclassified article is included: `gender IS NULL`
                    -- means we do not know who it is for, and hiding it from
                    -- the only adult route there is would lose it entirely.
                    OR ('adults' = ANY(
                            string_to_array(CAST(:gender AS text), ','))
                        AND (p.gender IS NULL OR p.gender <> 'kids')))
            """;

    /**
     * The price the band is measured against, for a facet.
     *
     * <p>Mirrors the listing: the overall cheapest offer normally, and the
     * cheapest in the selected size when there is one. A facet that counted
     * against the overall minimum on a size-filtered page would offer a band
     * that then held products priced outside it.
     */
    private static String priceExpr(SizeAxis axis) {
        if (axis == null) {
            return "s.min_price_minor";
        }
        return "(SELECT min(ov.price_minor)\n"
                + "   FROM merchant_offer pmo\n"
                + "   JOIN offer_variant ov ON ov.offer_id = pmo.id\n"
                + "  WHERE pmo.product_id = p.id\n"
                + "    AND pmo.status = 'active'\n"
                + "    AND ov.in_stock IS NOT FALSE\n"
                + "    AND " + sizeMatch(axis) + ")";
    }

    /** The band predicate, against whichever price expression applies. */
    private static String priceBand(String col) {
        return "   AND (CAST(:priceLo AS text) IS NULL\n"
                + "        OR EXISTS (\n"
                + "            SELECT 1\n"
                + "              FROM unnest(\n"
                + "                       string_to_array(CAST(:priceLo AS text), ',')::bigint[],\n"
                + "                       string_to_array(CAST(:priceHi AS text), ',')::bigint[])\n"
                + "                   AS band(lo, hi)\n"
                + "             WHERE " + col + " >= band.lo\n"
                + "               AND (band.hi < 0 OR " + col + " < band.hi)))\n";
    }

    private static final String W_CONCENTRATION = """
               AND (CAST(:concentration AS text) IS NULL
                    OR p.concentration = ANY(
                           string_to_array(CAST(:concentration AS text), ',')))
            """;

    /**
     * Which filter group a facet enumerates.
     *
     * <p>Also the group it must not apply. A brand facet narrowed by the
     * chosen brand answers "how many Nike products are there, given that you
     * picked Nike" -- the count the shopper can already see, and zero for
     * every other brand, so a multi-select could never add a second one.
     * Leaving a group's own filter out is what makes the numbers mean "and
     * this many more if you tick that too".
     */
    public enum Facet { BRAND, SHOP, CATEGORY, GENDER, SIZE, PRICE }

    /**
     * The WHERE clause for a facet, with its own group left out.
     *
     * <p>The size filter is the one piece that cannot be a constant: it
     * exists only when a size is selected, and the axis decides the
     * predicate. Written as an EXISTS over the offers rather than the join
     * {@code LIST_BY_SIZE} uses, because a facet counts products and a join
     * through {@code offer_variant} would multiply them.
     */
    private static String facetWhere(Facet enumerating, SizeAxis axis) {
        StringBuilder where = new StringBuilder(W_SCOPE).append(W_QUERY);
        if (enumerating != Facet.BRAND) {
            where.append(W_BRAND);
        }
        if (enumerating != Facet.SHOP) {
            where.append(W_SHOP);
        }
        if (enumerating != Facet.CATEGORY) {
            where.append(W_CATEGORY);
        }
        if (enumerating != Facet.GENDER) {
            where.append(W_GENDER);
        }
        where.append(W_CONCENTRATION);
        if (enumerating != Facet.PRICE) {
            where.append(priceBand(priceExpr(axis)));
        }
        if (enumerating != Facet.SIZE && axis != null) {
            where.append("""
               AND EXISTS (
                   SELECT 1
                     FROM merchant_offer fmo
                     JOIN offer_variant ov ON ov.offer_id = fmo.id
                    WHERE fmo.product_id = p.id
                      AND fmo.status = 'active'
                      AND ov.in_stock IS NOT FALSE
                      AND
                      """).append(sizeMatch(axis)).append(")\n");
        }
        return where.toString();
    }

    /**
     * One option list: the values of a group, with how many products each
     * would leave on the page.
     *
     * <p>{@code count(DISTINCT p.id)} throughout, so the number beside a shop
     * means what the number beside a brand means -- products, not listings.
     * A shop that lists one product under three SKUs counts once.
     */
    static String facetSql(Facet facet, SizeAxis axis) {
        String select = switch (facet) {
            case BRAND -> "SELECT b.slug AS value, b.name AS label,\n"
                    + "       count(DISTINCT p.id) AS product_count\n";
            case SHOP -> "SELECT m.slug AS value, m.name AS label,\n"
                    + "       count(DISTINCT p.id) AS product_count\n";
            // The Macedonian leaf name as the label, read from the column the
            // listing heading and the mega menu already use, so a leaf cannot
            // be called two things one control apart.
            case CATEGORY -> "SELECT cat.slug AS value, cat.name_mk AS label,\n"
                    + "       count(DISTINCT p.id) AS product_count\n";
            case GENDER -> "SELECT p.gender::text AS value,\n"
                    + "       p.gender::text AS label,\n"
                    + "       count(DISTINCT p.id) AS product_count\n";
            case SIZE -> throw new IllegalArgumentException(
                    "sizes come from sizeFacetSql: they are three axes in one "
                    + "group and are counted from the summary's own arrays");
            case PRICE -> throw new IllegalArgumentException(
                    "price bands come from priceFacetSql: the options are the "
                    + "site's own bands, not values found in a column");
        };
        String tail = switch (facet) {
            case BRAND -> """
             GROUP BY b.slug, b.name
             ORDER BY product_count DESC, b.name
             LIMIT :limit
            """;
            case SHOP -> """
             GROUP BY m.slug, m.name
             ORDER BY product_count DESC, m.name
             LIMIT :limit
            """;
            // An unclassified product has no leaf to offer, so it is counted
            // in the listing and left out of this control.
            case CATEGORY -> """
             GROUP BY cat.slug, cat.name_mk
            HAVING cat.slug IS NOT NULL
             ORDER BY product_count DESC, cat.name_mk
             LIMIT :limit
            """;
            case GENDER -> """
             GROUP BY p.gender
            HAVING p.gender IS NOT NULL
             ORDER BY product_count DESC
            """;
            case SIZE, PRICE -> "";
        };
        return select + FACET_FROM
                + (facet == Facet.SHOP ? SHOP_JOIN : "")
                + facetWhere(facet, axis) + tail;
    }

    /**
     * The size options, all three axes at once.
     *
     * <p>Counted from {@code product_price_summary}'s own arrays rather than
     * from {@code offer_variant}, which is where the rail has always read
     * them: the arrays are already "sizes a shopper can actually buy"
     * ({@code in_stock IS NOT FALSE}, distinct, in order), and recomputing
     * that per request would join three tables to reach the same answer.
     *
     * <p>Three branches because a shoe is on the EU ladder, a garment on the
     * letters and a bottle in millilitres, and no product is on two. Which
     * branch comes back with rows is how the control knows which rail to
     * draw. {@code ord} carries the ladder: sorting the letters as text gives
     * 3XL, L, M, S, XL.
     */
    static String sizeFacetSql(SizeAxis axis) {
        String where = facetWhere(Facet.SIZE, axis);
        return "SELECT axis, value, product_count\n  FROM (\n"
                // Trailing zeros off the EU number: the column is numeric
                // with a scale, so the raw text of a 42 reads "42.000" and of
                // a 42.5 "42.500", and the chip has to say what the shop
                // says.
                + sizeBranch("eu", "available_sizes_eu",
                        "trim(trailing '.' from "
                        + "trim(trailing '0' from opt.v::text))",
                        "opt.v::numeric", where)
                + "UNION ALL\n"
                + sizeBranch("alpha", "available_sizes_alpha", "opt.v",
                        "alpha_size_rank(opt.v)::numeric", where)
                + "UNION ALL\n"
                + sizeBranch("ml", "available_volumes_ml", "opt.v::text",
                        "opt.v::numeric", where)
                + ") AS opts\n ORDER BY axis, ord\n";
    }

    /**
     * One axis of the size facet.
     *
     * <p>Concatenated rather than formatted: {@code where} carries the search
     * predicate, whose {@code '%' || needle.tok || '%'} would be read as a
     * format specifier and throw.
     */
    private static String sizeBranch(String axis, String column, String value,
                                     String ord, String where) {
        return "SELECT '" + axis + "' AS axis, " + value + " AS value,\n"
                + "       " + ord + " AS ord,\n"
                + "       count(DISTINCT p.id) AS product_count\n"
                + FACET_FROM
                + "  CROSS JOIN LATERAL unnest(s." + column + ") AS opt(v)\n"
                + where
                + " GROUP BY 1, 2, 3\n";
    }

    /**
     * The price bands, each with the number of products inside it.
     *
     * <p>The one group whose options are not values read out of a column:
     * they are bands this site chose, so they arrive as a VALUES list and the
     * query counts into them. Which bands exist is the caller's business --
     * the storefront writes the Macedonian labels, since every other label on
     * the page is written there too.
     *
     * <p>`lo` inclusive and `hi` exclusive, matching the listing predicate, so
     * the count beside a band is what the page would hold.
     */
    static String priceFacetSql(SizeAxis axis, int bands) {
        StringBuilder values = new StringBuilder();
        for (int i = 0; i < bands; i++) {
            values.append(i == 0 ? "" : ", ")
                  .append("(CAST(:bandId").append(i).append(" AS text), ")
                  .append("CAST(:bandLo").append(i).append(" AS bigint), ")
                  .append("CAST(:bandHi").append(i).append(" AS bigint))");
        }
        return "SELECT pb.id AS value, pb.id AS label,\n"
                + "       count(DISTINCT p.id) AS product_count\n"
                + FACET_FROM
                + "  JOIN LATERAL (SELECT " + priceExpr(axis)
                + " AS px) AS pr ON TRUE\n"
                + "  CROSS JOIN (VALUES " + values + ") AS pb(id, lo, hi)\n"
                + facetWhere(Facet.PRICE, axis)
                + "   AND pr.px >= pb.lo\n"
                + "   AND (pb.hi < 0 OR pr.px < pb.hi)\n"
                + " GROUP BY pb.id, pb.lo\n"
                + " ORDER BY pb.lo\n";
    }

    /** One band of the price facet: an id the URL carries, and its bounds. */
    public record PriceBand(String id, long lo, long hi) {
    }

    /** The listing SQL, exposed so a test can hold the facets beside it. */
    static String listBaseSql() {
        return LIST_BASE;
    }

    /** The facet SQL, exposed so a test can hold it beside the listing's. */
    static String brandFacetsSql() {
        return facetSql(Facet.BRAND, null);
    }

    /** The facet SQL, exposed so a test can hold it beside the listing's. */
    static String merchantFacetsSql() {
        return facetSql(Facet.SHOP, null);
    }

    /**
     * Everything a facet has to narrow by, as one value.
     *
     * <p>Seven filters and a country, passed as a record because they travel
     * together to five queries, and a positional argument list that long is
     * how a category ends up bound to the gender parameter.
     */
    public record FacetScope(String country, String query, String[] kinds,
                             boolean includeUnclassified, String brandSlug,
                             String shopSlug, String categorySlug,
                             String gender, String concentration,
                             String priceLo, String priceHi,
                             String sizeEu, String sizeAlpha, String sizeMl) {
    }

    /** The axis a size list is on, or null when nothing is filtered. */
    static SizeAxis axisOf(String sizeEu, String sizeAlpha, String sizeMl) {
        return blankToNull(sizeEu) != null ? SizeAxis.EU
                : blankToNull(sizeMl) != null ? SizeAxis.VOLUME
                : blankToNull(sizeAlpha) != null ? SizeAxis.ALPHA
                : null;
    }

    private org.springframework.jdbc.core.simple.JdbcClient.StatementSpec
            bindFacet(String sql, FacetScope f, SizeAxis axis) {
        var spec = db.sql(sql)
                .param("country", f.country())
                .param("q", normalizeQuery(f.query()))
                .param("qTokens", tokenQuery(f.query()))
                .param("qSku", skuQuery(f.query()))
                .param("kinds", f.kinds())
                .param("includeUnclassified", f.includeUnclassified())
                .param("brand", blankToNull(f.brandSlug()))
                .param("shop", blankToNull(f.shopSlug()))
                .param("category", blankToNull(f.categorySlug()))
                .param("gender", blankToNull(f.gender()))
                .param("concentration", blankToNull(f.concentration()))
                .param("priceLo", blankToNull(f.priceLo()))
                .param("priceHi", blankToNull(f.priceHi()));
        // Bound only when the SQL asks for it. A facet that leaves its own
        // group out has no placeholder for it, and the template only looks up
        // the names it finds.
        if (axis == SizeAxis.EU) {
            spec = spec.param("sizeEu", blankToNull(f.sizeEu()));
        } else if (axis == SizeAxis.VOLUME) {
            spec = spec.param("sizeMl", blankToNull(f.sizeMl()));
        } else if (axis == SizeAxis.ALPHA) {
            spec = spec.param("sizeAlpha", blankToNull(f.sizeAlpha()));
        }
        return spec;
    }

    /** One group's options under the given scope, commonest first. */
    public List<Dtos.FacetOption> facet(Facet facet, FacetScope f, int limit) {
        SizeAxis axis = axisOf(f.sizeEu(), f.sizeAlpha(), f.sizeMl());
        return bindFacet(facetSql(facet, axis), f, axis)
                .param("limit", limit)
                .query((rs, rowNum) -> new Dtos.FacetOption(
                        rs.getString("value"),
                        rs.getString("label"),
                        rs.getInt("product_count")))
                .list();
    }

    /** The price bands under the given scope, cheapest band first. */
    public List<Dtos.FacetOption> priceFacet(FacetScope f,
                                             List<PriceBand> bands) {
        SizeAxis axis = axisOf(f.sizeEu(), f.sizeAlpha(), f.sizeMl());
        var spec = bindFacet(priceFacetSql(axis, bands.size()), f, axis);
        for (int i = 0; i < bands.size(); i++) {
            PriceBand band = bands.get(i);
            spec = spec.param("bandId" + i, band.id())
                       .param("bandLo" + i, band.lo())
                       .param("bandHi" + i, band.hi());
        }
        return spec.query((rs, rowNum) -> new Dtos.FacetOption(
                        rs.getString("value"),
                        rs.getString("label"),
                        rs.getInt("product_count")))
                .list();
    }

    /** The size options on every axis the scope has, in ladder order. */
    public List<Dtos.SizeOption> sizeFacet(FacetScope f) {
        SizeAxis axis = axisOf(f.sizeEu(), f.sizeAlpha(), f.sizeMl());
        return bindFacet(sizeFacetSql(axis), f, axis)
                .query((rs, rowNum) -> new Dtos.SizeOption(
                        rs.getString("axis"),
                        rs.getString("value"),
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
            SELECT p.id, p.slug, p.canonical_name, b.name AS brand,
                   b.slug AS brand_slug, p.colorway,
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

    /** The detail SQL, exposed so a test can pin what the breadcrumb needs. */
    static String productBySlugSql() {
        return PRODUCT_BY_SLUG;
    }

    public Optional<ProductRow> findProductBySlug(String slug) {
        return db.sql(PRODUCT_BY_SLUG).param("slug", slug)
                .query((rs, rowNum) -> new ProductRow(
                        rs.getLong("id"),
                        rs.getString("slug"),
                        rs.getString("canonical_name"),
                        rs.getString("brand"),
                        rs.getString("brand_slug"),
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
                             String brandSlug,
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

    /**
     * The query as an ILIKE pattern, with punctuation made permissive.
     *
     * <p>Two jobs, and the first one was a bug. A shopper who copies a name
     * off a shop's page brings its punctuation with them, and we did not
     * store it: `clean_model_name` turns "adidas 3-Stripes" into
     * "Adidas 3 Stripes" on one shop and "Adidas 3stripes" on another. So
     * `3-stripes` matched neither spelling and the search came back empty on
     * a product we hold six of.
     *
     * <p>Each run of punctuation becomes {@code %}, which matches the space,
     * the nothing, or the hyphen itself. Spaces stay literal: turning those
     * into wildcards too would let "nike air" match a name with twelve words
     * between them, and that is a different search from the one asked for.
     *
     * <p>The second job is that {@code %} and {@code _} are ILIKE
     * metacharacters and arrived unescaped, so a shopper typing a lone
     * {@code %} matched the whole catalogue. They are escaped first, and the
     * punctuation rule is written so it cannot eat the escapes it just
     * added.
     */
    /**
     * The query split into words, each an ILIKE pattern.
     *
     * <p>Search was one substring: the whole query, wrapped in wildcards,
     * matched against our own name for the product. That fails the moment a
     * shopper pastes a title off a shop's page, because the words are ours
     * and the paste is theirs. `clean_model_name` drops the merchant's
     * category noun, so "Juicy Couture Дуксер Classic Velour" -- copied from
     * buzz -- had to match "Juicy Couture Classic Velour", and a contiguous
     * pattern cannot.
     *
     * <p>So every word must be found, and each may be found in a different
     * place: our canonical name, the brand, the article code, the leaf's
     * Macedonian name, or the shop's own `raw_title` and `product_url`.
     *
     * <p><b>Why no stop-word list.</b> The obvious fix is to discard generic
     * Macedonian nouns -- дуксер, патики, маица -- when the rest of the
     * query matches. That widens every search that contains one: "патики
     * nike" would return Nike perfume. Requiring the word to appear in the
     * category's own name instead keeps it a filter rather than noise, and
     * there is no vocabulary to keep up to date as leaves are added.
     *
     * <p>Transliteration comes free the same way. `product_url` holds the
     * shop's Latin shelf (`/mk/dukser/`, `/mk/patiki/`), so a shopper typing
     * either script reaches the same products without a mapping table.
     *
     * <p>Order within the query stops mattering, which is the point: a
     * pasted title has the merchant's word order, not ours.
     */
    static String[] tokenQuery(String query) {
        String pattern = likeQuery(query);
        if (pattern == null) {
            return null;
        }
        List<String> tokens = new ArrayList<>();
        for (String word : pattern.split(" +")) {
            if (!word.isBlank() && !word.replace("%", "").replace("\\", "").isBlank()) {
                tokens.add(word);
            }
        }
        return tokens.isEmpty() ? null : tokens.toArray(new String[0]);
    }

    static String likeQuery(String query) {
        if (query == null || query.isBlank()) {
            return null;
        }
        // A query with no letter and no digit in it matches nothing. Caught
        // live: "---" reduced to "%", the predicate wrapped that in two
        // more, and the search answered with the entire catalogue.
        if (query.codePoints().noneMatch(Character::isLetterOrDigit)) {
            return null;
        }
        String escaped = query.trim()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_");
        return escaped.replaceAll("[^\\p{L}\\p{N}\\\\%_ ]+", "%");
    }

    /**
     * The query as an article code, punctuation stripped and upper-cased.
     *
     * <p>Sport Vision, Buzz and Nike print {@code HV0949-313} and
     * {@code 9A0693-AA7}; `normalize_sku` stored {@code HV0949313} and
     * {@code 9A0693AA7}. Measured: all 29 498 stored MPNs are free of
     * punctuation, so the normalisation is entirely one-sided -- the column
     * needs no expression index and the query needs stripping.
     *
     * <p>Returns null where nothing is left, so a query of pure punctuation
     * does not become an empty pattern that matches every unnamed article.
     */
    static String skuQuery(String query) {
        if (query == null || query.isBlank()) {
            return null;
        }
        String bare = query.replaceAll("[^A-Za-z0-9]", "")
                .toUpperCase(java.util.Locale.ROOT);
        return bare.isEmpty() ? null : bare;
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
