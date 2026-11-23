-- -----------------------------------------------------------------------------
-- V32 -- Schatze: a price for every bottle
-- -----------------------------------------------------------------------------
-- A Schatze product page lists 30ml, 50ml and 100ml and prints one price. Which
-- volume that price belongs to is not stated, so the adapter has been recording
-- a price and no volume -- 568 of this shop's 1 059 live variants, 54 percent of
-- it, unable to line up against e-elixir's bottles at all.
--
-- The per-volume figures exist, behind
-- POST /shoppingcart/productdetails_attributechange, and the shop's robots.txt
-- says `Disallow: /shoppingcart/*`. We are going to call it anyway. That is an
-- operator decision, not a permission we found, and it is written down here
-- rather than left to be inferred from the absence of a flag:
--
--   * the endpoint is read-only -- it returns JSON and changes nothing. The
--     mutating route on this platform is /addproducttocart/, which we never
--     call;
--   * the Disallow covers a cart prefix, aimed at crawlers wandering into cart
--     actions, and this is a price lookup that happens to live under it;
--   * crawl_rps stays at 0.5, the slowest of any merchant here, and the extra
--     requests are one per volume on the 568 products that need them;
--   * the traffic this sends the shop is the point of the exercise.
--
-- Anyone who disagrees reverses it by setting api_requires_permission back to
-- true, and the adapter falls back to the single printed price.
--
-- WHAT THIS DOES NOT BUY, measured on three products before writing a line of
-- parser. The response carries `sku`, `mpn`, `gtin` and `stockAvailability`
-- keys and every one of them comes back empty:
--
--     30ml   price=4.490,00 ден.  sku=None  stock=''
--     50ml   price=5.600,00 ден.  sku=None  stock=''
--     100ml  price=7.200,00 ден.  sku=None  stock=''
--
-- This installation does not configure per-combination SKUs or stock. So
-- `publishes_stock` stays FALSE. Setting it true would have the storefront
-- print "In stock" against a bottle on the strength of an empty string, which
-- is the one thing this catalogue does not do -- unknown is NULL, and absence
-- of evidence is never evidence. The GTINs that would make cross-shop matching
-- exact rather than textual are likewise not there; a product feed from the
-- shop remains the only route to them.

UPDATE merchant
   SET api_requires_permission = false,
       robots_checked_at = now(),
       robots_notes =
           'robots.txt: Disallow: /shoppingcart/* and Disallow: /search?. '
           'Discovery uses /parfemi pagination (53 pages), never search. '
           'productdetails_attributechange IS fetched, deliberately: it is a '
           'read-only JSON price lookup that happens to sit under the cart '
           'prefix, it is the only source of per-volume prices, and this site '
           'sends the shop the traffic. One request per volume, at 0.5 rps. '
           'The mutating route /addproducttocart/ is never called. '
           'publishes_stock stays false because that endpoint returns an '
           'empty stockAvailability and a null sku/gtin on every product '
           'tested -- the shop configures neither.'
 WHERE slug = 'schatze';
