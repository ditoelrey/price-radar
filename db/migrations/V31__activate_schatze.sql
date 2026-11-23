-- -----------------------------------------------------------------------------
-- V31 -- schatze goes live, on the permitted route
-- -----------------------------------------------------------------------------
-- V27 seeded this merchant inactive, because its adapter did not exist yet and
-- `is_active` is what the scheduler, promote and the serving query all read.
-- `mkagg.adapters.nopcommerce` exists now, so the gate comes off.
--
-- `api_requires_permission` stays TRUE, and that is not an oversight. It
-- records a fact about the shop, not a verdict on this crawl: per-volume
-- price, SKU, GTIN and stock exist only behind
-- POST /shoppingcart/productdetails_attributechange, and robots.txt says
-- `Disallow: /shoppingcart/*`. The adapter never calls it. megasport has
-- carried the same pairing since V5 for the same reason -- flag set, crawling
-- happily on the HTML route its robots.txt does allow.
--
-- What the permitted route costs us is stated plainly rather than hidden:
--
--   * No per-volume prices. A product page lists 30ml, 50ml and 100ml and
--     prices only the preselected one, so a multi-volume offer carries a
--     price and no volume. Three guessed prices would be worse than one
--     missing rail.
--   * No stock, hence `publishes_stock = false`. The page's microdata states
--     availability for the *product*; nothing says whether the 50ml is on the
--     shelf, and unknown must not be coerced to true.
--   * No article code, hence every offer trips `missing_mpn`. This shop
--     publishes none, which is precisely why V29 added the `identity` match
--     method: a fragrance is joined on brand, line and concentration.
--
-- A product feed from the shop would settle all three at once, and would hand
-- over the GTINs that make cross-shop matching exact rather than textual.
-- Until then this is the honest half of the catalogue, and it is worth having:
-- a dry run over 32 live products joined 5 of them straight onto e-elixir's,
-- including Luna Rossa Ocean in Eau de Parfum and in Eau de Toilette landing
-- on their two separate pages.
--
-- crawl_rps stays at 0.5 -- one request every two seconds, the slowest of any
-- merchant here. The whole shelf is roughly 1 150 requests.

UPDATE merchant
   SET is_active = true,
       robots_checked_at = now()
 WHERE slug = 'schatze';
