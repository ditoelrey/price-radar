-- -----------------------------------------------------------------------------
-- V21 -- letter sizes on the listing summary
-- -----------------------------------------------------------------------------
-- The listing's size rail reads `available_sizes_eu` and nothing else, which
-- was the whole story while the catalogue was shoes. With apparel live the
-- rail is empty on every garment listing: `size_eu` is correctly NULL for a
-- hoodie, so the sidebar says "Нема броеви во овие резултати" over 17 032
-- offers whose sizes we hold.
--
-- The sizes themselves were never missing. V18 normalised them into
-- `offer_variant.size_alpha` -- 76 930 live apparel variants carry one -- and
-- nothing downstream read the column. This adds the denormalised array beside
-- the EU one so the listing can keep its promise never to aggregate over
-- `offer_variant` at request time.
--
-- Alpha only, deliberately. Apparel sizes arrive in four systems (alpha
-- 76 930, numeric 37 267, age 16 564, height 570) and one rail cannot be
-- honest about all of them: a shopper picking "S" and a shopper picking
-- "128 cm" are not filtering the same axis. The other three stay unexposed
-- rather than being flattened into a list that mixes them.

ALTER TABLE product_price_summary
    ADD COLUMN IF NOT EXISTS available_sizes_alpha text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN product_price_summary.available_sizes_alpha IS
    'Letter sizes a shopper can actually buy, smallest first. Mirrors '
    'available_sizes_eu: distinct, in_stock IS NOT FALSE, so a shop that '
    'publishes no availability still contributes its sizes.';

-- -----------------------------------------------------------------------------
-- The ladder, as a rank
-- -----------------------------------------------------------------------------
-- Sorting these as text gives 3XL, 4XL, 5XL, L, M, S, XL, XS, XXL, XXS, which
-- is the one order no shopper reads. The ladder is the same one
-- `mkagg.sizing.ALPHA_LADDER` defines; it lives here as well because the
-- array is built in SQL, by this migration and by `refresh_summary`, and a
-- function is cheaper to keep honest than the same CASE written twice.
--
-- IMMUTABLE so it can be used in an index later if the rail ever needs one.
-- An unknown label ranks last rather than raising: a size we have not met is
-- a reason to show it at the end, not to fail the summary refresh.

CREATE OR REPLACE FUNCTION alpha_size_rank(label text)
RETURNS integer
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT coalesce(
        array_position(
            ARRAY['XXS','XS','S','M','L','XL','XXL','3XL','4XL','5XL'],
            label),
        99);
$$;

COMMENT ON FUNCTION alpha_size_rank(text) IS
    'Position on the letter-size ladder, smallest first; 99 for anything '
    'off it. Mirrors mkagg.sizing.ALPHA_LADDER.';

-- -----------------------------------------------------------------------------
-- Backfill
-- -----------------------------------------------------------------------------
-- Every product at once rather than waiting for the next sweep to touch it:
-- a garment nobody re-crawls for a week would otherwise sit on the listing
-- with an empty rail, and the data to fill it is already in the table.
--
-- Only rows that would change are written, so the pass is re-runnable and
-- leaves `updated_at` alone on the rest -- that column drives the "updated"
-- line on a product card and must not move because a migration ran.

WITH computed AS (
    SELECT s.product_id,
           coalesce((
               SELECT array_agg(a ORDER BY alpha_size_rank(a), a)
                 FROM (SELECT DISTINCT ov.size_alpha AS a
                         FROM offer_variant ov
                         JOIN merchant_offer mo ON mo.id = ov.offer_id
                         JOIN merchant m        ON m.id = mo.merchant_id
                        WHERE mo.product_id = s.product_id
                          AND mo.status = 'active'
                          AND m.is_active
                          AND ov.size_alpha IS NOT NULL
                          AND ov.in_stock IS NOT FALSE) t), '{}') AS sizes
      FROM product_price_summary s
)
UPDATE product_price_summary s
   SET available_sizes_alpha = c.sizes
  FROM computed c
 WHERE c.product_id = s.product_id
   AND s.available_sizes_alpha IS DISTINCT FROM c.sizes;
