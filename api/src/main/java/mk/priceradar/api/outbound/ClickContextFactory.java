package mk.priceradar.api.outbound;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.List;

import jakarta.servlet.http.HttpServletRequest;
import mk.priceradar.api.common.PriceRadarProperties;
import org.springframework.stereotype.Component;

/**
 * Builds the privacy-safe context stored with each click.
 *
 * <p>No raw IP address is ever written. An IP is personal data under North
 * Macedonia's LPPD and the GDPR it mirrors, and an unsalted hash of an IPv4
 * address is not anonymisation at all -- the whole space is four billion
 * values, so a rainbow table over it is trivial. The salt is what makes the
 * hash defensible, which is why it is required configuration rather than a
 * default.
 *
 * <p>Bot clicks are <em>recorded and flagged</em>, never dropped. Dropping
 * them would leave our click count unable to explain itself when a merchant
 * disputes an invoice; flagging them means the bill can be computed from the
 * human subset while the raw record stays complete.
 */
@Component
public class ClickContextFactory {

    /** Substrings that identify an automated client in a User-Agent. */
    private static final List<String> BOT_MARKERS = List.of(
            "bot", "crawler", "spider", "slurp", "curl", "wget", "python-requests",
            "httpx", "headlesschrome", "phantomjs", "scrapy", "monitoring",
            "pingdom", "uptimerobot", "facebookexternalhit", "preview");

    private final byte[] salt;

    public ClickContextFactory(PriceRadarProperties props) {
        this.salt = props.outbound().ipHashSalt().getBytes(StandardCharsets.UTF_8);
    }

    public OutboundRepository.ClickContext from(HttpServletRequest request,
                                                 String clientIp,
                                                 String sessionId) {
        String userAgent = request.getHeader("User-Agent");
        String referer = request.getHeader("Referer");
        return new OutboundRepository.ClickContext(
                trim(sessionId, 128),
                hash(clientIp),
                hash(userAgent),
                trim(referer, 1000),
                looksAutomated(userAgent));
    }

    /** Salted SHA-256, truncated to 16 bytes: enough to deduplicate, not to reverse. */
    byte[] hash(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(salt);
            digest.update(value.trim().toLowerCase().getBytes(StandardCharsets.UTF_8));
            return Arrays.copyOf(digest.digest(), 16);
        } catch (NoSuchAlgorithmException e) {
            // SHA-256 is mandated by the platform; unreachable in practice.
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }

    boolean looksAutomated(String userAgent) {
        if (userAgent == null || userAgent.isBlank()) {
            // No UA at all is far more likely a script than a browser.
            return true;
        }
        String ua = userAgent.toLowerCase();
        return BOT_MARKERS.stream().anyMatch(ua::contains);
    }

    private static String trim(String value, int max) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.length() <= max ? trimmed : trimmed.substring(0, max);
    }
}
