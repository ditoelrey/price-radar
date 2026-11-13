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
        return search(query, brand, sizeEu, CatalogRepository.FOOTWEAR_KINDS,
                true, CatalogRepository.Sort.CHEAPEST, page, pageSize);
    }

    /**
     * @param kinds category kinds to admit; null admits every category.
     *        Defaults to footwear, because this is a sneaker comparison site
     *        and the ingestion side crawls merchants that also sell socks,
     *        ski leggings and helmets.
     */
    public Dtos.ProductPage search(String query, String brand, Double sizeEu,
                                   String[] kinds, boolean includeUnclassified,
                                   CatalogRepository.Sort sort,
                                   int page, int pageSize) {
        // Fetch one extra row to answer hasMore without a second count query,
        // which on a listing is pure waste.
        List<Dtos.ProductCard> rows = repository.list(
                country, query, brand, sizeEu, kinds, includeUnclassified,
                sort, pageSize + 1, page * pageSize);
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = rows.subList(0, pageSize);
        }
        return new Dtos.ProductPage(rows, page, pageSize, hasMore,
                sizeEu == null ? null : trimSize(sizeEu));
    }

    public Optional<Dtos.ProductDetail> detail(String slug, Double sizeEu) {
        return repository.findProductBySlug(slug).map(product -> {
            List<CatalogRepository.OfferVariantRow> rows = repository.findOffers(product.id());
            List<Dtos.Offer> offers = groupIntoOffers(rows, sizeEu);
            return new Dtos.ProductDetail(
                    product.slug(),
                    product.name(),
                    product.brand(),
                    product.colorway(),
                    product.gender(),
                    product.mpn(),
                    product.imageUrl(),
                    Dtos.Money.of(product.minPriceMinor(), product.currency(), product.minorUnit()),
                    Dtos.Money.of(product.maxPriceMinor(), product.currency(), product.minorUnit()),
                    product.offerCount(),
                    product.merchantCount(),
                    product.availableSizesEu(),
                    product.updatedAt(),
                    PRICE_DISCLAIMER,
                    offers);
        });
    }

    /**
     * Group variant rows into one entry per shop, cheapest total first.
     *
     * <p>The SQL already ordered by each offer's cheapest total, so insertion
     * order into a {@link LinkedHashMap} preserves it.
     */
    List<Dtos.Offer> groupIntoOffers(List<CatalogRepository.OfferVariantRow> rows,
                                     Double sizeFilter) {
        Map<Long, List<CatalogRepository.OfferVariantRow>> byOffer = new LinkedHashMap<>();
        for (var row : rows) {
            if (sizeFilter != null && !sameSize(row.sizeEu(), sizeFilter)) {
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
