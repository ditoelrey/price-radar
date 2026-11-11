package mk.priceradar.api.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

import mk.priceradar.api.common.PriceRadarProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

/**
 * Assembly rules for the detail page.
 *
 * <p>The numbers below are the real ones measured during ingestion, so a
 * failure here is legible: the Stan Smith genuinely costs 4 072 MKD at Buzz
 * (one size in stock) and 6 799 at both Sport-M and Sizeer.
 */
class CatalogServiceTest {

    private static final Instant FRESH = Instant.now().minusSeconds(60);
    private static final Instant OLD = Instant.now().minus(Duration.ofHours(9));

    private CatalogService service() {
        return new CatalogService(
                Mockito.mock(CatalogRepository.class),
                new PriceRadarProperties("MK",
                        new PriceRadarProperties.Outbound("s", false),
                        new PriceRadarProperties.Freshness(180)));
    }

    private CatalogRepository.OfferVariantRow row(
            long offerId, String merchantSlug, String merchantName,
            long variantId, String sizeLabel, Double sizeEu,
            long price, long shipping, Boolean inStock, boolean publishesStock,
            String relatedSlug, Instant checkedAt, long offerFromTotal) {
        return new CatalogRepository.OfferVariantRow(
                offerId, merchantSlug, merchantName, 4.0, 10, publishesStock,
                2, 4, relatedSlug, variantId, sizeLabel, sizeEu,
                price, null, shipping, price + shipping, price, offerFromTotal,
                "MKD", inStock, inStock == Boolean.TRUE ? 3 : null,
                checkedAt, 0);
    }

    // ------------------------------------------------------------------
    // Grouping and ordering
    // ------------------------------------------------------------------

    @Test
    @DisplayName("variants group into one entry per shop, cheapest total first")
    void groupsAndOrders() {
        var rows = List.of(
                row(1, "buzz", "Buzz Sneakers", 11, "45 1/3", 45.333, 4072, 0,
                        true, true, null, FRESH, 4072),
                row(2, "sportm", "Sport-M", 21, "44", 44.0, 6799, 0,
                        true, true, "sizeer", FRESH, 6799),
                row(2, "sportm", "Sport-M", 22, "46", 46.0, 6799, 0,
                        true, true, "sizeer", FRESH, 6799));

        var offers = service().groupIntoOffers(rows, null);

        assertThat(offers).hasSize(2);
        assertThat(offers.get(0).merchantSlug()).isEqualTo("buzz");
        assertThat(offers.get(0).fromTotalPrice().amountMinor()).isEqualTo(4072);
        assertThat(offers.get(1).merchantSlug()).isEqualTo("sportm");
        assertThat(offers.get(1).variants()).hasSize(2);
    }

    @Test
    @DisplayName("ordering is by TOTAL price, so postage cannot hide a dearer offer")
    void ordersByTotalNotSticker() {
        var rows = List.of(
                // Cheaper sticker, expensive postage.
                row(1, "a", "Shop A", 11, "44", 44.0, 2863, 400, true, true,
                        null, FRESH, 3263),
                // Dearer sticker, free delivery -- genuinely the better buy.
                row(2, "b", "Shop B", 21, "44", 44.0, 3000, 0, true, true,
                        null, FRESH, 3000));

        var offers = service().groupIntoOffers(rows, null);

        assertThat(offers.get(0).merchantSlug()).isEqualTo("b");
        assertThat(offers.get(0).fromTotalPrice().amountMinor()).isEqualTo(3000);
        assertThat(offers.get(1).fromTotalPrice().amountMinor()).isEqualTo(3263);
    }

    @Test
    @DisplayName("a size filter can change which shop is cheapest")
    void sizeFilterReorders() {
        var rows = List.of(
                // Buzz is cheapest overall but has only 45 1/3.
                row(1, "buzz", "Buzz Sneakers", 11, "45 1/3", 45.333, 4072, 0,
                        true, true, null, FRESH, 4072),
                row(2, "sportm", "Sport-M", 21, "44", 44.0, 6799, 0,
                        true, true, null, FRESH, 6799));

        var all = service().groupIntoOffers(rows, null);
        var sized = service().groupIntoOffers(rows, 44.0);

        assertThat(all).hasSize(2);
        // Ask for EU 44 and the 4 072 headline simply is not available.
        assertThat(sized).hasSize(1);
        assertThat(sized.get(0).merchantSlug()).isEqualTo("sportm");
        assertThat(sized.get(0).fromTotalPrice().amountMinor()).isEqualTo(6799);
    }

    @Test
    @DisplayName("fractional sizes match despite rounding")
    void fractionalSizeTolerance() {
        var rows = List.of(row(1, "buzz", "Buzz", 11, "44 2/3", 44.667,
                4072, 0, true, true, null, FRESH, 4072));

        assertThat(service().groupIntoOffers(rows, 44.667)).hasSize(1);
        assertThat(service().groupIntoOffers(rows, 44.0)).isEmpty();
    }

    @Test
    @DisplayName("every variant exposes our own /out URL, never the shop's")
    void outUrlIsOurs() {
        var rows = List.of(row(1, "buzz", "Buzz", 11, "44", 44.0, 4072, 0,
                true, true, null, FRESH, 4072));

        var variant = service().groupIntoOffers(rows, null).get(0).variants().get(0);

        // Outbound clicks must pass through us or they are not billable.
        assertThat(variant.outUrl()).isEqualTo("/out/11");
    }

