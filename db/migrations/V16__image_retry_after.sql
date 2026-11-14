-- =============================================================================
-- V16 -- Separate "we looked" from "do not look again yet".
--
-- V12 made `image_checked_at` do both jobs: it recorded that we fetched a
-- URL, and the selection query derived the next attempt from it with one
-- global `retry_hours`. One window for every outcome is the problem, because
-- the outcomes are not alike:
--
--   * a 404, or an HTML error page served as a JPEG, is evidence about the
--     URL -- a full day is right, and re-asking sooner just wastes requests;
--   * a connection reset is evidence about the network -- a full day is
--     wrong, because nothing about the URL has been established at all.
--
-- The buzz image pass hit the second case: three transport failures, all
-- three stamped, and two of them proved alive on a re-fetch minutes later.
-- Those two products were locked out of retry for 24 hours over a blip that
-- had already passed. It cost two products; the same minute during a larger
-- pass would have cost thousands.
--
-- The fix is to stop deriving the schedule at read time and record it when
-- the outcome is known, which is the only moment we know what kind of
-- failure it was. `image_checked_at` goes back to meaning exactly one thing,
-- and the new column carries the decision.
-- =============================================================================

ALTER TABLE product
    -- Null means eligible now: never attempted, or deliberately reopened.
    ADD COLUMN image_retry_after timestamptz;

COMMENT ON COLUMN product.image_retry_after IS
    'Earliest next image fetch for this product. Written when an attempt '
    'fails, with a window chosen from what the failure proves: a full day '
    'for evidence about the URL, an hour for a transport error that proves '
    'nothing about it. Null means eligible now.';

COMMENT ON COLUMN product.image_checked_at IS
    'When we last fetched image_url, whatever the outcome. A record of what '
    'happened, never a schedule -- image_retry_after decides the next '
    'attempt.';

-- Everything stamped under V12 was scheduled by the 24-hour default, so that
-- is what those rows meant. Carrying it over keeps this migration a rename
-- of intent rather than a mass reopening: without it every already-checked
-- product would become eligible at once and the next pass would re-request
-- every known-dead URL in the catalogue.
UPDATE product
   SET image_retry_after = image_checked_at + interval '24 hours'
 WHERE image_checked_at IS NOT NULL;

-- The partial index exists to make the pending query cheap, so it has to
-- follow the column that query now orders and filters on.
DROP INDEX IF EXISTS product_image_pending_idx;

CREATE INDEX product_image_pending_idx
    ON product (image_retry_after NULLS FIRST)
    WHERE image_asset_id IS NULL AND image_url IS NOT NULL;
