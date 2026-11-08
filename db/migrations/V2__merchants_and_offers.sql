-- =============================================================================
-- V2 -- Supply side: merchants, their listings, and per-size variants.
--
-- Three levels, which is what makes the Idealo-style UI fall out for free:
--   product        the thing              (Adidas Stan Smith, M20325)
--   merchant_offer a shop's listing of it (one product page at one store)
--   offer_variant  a size of that listing (own price, own stock)
-- =============================================================================

CREATE TYPE source_t      AS ENUM ('feed', 'api', 'scrape', 'manual');
CREATE TYPE offer_status  AS ENUM ('active', 'unmatched', 'delisted', 'rejected');
CREATE TYPE match_method  AS ENUM ('mpn', 'gtin', 'merchant_sku', 'fuzzy', 'image', 'manual');

-- -----------------------------------------------------------------------------
-- merchant
-- -----------------------------------------------------------------------------

CREATE TABLE merchant (
    id            bigserial PRIMARY KEY,
    slug          text      NOT NULL UNIQUE,
    name          text      NOT NULL,
    country_code  char(2)   NOT NULL REFERENCES country(code),

    -- Which Python adapter handles this merchant. Recon collapsed 7 stores
    -- into 4 adapters, so this is deliberately many-merchants-to-one-adapter.
    adapter       text      NOT NULL,
    base_url      text      NOT NULL,

    logo_url      text,
    rating        numeric(2,1),
    review_count  integer   NOT NULL DEFAULT 0,

    source_type   source_t  NOT NULL DEFAULT 'scrape',
    feed_url      text,

    -- Recon finding: sizeer.com.mk returns its size list with Zaliha = null,
    -- i.e. it does NOT publish per-size stock, while sport-m.com.mk (same
    -- platform) returns exact quantities. When this is false the UI must say
    -- "listed" and never "in stock".
    publishes_stock boolean NOT NULL DEFAULT true,

    -- Shipping, for the total-price sort.
    free_shipping_threshold_minor bigint,
    flat_shipping_minor           bigint,
    delivery_days_min             smallint,
    delivery_days_max             smallint,

    -- Monetisation
    cpc_rate_minor    bigint,
    affiliate_network text,

    -- Recon finding: sizeer.com.mk and sport-m.com.mk share a platform, an IP
    -- (62.162.58.202) and an identical price for M20325 (6.799,00 den). They
    -- are very likely one operator. Linked merchants must be collapsed or
    -- badged in the UI, or the offer list looks padded.
    related_merchant_id bigint REFERENCES merchant(id) ON DELETE SET NULL,

    -- Per-domain politeness budget, enforced by the fetcher's token bucket.
    crawl_rps      numeric(4,2) NOT NULL DEFAULT 1.0,
    is_active      boolean      NOT NULL DEFAULT true,
    created_at     timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX merchant_country_idx ON merchant (country_code) WHERE is_active;

-- Deferred FK from V1 (product_identifier.merchant_id).
ALTER TABLE product_identifier
    ADD CONSTRAINT product_identifier_merchant_fk
    FOREIGN KEY (merchant_id) REFERENCES merchant(id) ON DELETE CASCADE;

-- -----------------------------------------------------------------------------
-- merchant_offer -- one shop's listing (one product page)
-- -----------------------------------------------------------------------------

CREATE TABLE merchant_offer (
    id               bigserial    PRIMARY KEY,
    merchant_id      bigint       NOT NULL REFERENCES merchant(id) ON DELETE CASCADE,

    -- NULL until matched. Unmatched offers are KEPT, not discarded: they often
    -- match later when another store reveals the SKU.
    product_id       bigint       REFERENCES product(id) ON DELETE SET NULL,

    merchant_sku     text         NOT NULL,   -- the store's own id for the listing
    raw_mpn          text,                    -- manufacturer code as scraped, verbatim
    raw_title        text         NOT NULL,
    raw_brand        text,
    product_url      text         NOT NULL,
    image_url        text,

    match_method     match_method,
    match_confidence numeric(4,3),
    status           offer_status NOT NULL DEFAULT 'unmatched',

    first_seen_at    timestamptz  NOT NULL DEFAULT now(),
    last_seen_at     timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT merchant_offer_uq UNIQUE (merchant_id, merchant_sku)
);

CREATE INDEX merchant_offer_product_idx   ON merchant_offer (product_id) WHERE product_id IS NOT NULL;
CREATE INDEX merchant_offer_unmatched_idx ON merchant_offer (merchant_id) WHERE product_id IS NULL;
CREATE INDEX merchant_offer_mpn_idx       ON merchant_offer (raw_mpn) WHERE raw_mpn IS NOT NULL;

-- -----------------------------------------------------------------------------
-- offer_variant -- a size. Price AND stock live here.
-- -----------------------------------------------------------------------------
-- Why size is a first-class row: for sneakers, stock per size changes far
-- faster than price, and showing a "lowest price" for a size the user cannot
-- buy is the single fastest way to lose their trust.

CREATE TABLE offer_variant (
    id                  bigserial PRIMARY KEY,
    offer_id            bigint    NOT NULL REFERENCES merchant_offer(id) ON DELETE CASCADE,

    size_label          text      NOT NULL,     -- verbatim: "44 2/3", "41<U+2153>", "35,5"
    size_eu             numeric(5,3),           -- normalised: 44.667, 41.333, 35.5
    size_uk             numeric(5,3),
    size_cm             numeric(5,2),

    -- The store's own per-size variant id, where it exposes one. Lets us probe
    -- a single size cheaply instead of re-parsing the whole page.
    --   sportvision group -> data-productsize-combid
    --   woocommerce       -> variation id
    --   magento           -> child product sku
    merchant_variant_id text,

    -- Integer money only. Unit is currency.minor_unit (MKD = 0 here).
    price_minor         bigint    NOT NULL,
    list_price_minor    bigint,                 -- pre-discount, for the "-30%" badge
    currency_code       char(3)   NOT NULL REFERENCES currency(code),
    shipping_cost_minor bigint,

    -- NULL means "we do not know" -- used for merchants where
    -- publishes_stock = false. Never coerce unknown to false.
    in_stock            boolean,
    stock_qty           integer,

    -- Freshness bookkeeping, consumed by the adaptive-TTL scheduler.
    last_checked_at     timestamptz NOT NULL DEFAULT now(),
    last_changed_at     timestamptz NOT NULL DEFAULT now(),
    check_ttl_seconds   integer     NOT NULL DEFAULT 14400,   -- 4h, adapts per probe
    consecutive_unchanged smallint  NOT NULL DEFAULT 0,
    freshness_tier      char(1)     NOT NULL DEFAULT 'B',     -- S hot / A warm / B cold

    CONSTRAINT offer_variant_uq UNIQUE (offer_id, size_label),
    CONSTRAINT offer_variant_price_nonneg CHECK (price_minor >= 0)
);

CREATE INDEX offer_variant_offer_idx   ON offer_variant (offer_id);
CREATE INDEX offer_variant_size_idx    ON offer_variant (size_eu) WHERE in_stock IS NOT FALSE;
-- Drives the scheduler: "what is due for a probe, hottest first".
CREATE INDEX offer_variant_due_idx
    ON offer_variant (freshness_tier, last_checked_at);

-- -----------------------------------------------------------------------------
-- product_price_summary -- denormalised read model
-- -----------------------------------------------------------------------------
-- The listing page reads ONLY this table. Never compute MIN(price) across
-- ~1.2M offer_variant rows at request time.

CREATE TABLE product_price_summary (
    product_id            bigint  PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    country_code          char(2) NOT NULL REFERENCES country(code),

    min_price_minor       bigint,
    min_price_variant_id  bigint REFERENCES offer_variant(id) ON DELETE SET NULL,
    max_price_minor       bigint,
    currency_code         char(3) REFERENCES currency(code),

    offer_count           integer NOT NULL DEFAULT 0,
    merchant_count        integer NOT NULL DEFAULT 0,
    in_stock_offer_count  integer NOT NULL DEFAULT 0,
    available_sizes_eu    numeric(5,3)[] NOT NULL DEFAULT '{}',

    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX pps_country_price_idx ON product_price_summary (country_code, min_price_minor);
