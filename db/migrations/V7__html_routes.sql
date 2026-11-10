-- =============================================================================
-- V7 -- Point dsport and megasport at their robots-permitted HTML route.
--
-- V5 recorded that both merchants' structured endpoints are forbidden by their
-- own robots.txt. This switches them to adapters that read the product pages
-- those sites do allow, so both stores become crawlable today instead of
-- waiting on a permission conversation.
--
--   dsport     magento      ->  magento_html       (spConfig size matrix)
--   megasport  woocommerce  ->  woocommerce_html   (data-product_variations)
--
-- The API adapters stay registered and stay correct. `api_requires_permission`
-- is left TRUE deliberately: it is the record of *why* the API route is unused,
-- and the flag to clear if permission or a feed ever arrives.
--
-- Both HTML adapters emit the same `merchant_sku` their API counterparts do --
-- dsport the article code, megasport the WordPress post id -- so this switch
-- updates the existing offers rather than duplicating them.
--
-- One unexpected benefit, worth recording: for the Puma Caven 2.0 the
-- megasport Store API reported prices.price = 3999 while every variation on
-- the product page is display_price = 3199.2. The parent price missed a 20%
-- reduction applying to all sizes, so the permitted route is also the more
-- accurate one.
-- =============================================================================

UPDATE merchant
   SET adapter = 'magento_html',
       source_type = 'scrape',
       robots_notes = robots_notes ||
           ' Switched to magento_html (V7): reads data-product-sku and the '
           'spConfig size matrix from the allowed product page.'
 WHERE slug = 'dsport';

UPDATE merchant
   SET adapter = 'woocommerce_html',
       source_type = 'scrape',
       robots_notes = robots_notes ||
           ' Switched to woocommerce_html (V7): reads the JSON-LD Product node '
           'and data-product_variations from the allowed product page, which '
           'also carries truer per-size prices than the Store API parent.'
 WHERE slug = 'megasport';
