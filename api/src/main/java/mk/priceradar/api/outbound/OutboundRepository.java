package mk.priceradar.api.outbound;

import java.util.Optional;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** Reads the redirect target and appends to the click ledger. */
@Repository
public class OutboundRepository {

    private final JdbcClient db;

    public OutboundRepository(JdbcClient db) {
        this.db = db;
    }

    /**
     * Everything the redirect needs, in one round trip.
     *
     * <p>Deliberately not filtered on {@code in_stock}: a shopper who clicks
     * an offer we believe is sold out should still be sent to the shop, which
     * may well know better than our last check does. Nor on
     * {@code m.is_active}: a merchant can be deactivated between the page
     * render and the click, and refusing the redirect at that point would
     * lose a click we have already shown.
     */
    private static final String TARGET = """
            SELECT ov.id          AS variant_id,
                   mo.id          AS offer_id,
                   mo.product_id  AS product_id,
                   m.id           AS merchant_id,
                   m.country_code AS country_code,
                   mo.product_url AS product_url,
                   m.affiliate_url_template AS affiliate_template,
                   ov.price_minor AS price_minor,
                   ov.currency_code AS currency_code
              FROM offer_variant ov
              JOIN merchant_offer mo ON mo.id = ov.offer_id
              JOIN merchant m        ON m.id = mo.merchant_id
             WHERE ov.id = :variantId
            """;

    private static final String INSERT_CLICK = """
            INSERT INTO click_event (
                    occurred_at, product_id, offer_id, offer_variant_id,
                    merchant_id, country_code, price_at_click_minor,
                    currency_code, session_id, ip_hash, ua_hash, referer, is_bot)
                 VALUES (now(), :productId, :offerId, :variantId, :merchantId,
                         :country, :priceMinor, :currency, :sessionId, :ipHash,
                         :uaHash, :referer, :isBot)
            """;

    public Optional<ClickTarget> findTarget(long variantId) {
        return db.sql(TARGET).param("variantId", variantId)
                .query((rs, rowNum) -> new ClickTarget(
                        rs.getLong("variant_id"),
                        rs.getLong("offer_id"),
                        (Long) rs.getObject("product_id"),
                        rs.getLong("merchant_id"),
                        rs.getString("country_code"),
                        rs.getString("product_url"),
                        rs.getString("affiliate_template"),
                        rs.getLong("price_minor"),
                        rs.getString("currency_code")))
                .optional();
    }

    public void recordClick(ClickTarget target, ClickContext context) {
        db.sql(INSERT_CLICK)
                .param("productId", target.productId())
                .param("offerId", target.offerId())
                .param("variantId", target.variantId())
                .param("merchantId", target.merchantId())
                .param("country", target.countryCode())
                .param("priceMinor", target.priceMinor())
                .param("currency", target.currency())
                .param("sessionId", context.sessionId())
                .param("ipHash", context.ipHash())
                .param("uaHash", context.uaHash())
                .param("referer", context.referer())
                .param("isBot", context.bot())
                .update();
    }

    public record ClickTarget(long variantId, long offerId, Long productId,
                              long merchantId, String countryCode,
                              String productUrl, String affiliateTemplate,
                              long priceMinor, String currency) {

        /**
         * Where to send the shopper.
         *
         * <p>When a merchant has an affiliate template, the deep link goes
         * through it so the click is attributable; otherwise straight to the
         * shop's own page.
         */
        public String redirectUrl() {
            if (affiliateTemplate == null || affiliateTemplate.isBlank()) {
                return productUrl;
            }
            return affiliateTemplate
                    .replace("{url}", java.net.URLEncoder.encode(
                            productUrl, java.nio.charset.StandardCharsets.UTF_8))
                    .replace("{rawUrl}", productUrl)
                    .replace("{variantId}", Long.toString(variantId));
        }
    }

    public record ClickContext(String sessionId, byte[] ipHash, byte[] uaHash,
                               String referer, boolean bot) {
    }
}
