package mk.priceradar.api.catalog;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * The API's read model.
 *
 * <p>Every money value is an integer in minor units plus its currency's
 * exponent, never a decimal. MKD is configured with {@code minorUnit = 0} by
 * the MK shops, so 2863 means 2 863 denars, not 28.63. Formatting is the
 * client's job; getting the arithmetic right is ours, and float money breaks
 * the lowest-price sort the moment 4499.9999 appears.
 */
public final class Dtos {

    private Dtos() {
    }

    /** Integer money, with the exponent the client needs to format it. */
    public record Money(long amountMinor, String currency, int minorUnit) {

        public static Money of(Long amountMinor, String currency, int minorUnit) {
            return amountMinor == null ? null
                    : new Money(amountMinor, currency == null ? "MKD" : currency, minorUnit);
        }

        public Money plus(Money other) {
            if (other == null) {
                return this;
            }
            return new Money(amountMinor + other.amountMinor(), currency, minorUnit);
        }
    }

    /**
     * What we can honestly say about a size's availability.
     *
     * <p>{@link #NOT_PUBLISHED} exists because sizeer.com.mk returns its size
     * list with no stock figures at all. That is not "out of stock" and it is
     * not "in stock" -- claiming either would be a statement we cannot
     * support, so the UI must render it as "listed".
     */
    public enum StockState {
        IN_STOCK,
        SOLD_OUT,
        /** The shop does not publish availability for this size. */
        NOT_PUBLISHED,
        /** Last check is older than the freshness window; soften the claim. */
        STALE
    }

    /** One row in a search or category listing. */
    public record ProductCard(
            String slug,
            String name,
            String brand,
            String colorway,
            String imageUrl,
            String mpn,
            Money fromPrice,
            int offerCount,
            int merchantCount,
            /**
             * True when {@code fromPrice} was computed for the requested size
             * rather than taken from the product's overall minimum. The
             * distinction matters: the cheapest offer for a product is often
             * not available in the size the shopper asked for.
             */
            boolean fromPriceIsSizeSpecific,
            List<Double> availableSizesEu,
            Instant updatedAt) {
    }

    /** A page of listing rows. */
    public record ProductPage(
            List<ProductCard> items,
            int page,
            int pageSize,
            boolean hasMore,
            String appliedSizeFilter) {
    }

    /** One size at one shop: the row a shopper actually buys from. */
    public record OfferVariant(
            long id,
            String sizeLabel,
            Double sizeEu,
            Money price,
            Money listPrice,
            Money shipping,
            Money totalPrice,
            StockState stock,
            Integer stockQty,
            Instant checkedAt,
            /** Where to send the shopper. Always our own endpoint. */
            String outUrl) {
    }

    /** One shop's listing of a product, with every size it carries. */
    public record Offer(
            long id,
            String merchantSlug,
            String merchantName,
            Double merchantRating,
            int merchantReviewCount,
            boolean publishesStock,
            String deliveryEstimate,
            Money fromPrice,
            Money fromTotalPrice,
            /**
             * Set when this shop shares an operator with another in the same
             * list. sizeer.com.mk and sport-m.com.mk run on one platform, one
             * host IP and quote identical prices; showing both unlabelled
             * makes the offer list look padded.
             */
            String sameOperatorAs,
            List<OfferVariant> variants) {
    }

    /** The detail page: one product, every offer, cheapest total first. */
    public record ProductDetail(
            String slug,
            String name,
            String brand,
            String colorway,
            String gender,
            String mpn,
            String imageUrl,
            Money lowestPrice,
            Money highestPrice,
            int offerCount,
            int merchantCount,
            List<Double> availableSizesEu,
            Instant updatedAt,
            /** Honest-UI copy: shown next to the prices, not buried. */
            String priceDisclaimer,
            List<Offer> offers) {
    }

    /** Derive a stock state we can defend, given how old the check is. */
    public static StockState stockState(Boolean inStock, Instant checkedAt,
                                        Duration staleAfter) {
        if (inStock == null) {
            return StockState.NOT_PUBLISHED;
        }
        if (!inStock) {
            // A sold-out claim does not go stale in a harmful direction: the
            // worst case is a shopper not clicking something they could have
            // bought. Only positive claims need softening.
            return StockState.SOLD_OUT;
        }
        if (checkedAt != null && Duration.between(checkedAt, Instant.now()).compareTo(staleAfter) > 0) {
            return StockState.STALE;
        }
        return StockState.IN_STOCK;
    }
}
