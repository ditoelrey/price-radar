package mk.priceradar.api.outbound;

import java.net.URI;
import java.util.Optional;

import jakarta.servlet.http.HttpServletRequest;
import mk.priceradar.api.common.PriceRadarProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * The outbound redirect. This endpoint is the business.
 *
 * <p>Three rules, in priority order:
 *
 * <ol>
 *   <li><b>Log before redirecting.</b> The click is the thing we invoice for.
 *       It is recorded synchronously, before the 302 goes out, so a click a
 *       shopper made is never a click we cannot bill.</li>
 *   <li><b>Fail open.</b> If logging throws -- the database is down, the pool
 *       is exhausted, a partition is missing -- the shopper is still
 *       redirected and the failure is logged loudly on our side. Losing one
 *       ledger row is bad; sending a shopper to an error page because our
 *       database hiccuped is worse, and it is the shop's sale we would be
 *       breaking as well as our own.</li>
 *   <li><b>Never cache.</b> A cached redirect would send later shoppers to a
 *       stale destination and, worse, would stop the click reaching us at
 *       all.</li>
 * </ol>
 *
 * <p>Live price verification is deliberately <em>not</em> here. It belongs in
 * front of this call with a hard sub-second budget, and it must never be able
 * to delay the redirect; the ingestion side already records
 * {@code verification_event} for that purpose.
 */
@RestController
public class OutboundController {

    private static final Logger log = LoggerFactory.getLogger(OutboundController.class);

    private final OutboundRepository repository;
    private final ClickContextFactory contexts;
    private final boolean trustForwardedFor;

    public OutboundController(OutboundRepository repository,
                              ClickContextFactory contexts,
                              PriceRadarProperties props) {
        this.repository = repository;
        this.contexts = contexts;
        this.trustForwardedFor = props.outbound().trustForwardedFor();
    }

    @GetMapping("/out/{variantId}")
    public ResponseEntity<Void> out(@PathVariable long variantId,
                                    HttpServletRequest request) {
        Optional<OutboundRepository.ClickTarget> found;
        try {
            found = repository.findTarget(variantId);
        } catch (RuntimeException e) {
            // Without a target there is nowhere to send anyone, so this is the
            // one failure that cannot fail open.
            log.error("outbound lookup failed for variant {}", variantId, e);
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        }

        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        OutboundRepository.ClickTarget target = found.get();

        String destination = target.redirectUrl();
        if (destination == null || destination.isBlank()) {
            log.error("variant {} has no product_url; cannot redirect", variantId);
            return ResponseEntity.notFound().build();
        }

        // --- log first ---------------------------------------------------
        try {
            repository.recordClick(target, contexts.from(
                    request, clientIp(request), request.getSession(true).getId()));
        } catch (RuntimeException e) {
            // Fail open, loudly. This log line is the only record that a
            // billable click happened, so it carries the ids needed to
            // reconstruct the row by hand.
            log.error("CLICK NOT RECORDED variant={} offer={} merchant={} price={} -- "
                            + "redirecting anyway", variantId, target.offerId(),
                    target.merchantId(), target.priceMinor(), e);
        }

        // --- then redirect -----------------------------------------------
        HttpHeaders headers = new HttpHeaders();
        headers.setLocation(URI.create(destination));
        headers.setCacheControl("no-store, no-cache, must-revalidate, max-age=0");
        headers.setPragma("no-cache");
        // Do not leak our internal paths to the shop as a referrer.
        headers.add("Referrer-Policy", "no-referrer");
        return new ResponseEntity<>(headers, HttpStatus.FOUND);
    }

    /**
     * The client address, honouring {@code X-Forwarded-For} only when a proxy
     * we control is in front. Trusting it unconditionally would let anyone
     * spoof the hash and poison our own bot and deduplication statistics.
     */
    String clientIp(HttpServletRequest request) {
        if (trustForwardedFor) {
            String forwarded = request.getHeader("X-Forwarded-For");
            if (forwarded != null && !forwarded.isBlank()) {
                // Leftmost entry is the original client.
                return forwarded.split(",")[0].trim();
            }
        }
        return request.getRemoteAddr();
    }
}
