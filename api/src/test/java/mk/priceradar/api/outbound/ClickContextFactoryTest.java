package mk.priceradar.api.outbound;

import static org.assertj.core.api.Assertions.assertThat;

import mk.priceradar.api.common.PriceRadarProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockHttpServletRequest;

class ClickContextFactoryTest {

    private ClickContextFactory factory(String salt) {
        return new ClickContextFactory(new PriceRadarProperties(
                "MK", new PriceRadarProperties.Outbound(salt, false),
                new PriceRadarProperties.Freshness(180)));
    }

    private final ClickContextFactory factory = factory("test-salt");

    @Test
    @DisplayName("no raw IP address is ever stored")
    void ipIsHashed() {
        var request = new MockHttpServletRequest("GET", "/out/1");
        request.setRemoteAddr("62.162.58.202");
        request.addHeader("User-Agent", "Mozilla/5.0");

        var context = factory.from(request, "62.162.58.202", "sess-1");

        assertThat(context.ipHash()).isNotNull().hasSize(16);
        // The address must not survive anywhere in the stored bytes.
        assertThat(new String(context.ipHash()))
                .doesNotContain("62.162.58.202");
    }

    @Test
    @DisplayName("the salt changes the hash")
    void saltMatters() {
        byte[] a = factory("salt-a").hash("62.162.58.202");
        byte[] b = factory("salt-b").hash("62.162.58.202");

        // An unsalted hash of an IPv4 address is reversible by brute force
        // over four billion values, so the salt is what makes this defensible.
        assertThat(a).isNotEqualTo(b);
    }

    @Test
    @DisplayName("the same address hashes consistently, so clicks can be deduplicated")
    void hashIsStable() {
        assertThat(factory.hash("62.162.58.202")).isEqualTo(factory.hash("62.162.58.202"));
    }

    @Test
    @DisplayName("null and blank values hash to null rather than to a constant")
    void blankIsNull() {
        assertThat(factory.hash(null)).isNull();
        assertThat(factory.hash("   ")).isNull();
    }

    @ParameterizedTest
    @DisplayName("obvious automated clients are flagged")
    @ValueSource(strings = {
            "MKPriceCompareBot/0.1 (+https://yoursite.mk/bot)",
            "Mozilla/5.0 (compatible; Googlebot/2.1)",
            "curl/8.18.0",
            "python-requests/2.32",
            "Scrapy/2.11",
            "UptimeRobot/2.0",
            "facebookexternalhit/1.1",
    })
    void detectsBots(String userAgent) {
        assertThat(factory.looksAutomated(userAgent)).isTrue();
    }

    @ParameterizedTest
    @DisplayName("real browsers are not flagged")
    @ValueSource(strings = {
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    + "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    + "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    })
    void doesNotFlagBrowsers(String userAgent) {
        assertThat(factory.looksAutomated(userAgent)).isFalse();
    }

    @Test
    @DisplayName("a missing User-Agent counts as automated")
    void missingUserAgentIsSuspect() {
        assertThat(factory.looksAutomated(null)).isTrue();
        assertThat(factory.looksAutomated("")).isTrue();
    }

    @Test
    @DisplayName("bot clicks are flagged, not discarded")
    void botsAreStillRecorded() {
        var request = new MockHttpServletRequest("GET", "/out/1");
        request.setRemoteAddr("10.0.0.1");
        request.addHeader("User-Agent", "curl/8.18.0");

        var context = factory.from(request, "10.0.0.1", "sess-2");

        // The raw ledger has to be able to explain itself when a merchant
        // disputes an invoice, so the row is kept and marked.
        assertThat(context.bot()).isTrue();
        assertThat(context.ipHash()).isNotNull();
        assertThat(context.uaHash()).isNotNull();
    }

    @Test
    @DisplayName("an overlong referer is truncated rather than rejected")
    void refererTruncated() {
        var request = new MockHttpServletRequest("GET", "/out/1");
        request.setRemoteAddr("10.0.0.1");
        request.addHeader("User-Agent", "Mozilla/5.0 Chrome/131");
        request.addHeader("Referer", "https://x.mk/?q=" + "a".repeat(5000));

        var context = factory.from(request, "10.0.0.1", "s");

        assertThat(context.referer()).hasSize(1000);
    }
}
