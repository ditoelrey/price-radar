package mk.priceradar.api.catalog;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import mk.priceradar.api.common.PriceRadarProperties;
import org.springframework.stereotype.Service;

/** Assembles the read model from repository rows. */
@Service
public class CatalogService {

    /**
     * Shown with every price. Not legal boilerplate: the prices here are
     * collected from the shops and are minutes-to-hours old, none of the MK
     * stores sends a cache validator, and saying so plainly is cheaper than
     * any amount of crawling and does more for trust.
     */
    static final String PRICE_DISCLAIMER =
            "Prices and availability are reported by the shops and may have changed. "
            + "Each offer shows when we last checked it.";

    private final CatalogRepository repository;
    private final Duration staleAfter;
    private final String country;

    public CatalogService(CatalogRepository repository, PriceRadarProperties props) {
        this.repository = repository;
        this.staleAfter = Duration.ofMinutes(props.freshness().staleAfterMinutes());
        this.country = props.country();
    }

    public Dtos.ProductPage search(String query, String brand, Double sizeEu,
                                   int page, int pageSize) {
        return search(query, brand, sizeEu, null,
                CatalogRepository.FOOTWEAR_KINDS,
                true, null, null, CatalogRepository.Sort.CHEAPEST,
                page, pageSize);
    }

    /**
     * @param kinds category kinds to admit; null admits every category.
     *        Defaults to footwear, because this is a sneaker comparison site
     *        and the ingestion side crawls merchants that also sell socks,
     *        ski leggings and helmets.
     */
    public Dtos.ProductPage search(String query, String brand, Double sizeEu,
                                   String size,
                                   String[] kinds, boolean includeUnclassified,
                                   String category, String gender,
                                   CatalogRepository.Sort sort,
                                   int page, int pageSize) {
        return search(query, brand, sizeEu, size, kinds, includeUnclassified,
                category, gender, null, sort, page, pageSize);
    }

