package mk.priceradar.api.common;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "price-radar")
public record PriceRadarProperties(
        String country,
        Outbound outbound,
        Freshness freshness) {

    public record Outbound(String ipHashSalt, boolean trustForwardedFor) {
    }

    public record Freshness(int staleAfterMinutes) {
    }

    public PriceRadarProperties {
        if (country == null || country.isBlank()) {
            country = "MK";
        }
        if (outbound == null) {
            outbound = new Outbound("dev-only-change-me", false);
        }
        if (freshness == null) {
            freshness = new Freshness(180);
        }
    }
}
