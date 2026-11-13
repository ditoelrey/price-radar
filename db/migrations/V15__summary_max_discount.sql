-- Carry each product's best advertised discount on the summary, so the
-- listing can sort by it.
--
-- The listing deliberately reads `product_price_summary` and nothing else:
-- one row per product, no join to `offer_variant`, which is what keeps a
-- 24-product page to a single indexed scan over what will become hundreds of
-- thousands of variants. Sorting by discount from the variants would undo
-- that for every page view, so the number is computed once at promotion
-- time, next to the prices it is derived from.
--
-- Stored as whole percent rather than the two prices: it is what the UI
-- renders and what the sort orders by, and a product's "biggest discount" is
-- a maximum over its offers, not a pair of prices belonging to any one of
-- them. NULL means no shop is discounting it -- distinct from 0, which would
-- claim a shop advertised a 0% saving.

ALTER TABLE product_price_summary
    ADD COLUMN max_discount_pct smallint
        CHECK (max_discount_pct IS NULL
               OR max_discount_pct BETWEEN 1 AND 99);

-- Sorting is `DESC NULLS LAST` over the whole catalogue, so the index has to
-- match that order or Postgres sorts the table every time.
CREATE INDEX pps_discount_idx
    ON product_price_summary (country_code, max_discount_pct DESC NULLS LAST);

-- Backfill from what is already stored. Only megasport carries list prices
-- today; the Sport Vision shops gained list-price extraction after their
-- Stage 2 sweeps, so theirs fill in as Stage 3 re-ingests them.
UPDATE product_price_summary s
   SET max_discount_pct = f.pct
  FROM (
        SELECT mo.product_id,
               max(round(100.0 * (ov.list_price_minor - ov.price_minor)
                               / ov.list_price_minor))::smallint AS pct
          FROM offer_variant ov
          JOIN merchant_offer mo ON mo.id = ov.offer_id
          JOIN merchant m        ON m.id = mo.merchant_id
         WHERE mo.status = 'active'
           AND m.is_active
           AND ov.price_minor IS NOT NULL
           AND ov.list_price_minor IS NOT NULL
           AND ov.list_price_minor > ov.price_minor
         GROUP BY mo.product_id
       ) f
 WHERE f.product_id = s.product_id
   AND f.pct BETWEEN 1 AND 99;