    /** As above, narrowed to one fragrance concentration. */
    public Dtos.ProductPage search(String query, String brand, Double sizeEu,
                                   String size,
                                   String[] kinds, boolean includeUnclassified,
                                   String category, String gender,
                                   String concentration,
                                   CatalogRepository.Sort sort,
                                   int page, int pageSize) {
        // A volume and a letter arrive in the same `size` parameter,
        // because to a shopper they are one question -- "which size" -- and
        // the catalogue answers it on whichever axis the product is on.
        // Read as a volume first: "30ml" would otherwise be upper-cased to
        // "30ML" and offered to the letter ladder, which has no such rung,
        // and the page would come back empty.
        Integer volumeMl = normalizeVolumeMl(size);
        String alpha = volumeMl == null ? normalizeAlpha(size) : null;
        // Fetch one extra row to answer hasMore without a second count query,
        // which on a listing is pure waste.
        List<Dtos.ProductCard> rows = repository.list(
                country, query, brand, sizeEu, alpha, volumeMl, kinds,
                includeUnclassified,
                category, gender, normalizeConcentration(concentration),
                sort, pageSize + 1, page * pageSize);
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = rows.subList(0, pageSize);
        }
        // Whichever axis actually filtered, as the client should echo it. The
        // EU number wins when both are present, exactly as the repository
        // resolves them.
        String applied = sizeEu != null ? trimSize(sizeEu)
                : volumeMl != null ? volumeMl + "ml"
                : alpha;
        return new Dtos.ProductPage(rows, page, pageSize, hasMore, applied);
    }

    /**
     * A letter size as the catalogue spells it, or null.
     *
     * <p>Upper-cased because {@code offer_variant.size_alpha} is canonical
     * and a shopper's URL is not: "xl" in an address bar is the same request
     * as "XL". Nothing else is corrected -- an unknown label matches no row
     * and returns an empty page, which is the truthful answer to a size we
     * do not carry.
     */
    /**
     * Brands the given scope actually has products in.
     *
     * <p>The sidebar asks this instead of rendering its own fixed list, so a
     * shopper browsing Опрема is not offered Ajmal and one browsing
     * Парфеми is not offered Hoka.
     */
    public List<Dtos.BrandFacet> brands(String query, String[] kinds,
                                        boolean includeUnclassified,
                                        String category, String gender,
                                        String concentration, int limit) {
        return repository.brandFacets(country, query, kinds,
                includeUnclassified, category, gender,
                normalizeConcentration(concentration), limit);
    }

    /**
     * Upper-cases a concentration, because the column is canonical.
     *
     * <p>Passed through unknown rather than corrected, the same refusal
     * {@link #normalizeAlpha} makes: an unrecognised strength matches no row
     * and an empty page is the truthful answer to a question we cannot
     * answer. Guessing a near match would price a shopper's basket in a
     * strength they did not ask for.
     */
    static String normalizeConcentration(String concentration) {
        if (concentration == null || concentration.isBlank()) {
            return null;
        }
        // A comma-separated list, because one menu entry names two
        // strengths: the shops' Парфеми shelf holds both PARFUM and
        // EXTRAIT, and a shopper reading that word does not distinguish
        // them. Split, trimmed and rejoined so "parfum, extrait" and
        // "PARFUM,EXTRAIT" reach the query identically.
        var parts = new java.util.ArrayList<String>();
        for (String part : concentration.split(",")) {
            String one = part.trim().toUpperCase(java.util.Locale.ROOT);
            if (!one.isEmpty() && !parts.contains(one)) {
                parts.add(one);
            }
        }
        return parts.isEmpty() ? null : String.join(",", parts);
    }

    /**
     * A bottle volume in millilitres, or null when this is not one.
     *
     * <p>Shares the `size` parameter with letters, so it has to be strict:
     * anything that is not a bare number followed by `ml` falls through to
     * the letter ladder. The bound mirrors `mkagg.sizing`, which refuses a
     * four-digit volume for the same reason -- a label that reads that way
     * is more likely a weight or a code.
     */
    static Integer normalizeVolumeMl(String size) {
        if (size == null) {
            return null;
        }
        var matcher = VOLUME.matcher(size.trim());
        if (!matcher.matches()) {
            return null;
        }
        int ml = Integer.parseInt(matcher.group(1));
        return ml >= 1 && ml <= 2000 ? ml : null;
    }

    private static final java.util.regex.Pattern VOLUME =
            java.util.regex.Pattern.compile("(\\d{1,4})\\s*ml",
                    java.util.regex.Pattern.CASE_INSENSITIVE);

    static String normalizeAlpha(String size) {
        if (size == null || size.isBlank()) {
            return null;
        }
        return size.trim().toUpperCase(java.util.Locale.ROOT);
    }

    public Optional<Dtos.ProductDetail> detail(String slug, Double sizeEu) {
        return detail(slug, sizeEu, null);
    }

    /**
     * One product, optionally narrowed to a single size.
     *
     * <p>{@code size} is the non-EU axis: a letter for adult garments, an age
     * band or a height for kids'. It is matched against the same string the
     * page shows -- {@code sizeAlpha} when the variant is on the letter
     * ladder, the shop's own label otherwise -- so a chip a shopper can see
     * is a chip that can filter. Matching {@code sizeLabel} alone would miss
     * the adidas spellings the parser folds in ({@code LG}, {@code MD},
     * {@code 2XL}), and matching {@code sizeAlpha} alone would exclude every
     * kids' size, which has no letter at all.
     */
    public Optional<Dtos.ProductDetail> detail(String slug, Double sizeEu,
                                               String size) {
        String alpha = normalizeAlpha(size);
        return repository.findProductBySlug(slug).map(product -> {
            List<CatalogRepository.OfferVariantRow> rows = repository.findOffers(product.id());
            List<Dtos.Offer> offers = groupIntoOffers(rows, sizeEu, alpha);
            return new Dtos.ProductDetail(
                    product.slug(),
                    product.name(),
                    product.brand(),
                    product.colorway(),
                    product.gender(),
                    product.mpn(),
                    product.imageUrl(),
                    product.categoryKind(),
                    product.category(),
                    product.categoryMk(),
                    Dtos.Money.of(product.minPriceMinor(), product.currency(), product.minorUnit()),
                    Dtos.Money.of(product.maxPriceMinor(), product.currency(), product.minorUnit()),
                    product.offerCount(),
                    product.merchantCount(),
                    product.availableSizesEu(),
                    product.availableSizes(),
                    product.updatedAt(),
                    PRICE_DISCLAIMER,
                    offers);
        });
    }

    /**
     * Whether a variant is the size a shopper asked for, on the non-EU axis.
     *
     * <p>Compared case-insensitively against the letter first and the shop's
     * own label second, which is the same pair the page renders. The label
     * side is what carries kids' sizes: "9-10 год." is not on any ladder and
     * has no canonical form to normalise to.
     */
    static boolean sameLabel(CatalogRepository.OfferVariantRow row,
                                     String wanted) {
        if (row.sizeAlpha() != null
                && row.sizeAlpha().equalsIgnoreCase(wanted)) {
            return true;
        }
        return row.sizeLabel() != null
                && row.sizeLabel().equalsIgnoreCase(wanted);
    }

    /**
     * Group variant rows into one entry per shop, cheapest total first.
     *
     * <p>The SQL already ordered by each offer's cheapest total, so insertion
     * order into a {@link LinkedHashMap} preserves it.
     */
    List<Dtos.Offer> groupIntoOffers(List<CatalogRepository.OfferVariantRow> rows,
                                     Double sizeFilter) {
        return groupIntoOffers(rows, sizeFilter, null);
    }

    List<Dtos.Offer> groupIntoOffers(List<CatalogRepository.OfferVariantRow> rows,
                                     Double sizeFilter, String labelFilter) {
        Map<Long, List<CatalogRepository.OfferVariantRow>> byOffer = new LinkedHashMap<>();
        for (var row : rows) {
            if (sizeFilter != null && !sameSize(row.sizeEu(), sizeFilter)) {
                continue;
            }
            if (sizeFilter == null && labelFilter != null
                    && !sameLabel(row, labelFilter)) {
                continue;
            }
            byOffer.computeIfAbsent(row.offerId(), key -> new ArrayList<>()).add(row);
        }

        // Which shops in *this* list share an operator. Only worth badging
        // when both are actually on the page.
        Set<String> present = byOffer.values().stream()
                .map(group -> group.get(0).merchantSlug())
                .collect(java.util.stream.Collectors.toSet());

        List<Dtos.Offer> offers = new ArrayList<>(byOffer.size());
        for (var group : byOffer.values()) {
            var head = group.get(0);
            List<Dtos.OfferVariant> variants = new ArrayList<>(group.size());
            // Boxed and left null when nothing in the offer has a price:
            // a sold-out shop that publishes none must not be reported as
            // costing zero, and must not claim a "from" price it has not got.
            Long fromPrice = null;
            Long fromTotal = null;

            for (var row : group) {
                variants.add(new Dtos.OfferVariant(
                        row.variantId(),
                        row.sizeLabel(),
                        row.sizeEu(),
                        row.sizeAlpha(),
                        row.sizeAlphaMax(),
                        row.sizeSystem(),
                        Dtos.Money.of(row.priceMinor(), row.currency(), row.minorUnit()),
                        Dtos.Money.of(row.listPriceMinor(), row.currency(), row.minorUnit()),
                        Dtos.Money.of(row.shippingMinor(), row.currency(), row.minorUnit()),
                        Dtos.Money.of(row.totalMinor(), row.currency(), row.minorUnit()),
                        // publishesStock=false forces NOT_PUBLISHED even if a
                        // stale true leaked into the column: the merchant flag
                        // is the authority on what we may claim.
                        Dtos.stockState(row.publishesStock() ? row.inStock() : null,
                                row.checkedAt(), staleAfter),
                        row.publishesStock() ? row.stockQty() : null,
                        row.checkedAt(),
                        "/out/" + row.variantId()));
                if (row.priceMinor() != null) {
                    fromPrice = fromPrice == null ? row.priceMinor()
                            : Math.min(fromPrice, row.priceMinor());
                }
                if (row.totalMinor() != null) {
                    fromTotal = fromTotal == null ? row.totalMinor()
                            : Math.min(fromTotal, row.totalMinor());
                }
            }

            String related = head.relatedMerchantSlug();
            offers.add(new Dtos.Offer(
                    head.offerId(),
                    head.merchantSlug(),
                    head.merchantName(),
                    head.rating(),
                    head.reviewCount(),
                    head.publishesStock(),
                    deliveryEstimate(head.deliveryDaysMin(), head.deliveryDaysMax()),
                    Dtos.Money.of(fromPrice, head.currency(), head.minorUnit()),
                    Dtos.Money.of(fromTotal, head.currency(), head.minorUnit()),
                    (related != null && present.contains(related)) ? related : null,
                    variants));
        }

        // Sort by total here unconditionally, even though the SQL already
        // ordered by it.
        //
        // The first version only re-sorted when a size filter was applied and
        // otherwise trusted the query's ORDER BY. A unit test feeding rows in
        // sticker-price order then produced a list where a 2 863 + 400 postage
        // offer outranked a 3 000 delivered free -- the exact mistake this
        // page exists to prevent. The ordering of the offer list is the single
        // most important behaviour in the product, so it should not depend on
        // an upstream invariant that nothing in this class enforces. Sorting a
        // handful of offers costs nothing.
        offers.sort(java.util.Comparator.comparingLong(
                offer -> offer.fromTotalPrice() == null
                        ? Long.MAX_VALUE : offer.fromTotalPrice().amountMinor()));
        return offers;
    }

    /** Size equality with a tolerance, since 44.667 is stored rounded. */
    private static boolean sameSize(Double stored, double requested) {
        return stored != null && Math.abs(stored - requested) < 0.005;
    }

    private static String deliveryEstimate(Integer min, Integer max) {
        if (min == null && max == null) {
            return null;
        }
        if (min != null && max != null && !min.equals(max)) {
            return min + "-" + max + " days";
        }
        int days = min != null ? min : max;
        return days + (days == 1 ? " day" : " days");
    }

    private static String trimSize(double size) {
        return size == Math.floor(size)
                ? String.valueOf((long) size)
                : String.valueOf(size);
    }
}
