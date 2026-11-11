package mk.priceradar.api.outbound;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Optional;

import mk.priceradar.api.common.PriceRadarProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.mockito.Mockito;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;

/**
 * Tests for the redirect, which is the revenue path.
 *
 * <p>Plain unit tests rather than a Spring slice: the behaviour that matters
 * is ordering and failure handling, and a mocked repository makes both
 * directly assertable.
 */
class OutboundControllerTest {

    private static final OutboundRepository.ClickTarget TARGET =
            new OutboundRepository.ClickTarget(
                    11L, 7L, 3L, 2L, "MK",
                    "https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0",
                    null, 2863L, "MKD");

    private final OutboundRepository repository = mock(OutboundRepository.class);
    private final PriceRadarProperties props = new PriceRadarProperties(
            "MK", new PriceRadarProperties.Outbound("test-salt", false),
            new PriceRadarProperties.Freshness(180));
    private final ClickContextFactory contexts = new ClickContextFactory(props);
    private final OutboundController controller =
            new OutboundController(repository, contexts, props);

    private MockHttpServletRequest request() {
        var request = new MockHttpServletRequest("GET", "/out/11");
        request.setRemoteAddr("62.162.58.202");
        request.addHeader("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
        return request;
    }

    @Test
    @DisplayName("redirects with 302 to the shop's product URL")
    void redirects() {
        when(repository.findTarget(11L)).thenReturn(Optional.of(TARGET));

        var response = controller.out(11L, request());

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FOUND);
        assertThat(response.getHeaders().getLocation()).hasToString(TARGET.productUrl());
    }

    @Test
    @DisplayName("records the click BEFORE issuing the redirect")
    void logsBeforeRedirecting() {
        when(repository.findTarget(11L)).thenReturn(Optional.of(TARGET));

        controller.out(11L, request());

        InOrder order = Mockito.inOrder(repository);
        order.verify(repository).findTarget(11L);
        order.verify(repository).recordClick(any(), any());
        order.verifyNoMoreInteractions();
    }

    @Test
    @DisplayName("still redirects when the click cannot be recorded (fail open)")
    void failsOpenWhenLoggingBreaks() {
        when(repository.findTarget(11L)).thenReturn(Optional.of(TARGET));
        doThrow(new RuntimeException("connection pool exhausted"))
                .when(repository).recordClick(any(), any());

        var response = controller.out(11L, request());

        // Losing a ledger row is bad. Breaking the shopper's journey -- and
        // the shop's sale -- because our database hiccuped is worse.
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FOUND);
        assertThat(response.getHeaders().getLocation()).hasToString(TARGET.productUrl());
    }

    @Test
    @DisplayName("404s for an unknown variant without logging a click")
    void unknownVariant() {
        when(repository.findTarget(999L)).thenReturn(Optional.empty());

        var response = controller.out(999L, request());

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        verify(repository, never()).recordClick(any(), any());
    }

    @Test
    @DisplayName("503s when the target lookup itself fails")
    void lookupFailureCannotFailOpen() {
        when(repository.findTarget(11L)).thenThrow(new RuntimeException("db down"));

        var response = controller.out(11L, request());

        // The one failure that cannot fail open: with no target there is
        // nowhere to send anybody.
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
    }

    @Test
    @DisplayName("404s when the offer has no destination URL")
    void missingProductUrl() {
        var broken = new OutboundRepository.ClickTarget(
                11L, 7L, 3L, 2L, "MK", "  ", null, 2863L, "MKD");
        when(repository.findTarget(11L)).thenReturn(Optional.of(broken));

        assertThat(controller.out(11L, request()).getStatusCode())
                .isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    @DisplayName("the redirect is never cacheable")
    void neverCached() {
        when(repository.findTarget(11L)).thenReturn(Optional.of(TARGET));

        var headers = controller.out(11L, request()).getHeaders();

        // A cached redirect would send later shoppers to a stale destination
        // and, worse, stop the click reaching us at all.
        assertThat(headers.getCacheControl()).contains("no-store");
        assertThat(headers.getFirst("Referrer-Policy")).isEqualTo("no-referrer");
    }

    @Test
    @DisplayName("an affiliate template produces an attributable deep link")
    void affiliateTemplate() {
        var affiliate = new OutboundRepository.ClickTarget(
                11L, 7L, 3L, 2L, "MK",
                "https://shop.mk/p/1?x=2",
                "https://net.example/click?a=99&sub={variantId}&dest={url}",
                2863L, "MKD");

        String url = affiliate.redirectUrl();

        assertThat(url).startsWith("https://net.example/click?a=99&sub=11&dest=");
        // The destination must be encoded, or its own query string would be
        // swallowed by the network's.
        assertThat(url).contains("https%3A%2F%2Fshop.mk%2Fp%2F1%3Fx%3D2");
    }

    @Test
    @DisplayName("no affiliate template means a direct redirect")
    void noAffiliateTemplate() {
        assertThat(TARGET.redirectUrl()).isEqualTo(TARGET.productUrl());
    }

    @Test
    @DisplayName("X-Forwarded-For is ignored unless a trusted proxy is configured")
    void forwardedForIsNotTrustedByDefault() {
        var request = request();
        request.addHeader("X-Forwarded-For", "1.2.3.4");

        // Trusting it unconditionally would let anyone spoof the hash and
        // poison our own bot and deduplication statistics.
        assertThat(controller.clientIp(request)).isEqualTo("62.162.58.202");
    }

    @Test
    @DisplayName("X-Forwarded-For is honoured when explicitly trusted")
    void forwardedForTrustedWhenConfigured() {
        var trusting = new PriceRadarProperties(
                "MK", new PriceRadarProperties.Outbound("salt", true),
                new PriceRadarProperties.Freshness(180));
        var controllerBehindProxy =
                new OutboundController(repository, contexts, trusting);
        var request = request();
        request.addHeader("X-Forwarded-For", "1.2.3.4, 10.0.0.1");

        assertThat(controllerBehindProxy.clientIp(request)).isEqualTo("1.2.3.4");
    }
}
