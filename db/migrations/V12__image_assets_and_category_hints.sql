-- =============================================================================
-- V12 -- Self-hosted images, and a category hint carried from discovery.
--
-- Two things that both need to exist before a full sweep, for the same
-- reason: at 50k products, mistakes stop being cosmetic.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- image_asset -- our own copy of a product photo
-- -----------------------------------------------------------------------------
-- Hotlinking was fine for a 32-product demo. At catalogue scale it means
-- every page view spends six shops' bandwidth, and a single referer rule at
-- any one of them blanks that shop's photos with no error on our side.
--
-- Content-addressed by SHA-256 of the bytes, which buys three things:
--   * deduplication, and it is not theoretical -- the shops publish the same
--     manufacturer press photo, so one file can back several products;
--   * immutability, so the served path can be cached hard and forever;
--   * idempotent re-fetching, since re-downloading an unchanged image lands
--     on the row that already exists.

CREATE TABLE image_asset (
    id           bigserial   PRIMARY KEY,
    sha256       char(64)    NOT NULL UNIQUE,
    -- Served path relative to the media root, e.g. "ab/cd/abcd...webp".
    path         text        NOT NULL,
    content_type text        NOT NULL,
    bytes        integer     NOT NULL CHECK (bytes > 0),
    -- Where we first saw it. Kept for provenance and for re-fetching if the
    -- local copy is ever lost; NOT what the storefront links to.
    source_url   text,
    fetched_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX image_asset_path_idx ON image_asset (path);

COMMENT ON TABLE image_asset IS
    'Locally stored product photos, content-addressed by SHA-256. The '
    'storefront serves these; product.image_url is only the remote source we '
    'fetched from.';

ALTER TABLE product
    ADD COLUMN image_asset_id    bigint REFERENCES image_asset(id) ON DELETE SET NULL,
    -- Null means never attempted. Set even on failure, so a broken URL is
    -- retried on a schedule rather than on every single pass.
    ADD COLUMN image_checked_at  timestamptz;

CREATE INDEX product_image_pending_idx
    ON product (image_checked_at NULLS FIRST)
    WHERE image_asset_id IS NULL AND image_url IS NOT NULL;

COMMENT ON COLUMN product.image_asset_id IS
    'Our stored copy. The API serves this when present and falls back to the '
    'remote image_url only while the pipeline catches up.';

-- -----------------------------------------------------------------------------
-- Category hint from discovery
-- -----------------------------------------------------------------------------
-- Classification reads the product title, and twelve of thirty-two products
-- had no category because their titles never named one ("Adidas Handball
-- Spezial", "Hoka Clifton UTL"). At 50k that is thousands of uncategorised
-- products in a storefront that filters by category.
--
-- Discovery knew all along: those products were reached through a footwear
-- facet or a footwear category page. The hint carries that context to the
-- loader, which still prefers what the title actually says -- a hint is the
-- fallback for silence, never an override of evidence.

ALTER TABLE stage_offer
    ADD COLUMN category_hint text;

COMMENT ON COLUMN stage_offer.category_hint IS
    'Category slug implied by where discovery found this product (a footwear '
    'facet, a sneakers category page). Used by the loader only when the '
    'title names no category of its own.';
