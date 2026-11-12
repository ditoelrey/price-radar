-- Drop EU sizes that were never really EU sizes.
--
-- Sport Vision publishes three parallel scales per size row -- the brand's own
-- size, EU, and centimetres -- and on some articles its own conversion table
-- has holes. Where the mapping is missing, the EU column simply echoes the
-- brand column and the centimetre column is left empty:
--
--     original-size: 4.5   eur-size: 4.5   cm-size: (empty)
--     original-size: 5     eur-size: 35.5  cm-size: 22     <- mapping starts
--
-- Taken literally, that stored "EU 4.5" for a men's running shoe. The harm is
-- not the odd number on the page: it is that the shoe silently disappears from
-- the EU size filter, which is the single comparison this site exists to make.
-- The adapter now refuses those rows at parse time (see `_unmapped_eu` in
-- adapters/sportvision.py); this repairs the rows already written by the
-- Stage 1 sweep.
--
-- The condition below is the database-side half of that signature. It was
-- checked against the stored HTML before being applied: re-parsing the four
-- affected products with the fixed adapter drops exactly these 19 rows and no
-- others, and leaves every genuine size run intact -- including the Nike Court
-- Borough children's run (EU 28-40), which is real and properly converted.
--
-- The variants themselves are kept. They are buyable sizes with real prices;
-- it is only the EU claim that was wrong, and `size_label` still carries what
-- the shop actually printed.

UPDATE offer_variant
   SET size_eu = NULL
 WHERE size_eu IS NOT NULL
   AND size_eu < 16      -- EU 16 is roughly a 9-month-old; our real floor is 17
   AND size_cm IS NULL;  -- the shop fills centimetres whenever it converted

-- `available_sizes_eu` is denormalised onto the summary, so the listing's size
-- facet would keep offering the phantom sizes until this runs.
-- Driven from the summary rather than from the variants, so that a product
-- which lost *every* EU size is reset to an empty array instead of silently
-- keeping its old one: an aggregate over the variants has no row to offer for
-- a product that no longer has any.
UPDATE product_price_summary s
   SET available_sizes_eu = coalesce((
           SELECT array_agg(DISTINCT ov.size_eu)
             FROM offer_variant ov
             JOIN merchant_offer mo ON mo.id = ov.offer_id
             JOIN merchant m        ON m.id = mo.merchant_id
            WHERE mo.product_id = s.product_id
              AND mo.status = 'active'
              AND m.is_active
              AND ov.size_eu IS NOT NULL
              AND ov.in_stock IS NOT FALSE), '{}'),
       updated_at = now()
 WHERE s.available_sizes_eu <> coalesce((
           SELECT array_agg(DISTINCT ov.size_eu)
             FROM offer_variant ov
             JOIN merchant_offer mo ON mo.id = ov.offer_id
             JOIN merchant m        ON m.id = mo.merchant_id
            WHERE mo.product_id = s.product_id
              AND mo.status = 'active'
              AND m.is_active
              AND ov.size_eu IS NOT NULL
              AND ov.in_stock IS NOT FALSE), '{}');
