package mk.priceradar.api;

import mk.priceradar.api.common.PriceRadarProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * Serving layer for Price Radar.
 *
 * <p>Two jobs, with very different risk profiles:
 *
 * <ul>
 *   <li><b>Read the catalogue.</b> Listing and detail pages, served from the
 *       denormalised summary table so a page view never aggregates over the
 *       whole variant table.</li>
 *   <li><b>Record outbound clicks.</b> {@code /out/{id}} is the revenue
 *       ledger. It logs before it redirects and it never fails closed.</li>
 * </ul>
 *
 * <p>It does not write to the catalogue and it does not migrate the schema:
 * both belong to the Python ingestion side.
 */
@SpringBootApplication
@EnableConfigurationProperties(PriceRadarProperties.class)
public class PriceRadarApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(PriceRadarApiApplication.class, args);
    }
}