    // ------------------------------------------------------------------
    // Honest stock
    // ------------------------------------------------------------------

    @Test
    @DisplayName("a shop that publishes no stock yields NOT_PUBLISHED, never SOLD_OUT")
    void sizeerStockIsUnknown() {
        var rows = List.of(row(1, "sizeer", "Sizeer", 11, "44", 44.0, 6799, 0,
                null, false, "sportm", FRESH, 6799));

        var variant = service().groupIntoOffers(rows, null).get(0).variants().get(0);

        assertThat(variant.stock()).isEqualTo(Dtos.StockState.NOT_PUBLISHED);
        assertThat(variant.stockQty()).isNull();
    }

    @Test
    @DisplayName("publishesStock=false overrides a stale true in the column")
    void merchantFlagIsTheAuthority() {
        var rows = List.of(row(1, "sizeer", "Sizeer", 11, "44", 44.0, 6799, 0,
                true, false, null, FRESH, 6799));

        var variant = service().groupIntoOffers(rows, null).get(0).variants().get(0);

        // The merchant flag decides what we are allowed to claim.
        assertThat(variant.stock()).isEqualTo(Dtos.StockState.NOT_PUBLISHED);
    }

    @Test
    @DisplayName("an in-stock claim older than the window softens to STALE")
    void positiveClaimsGoStale() {
        var rows = List.of(row(1, "buzz", "Buzz", 11, "44", 44.0, 4072, 0,
                true, true, null, OLD, 4072));

        assertThat(service().groupIntoOffers(rows, null).get(0)
                .variants().get(0).stock())
                .isEqualTo(Dtos.StockState.STALE);
    }

    @Test
    @DisplayName("a sold-out claim does not go stale")
    void negativeClaimsDoNot() {
        var rows = List.of(row(1, "buzz", "Buzz", 11, "44", 44.0, 4072, 0,
                false, true, null, OLD, 4072));

        // Being wrong about "sold out" costs a click we might have had.
        // Being wrong about "in stock" costs a wasted trip and the trust.
        assertThat(service().groupIntoOffers(rows, null).get(0)
                .variants().get(0).stock())
                .isEqualTo(Dtos.StockState.SOLD_OUT);
    }

    @Test
    @DisplayName("stockState is defensible for each input")
    void stockStateMatrix() {
        var window = Duration.ofMinutes(180);
        assertThat(Dtos.stockState(null, FRESH, window)).isEqualTo(Dtos.StockState.NOT_PUBLISHED);
        assertThat(Dtos.stockState(true, FRESH, window)).isEqualTo(Dtos.StockState.IN_STOCK);
        assertThat(Dtos.stockState(true, OLD, window)).isEqualTo(Dtos.StockState.STALE);
        assertThat(Dtos.stockState(false, OLD, window)).isEqualTo(Dtos.StockState.SOLD_OUT);
        assertThat(Dtos.stockState(true, null, window)).isEqualTo(Dtos.StockState.IN_STOCK);
    }

    // ------------------------------------------------------------------
    // Linked operators
    // ------------------------------------------------------------------

    @Test
    @DisplayName("shops sharing an operator are badged when both are listed")
    void badgesLinkedOperators() {
        var rows = List.of(
                row(1, "sportm", "Sport-M", 11, "44", 44.0, 6799, 0, true, true,
                        "sizeer", FRESH, 6799),
                row(2, "sizeer", "Sizeer", 21, "44", 44.0, 6799, 0, null, false,
                        "sportm", FRESH, 6799));

        var offers = service().groupIntoOffers(rows, null);

        // Identical platform, host IP and price: unlabelled, the offer list
        // just looks padded.
        assertThat(offers).allMatch(offer -> offer.sameOperatorAs() != null);
    }

    @Test
    @DisplayName("no badge when the linked shop is not on this page")
    void noBadgeWhenAlone() {
        var rows = List.of(row(1, "sportm", "Sport-M", 11, "44", 44.0, 6799, 0,
                true, true, "sizeer", FRESH, 6799));

        assertThat(service().groupIntoOffers(rows, null).get(0).sameOperatorAs())
                .isNull();
    }

    // ------------------------------------------------------------------
    // Money
    // ------------------------------------------------------------------

    @Test
    @DisplayName("money carries its exponent, and MKD has none")
    void moneyIsIntegerMinorUnits() {
        var money = Dtos.Money.of(2863L, "MKD", 0);

        assertThat(money.amountMinor()).isEqualTo(2863L);
        assertThat(money.minorUnit()).isZero();
        assertThat(money.currency()).isEqualTo("MKD");
    }

    @Test
    @DisplayName("a null amount yields no Money rather than a zero")
    void nullMoney() {
        // Zero is a price; absent is not, and conflating them would advertise
        // free shoes.
        assertThat(Dtos.Money.of(null, "MKD", 0)).isNull();
    }

    @Test
    @DisplayName("the price disclaimer is shown with every detail response")
    void disclaimerExists() {
        assertThat(CatalogService.PRICE_DISCLAIMER)
                .contains("reported by the shops")
                .contains("last checked");
    }
}
