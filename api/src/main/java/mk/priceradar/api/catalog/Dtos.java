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
    /**
     * One brand the current listing scope actually has products in.
     *
     * <p>Exists so the storefront can stop rendering a fixed list of sneaker
     * brands on every vertical. {@code productCount} is what the listing
     * would return for that brand under the same filters, so the facet and
     * the page it leads to cannot disagree.
     */
    public record BrandFacet(String slug, String name, int productCount) {
    }

    /**
     * One shop that actually sells inside the current listing scope.
     *
     * <p>Same reason as {@link BrandFacet}: the sidebar used to name six
     * sneaker shops on every listing, so a shopper on Машки парфеми was
     * told the site compares Sport Vision and Sizeer -- which sell no
     * perfume -- and was not told about the two perfumeries that do.
     */
    /**
     * One option of one filter group, with the number beside it.
     *
     * <p>The shape every group shares, because the controls do: a checkbox, a
     * Macedonian label and a count that says what the page would hold if it
     * were ticked. {@code value} is what travels in the URL -- a slug, a
     * gender, a bare size -- and {@code label} is what a shopper reads.
     *
     * <p>Replaces the per-group records for the new sidebar.
     * {@link BrandFacet} and {@link MerchantFacet} are the same thing under
     * older names, kept while {@code /brands} and {@code /merchants} are
     * still served.
     */
    public record FacetOption(String value, String label, int productCount) {
    }

    /**
     * One size option, and which ladder it is a rung of.
     *
     * <p>{@code axis} is {@code eu}, {@code alpha} or {@code ml}. The three
     * share a control because to a shopper they are one question, and they
     * cannot share a list because no product is on two ladders -- which axis
     * comes back with options is how the sidebar knows which rail to draw.
     */
    public record SizeOption(String axis, String value, int productCount) {
    }

    /**
     * Every control on the listing page, answered in one call.
     *
     * <p>Five queries rather than one, because each group's options are
     * counted with every <em>other</em> group's filters applied and its own
     * left out. That is what makes a multi-select usable: the number beside
     * Nike has to mean "this many more if you add Nike", not "this many,
     * given you already picked adidas".
     */
    public record Facets(List<FacetOption> genders,
                         List<FacetOption> categories,
                         List<FacetOption> concentrations,
                         List<SizeOption> sizes,
                         List<FacetOption> brands,
                         List<FacetOption> shops,
                         List<FacetOption> prices) {
    }

    public record MerchantFacet(String slug, String name, int productCount) {
    }

    public record ProductCard(
            String slug,
            String name,
            String brand,
            String colorway,
            String imageUrl,
            String mpn,
            /**
             * Canonical category leaf, English, or null when nothing has
             * said yet. Null is a real answer: 489 products reached the
             * catalogue through a footwear facet with a title that named no
             * category, and a guess is how a pack of socks once got filed
             * under sneakers.
             */
            String category,
            /** The same category in Macedonian, for display. */
            String categoryMk,
            /**
             * {@code men}, {@code women}, {@code kids}, {@code unisex}, or
             * null when no facet or title said. {@code unisex} is a finding
             * -- the article is listed in both adult departments -- not a
             * fallback for silence.
             */
            String gender,
            Money fromPrice,
            /**
             * The dearest variant, when a range means anything, else null.
             *
             * <p>Fragrances are the reason: one bottle is sold in 30ml, 50ml
             * and 100ml at three prices, and a card showing only the
             * cheapest understates what the shopper will pay for the size
             * they want. Null when there is no range -- a single-size
             * product, or a size-filtered page, where the summary's maximum
             * covers sizes the shopper has filtered out.
             */
            Money toPrice,
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
            /**
             * Letter sizes a shopper can buy, smallest first.
             *
             * <p>Separate from {@code availableSizesEu} rather than merged
             * into one list of strings: they are different axes and nothing
             * carries both. A shoe fills the first and a garment the second,
             * so a client can tell which rail to draw by seeing which list
             * has anything in it.
             */
            List<String> availableSizes,
            /**
             * Bottle volumes in millilitres a shopper can buy, smallest
             * first.
             *
             * <p>A third axis beside the EU numbers and the letters, and
             * separate for the same reason: nothing carries two of them. A
             * shoe fills the first, a garment the second, a fragrance this
             * one, so a client knows which rail to draw by seeing which
             * list is non-empty.
             */
            List<Integer> availableVolumesMl,
            /**
             * Normalised fragrance strength -- EDP, EDT, EDC, PARFUM,
             * EXTRAIT, COLOGNE -- or null outside the fragrance vertical.
             *
             * <p>Part of the product's identity, not a facet of it:
             * "Valentino Donna" in Eau de Parfum and in Eau de Toilette are
             * different liquids at different prices, so the card has to be
             * able to say which one it is showing.
             */
            String concentration,
            /**
             * Best advertised saving on this product, as whole percent, or
             * null when no shop is discounting it.
             *
             * <p>Null rather than 0 on purpose: the card draws a badge when
             * this is present, and zero would put a "save nothing" badge on
             * most of the catalogue.
             */
            Integer discountPct,
            Instant updatedAt) {
    }

    /** A page of listing rows. */
    public record ProductPage(
            List<ProductCard> items,
            int page,
            int pageSize,
            boolean hasMore,
            /**
             * Every product the filters match, not just this page's worth.
             *
             * <p>Added so the storefront can number its pages and offer the
             * last one. `hasMore` answers "is there another page" for a
             * next/previous pair and nothing more -- it cannot say "of 50".
             */
            int total,
            String appliedSizeFilter) {
    }

    /** One size at one shop: the row a shopper actually buys from. */
    public record OfferVariant(
            long id,
            String sizeLabel,
            Double sizeEu,
            /**
             * The canonical letter, XXS to 5XL, or null when this variant is
             * not on that ladder. Distinct from {@code sizeLabel}, which is
             * whatever the shop printed: Sport Vision renders its entire size
             * dictionary into every garment page, so the raw labels include
             * 2XLS, M-T and YXS alongside the real ones.
             */
            String sizeAlpha,
            /**
             * The upper letter when the shop's label names a span ("M/L"),
             * with {@code sizeAlpha} the lower. NULL for a single letter.
             * The storefront shows the shop's own label for a span rather
             * than either end of it.
             */
            String sizeAlphaMax,
            /**
             * Which ladder this size is on: {@code alpha}, {@code age},
             * {@code height}, {@code numeric}, or null.
             *
             * <p>{@code numeric} is the sizing parser's catch-all, not a
             * system: every normalised column is empty on those rows. For
             * apparel it is almost entirely Sport Vision's template
             * dictionary -- NS, 1X, YMD, 2XLT -- which the shop renders into
             * every garment page and sells in none of: 2 479 NS variants, 0
             * of them in stock. A client showing sizes should skip them.
             */
            String sizeSystem,
            /**
             * Foot length in centimetres, as the shop publishes it.
             *
             * The second scale a shoe can be read in, and scraped rather
             * than converted: Sport Vision, Sport Reality and Buzz each put
             * it on the size widget. Null where a shop does not, which is
             * why the storefront only offers the CM tab when every rung of
             * a product has one -- a grid with holes in it is worse than
             * one scale.
             */
            Double sizeCm,
            /**
             * A child's height in centimetres.
             *
             * The shop's own figure when it publishes one, and otherwise the
             * height the age band maps to through `kids_size_chart`. Null
             * for a band the chart does not cover -- 4-5 years has no row,
             * and the storefront hides the tab rather than guess.
             */
            Integer sizeHeightCm,
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
            /**
             * The brand's own slug, as {@code ?brand=} wants it.
             *
             * <p>Served rather than derived, because the breadcrumb used to
             * build it from the display name -- lower-case and spaces to
             * hyphens. That is wrong for 18 brands the catalogue carries,
             * most of them perfumeries: "Dolce & Gabbana" became
             * {@code dolce-&-gabbana} and not {@code dolce-gabbana},
             * "Lancôme" kept its circumflex, "Joop!" its exclamation mark.
             * A slug is a fact the database holds; guessing it on the
             * client produced a dead link on every one of them.
             */
            String brandSlug,
            String colorway,
            String gender,
            String mpn,
            String imageUrl,
            /** {@code footwear}, {@code apparel}, ... or null if unclassified. */
            String categoryKind,
            /** Canonical leaf slug, or null. */
            String category,
            /** The same leaf in Macedonian, for the breadcrumb. */
            String categoryMk,
            Money lowestPrice,
            Money highestPrice,
            int offerCount,
            int merchantCount,
            List<Double> availableSizesEu,
            /** Letter sizes, smallest first; the garment counterpart. */
            List<String> availableSizes,
            /**
             * When any shop was last asked about this product -- the newest
             * {@code offer_variant.last_checked_at} among its active
             * offers, not when we last recomputed its summary row.
             *
             * <p>The distinction is visible on the page: it previously
             * showed today's date above a list of offers each labelled
             * "checked 4 days ago".
             */
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
