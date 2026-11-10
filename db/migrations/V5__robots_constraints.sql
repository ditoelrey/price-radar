-- =============================================================================
-- V5 -- Record the robots.txt constraint per merchant.
--
-- The first live run of the fetcher corrected a Phase 1 conclusion. Recon found
-- that dsport.mk serves an open Magento GraphQL endpoint and megasport an open
-- WooCommerce Store API, and concluded "two stores need no scraping at all".
-- Technically true, and not usable: both sites explicitly forbid those paths.
--
--   dsport.mk                 Disallow: /graphql
--   megasportonlineshop.com   Disallow: /wp-json/
--
-- An endpoint being unauthenticated is not permission to crawl it. Honouring
-- robots is also the evidence of good faith that makes the feed conversation
-- possible later -- and for these two merchants that conversation is now the
-- highest-value action on the project, because one email converts a perfect
-- data source from forbidden to allowed.
--
-- What each site does permit (verified against its live robots.txt):
--
--   sportvision / sportreality / buzz   product pages + category pages
--   dsport                              product pages + /media/sitemap/*
--   megasport                           product pages + category pages
--                                       (but NOT search or ?filter_* URLs)
--   sport-m / sizeer                    no robots.txt at all -> unrestricted
-- =============================================================================

ALTER TABLE merchant
    ADD COLUMN api_requires_permission boolean NOT NULL DEFAULT false,
    ADD COLUMN robots_checked_at       timestamptz,
    ADD COLUMN robots_notes            text;

COMMENT ON COLUMN merchant.api_requires_permission IS
    'True when this merchant exposes a usable structured endpoint that its '
    'robots.txt forbids. The scheduler must not queue API probes for these '
    'merchants; use the permitted HTML route, or obtain written permission / '
    'a product feed and then set this back to false.';

COMMENT ON COLUMN merchant.robots_notes IS
    'The specific rule observed, so a future reader does not have to re-derive '
    'why a working endpoint is unused.';

UPDATE merchant
   SET api_requires_permission = true,
       robots_checked_at = now(),
       robots_notes = 'robots.txt: Disallow: /graphql -- the open Magento '
                      'GraphQL endpoint is off-limits without permission. '
                      'Product pages and /media/sitemap/* are allowed.'
 WHERE slug = 'dsport';

UPDATE merchant
   SET api_requires_permission = true,
       robots_checked_at = now(),
       robots_notes = 'robots.txt: Disallow: /wp-json/ -- the open WooCommerce '
                      'Store API is off-limits without permission. Product and '
                      'category pages are allowed; search (?s=) and '
                      '?filter_* URLs are not, so discovery must use category '
                      'pagination.'
 WHERE slug = 'megasport';

UPDATE merchant
   SET robots_checked_at = now(),
       robots_notes = 'robots.txt allows product and category pages.'
 WHERE slug IN ('sportvision', 'sportreality', 'buzz');

UPDATE merchant
   SET robots_checked_at = now(),
       robots_notes = 'No robots.txt (HTTP 404) -- unrestricted per RFC 9309. '
                      'POST /ProductCatalog/GetVelicini/ is therefore usable.'
 WHERE slug IN ('sportm', 'sizeer');
