-- =============================================================================
-- V11 -- Remove price summaries that no active merchant backs.
--
-- A data repair for a bug the frontend surfaced as a crash.
--
-- `refresh_summary` filtered `merchant_offer.status = 'active'` but not
-- `merchant.is_active`. When V8 deactivated dsport -- whose edge returns 403
-- to our declared crawler -- its products kept their summary rows. The
-- listing reads those rows, so the site went on advertising
-- "Adidas Terrex Skychaser · from 8 599 ден. · 1 shop", while the detail
-- page's offer query (which *does* filter m.is_active) returned nothing.
--
-- A price for something nobody can buy is the exact failure the pipeline is
-- built to avoid, and nothing flagged it: it took a TypeError in a size
-- formatter on the empty-state branch to make it visible.
--
-- The loader is fixed; this clears what it already wrote. Deleting rather
-- than nulling, because "no summary" is what a product with no purchasable
-- offer should have -- the listing requires min_price_minor IS NOT NULL, so
-- these products correctly drop out until a live merchant lists them again.
-- Their offers, variants and price history are all untouched, so re-enabling
-- dsport restores everything on the next promoted run.
-- =============================================================================

DELETE FROM product_price_summary s
 WHERE NOT EXISTS (
     SELECT 1
       FROM merchant_offer mo
       JOIN merchant m ON m.id = mo.merchant_id
      WHERE mo.product_id = s.product_id
        AND mo.status = 'active'
        AND m.is_active
 );
