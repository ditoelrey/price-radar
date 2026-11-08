-- =============================================================================
-- V1 -- Core catalogue: the unified ("global product") side of the model.
--
-- Multi-country from day one: launch is MK, but every price and merchant is
-- scoped to a country + currency so RS / HR / BA / SI need no migration later.
-- =============================================================================

-- pg_trgm powers the fuzzy fallback matcher and the MVP search.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- Currency / country reference
-- -----------------------------------------------------------------------------

CREATE TABLE currency (
    code        char(3)  PRIMARY KEY,          -- ISO 4217: MKD, EUR, RSD, HRK, BAM
    minor_unit  smallint NOT NULL,             -- decimal places used for storage
    symbol      text     NOT NULL
);

COMMENT ON COLUMN currency.minor_unit IS
    'Decimal places that price_minor is expressed in. Recon finding: the MK '
    'shops configure MKD with minor_unit = 0 (WooCommerce Store API reports '
    'currency_minor_unit: 0), i.e. whole denars. EUR will be 2. Always read '
    'this column instead of assuming 100.';

CREATE TABLE country (
    code           char(2) PRIMARY KEY,        -- ISO 3166-1 alpha-2
    name           text    NOT NULL,
    currency_code  char(3) NOT NULL REFERENCES currency(code),
    default_locale text    NOT NULL,           -- mk-MK, sq-MK, sr-RS ...
    is_active      boolean NOT NULL DEFAULT false
);

-- -----------------------------------------------------------------------------
-- Brand / category
-- -----------------------------------------------------------------------------

CREATE TABLE brand (
    id      bigserial PRIMARY KEY,
    slug    text      NOT NULL UNIQUE,
    name    text      NOT NULL,
    -- Cyrillic/Latin aliases. MK users search "Најк", "Nike", "najk" alike,
    -- so the matcher and the search indexer both read this column.
    aliases text[]    NOT NULL DEFAULT '{}'
);

CREATE INDEX brand_aliases_gin ON brand USING gin (aliases);

-- Category kind keeps the roadmap open: footwear MVP, then apparel, then
-- fragrance (different matching rules, same tables).
CREATE TYPE category_kind AS ENUM ('footwear', 'apparel', 'accessory', 'fragrance', 'equipment');

CREATE TABLE category (
    id        bigserial     PRIMARY KEY,
    parent_id bigint        REFERENCES category(id) ON DELETE SET NULL,
    slug      text          NOT NULL UNIQUE,
    kind      category_kind NOT NULL DEFAULT 'footwear',
    name_en   text          NOT NULL,
    name_mk   text,
    name_sq   text
);

CREATE INDEX category_parent_idx ON category (parent_id);

-- -----------------------------------------------------------------------------
-- Product -- one row per real-world article/colourway
-- -----------------------------------------------------------------------------

CREATE TYPE gender_t AS ENUM ('men', 'women', 'unisex', 'kids');

CREATE TABLE product (
    id             bigserial PRIMARY KEY,
    brand_id       bigint    NOT NULL REFERENCES brand(id),
    category_id    bigint    REFERENCES category(id) ON DELETE SET NULL,

    model_name     text      NOT NULL,          -- "Caven 2.0"
    canonical_name text      NOT NULL,          -- "Puma Caven 2.0"
    colorway       text,                        -- "White / Black"
    gender         gender_t  NOT NULL DEFAULT 'unisex',

    -- Normalised manufacturer part number. Recon showed this is present on all
    -- 7 MK stores, so it is the primary matching key, not a nice-to-have.
    primary_mpn    text,

    image_url      text,
    slug           text      NOT NULL UNIQUE,

    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX product_brand_idx        ON product (brand_id);
CREATE INDEX product_category_idx     ON product (category_id);
CREATE INDEX product_primary_mpn_idx  ON product (primary_mpn) WHERE primary_mpn IS NOT NULL;
-- Blocking index for the fuzzy fallback: never compare across brand+gender.
CREATE INDEX product_block_idx        ON product (brand_id, gender, category_id);
CREATE INDEX product_name_trgm_idx    ON product USING gin (canonical_name gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- product_identifier -- the matching backbone
-- -----------------------------------------------------------------------------
-- One product carries many identifiers: its MPN, maybe a GTIN, plus one
-- MERCHANT_SKU per store once a match is confirmed. A confirmed merchant SKU
-- is written here so that offer is never fuzzy-matched again -- the system
-- gets monotonically smarter.

CREATE TYPE identifier_t AS ENUM ('MPN', 'GTIN13', 'UPC', 'MERCHANT_SKU');

CREATE TABLE product_identifier (
    id          bigserial    PRIMARY KEY,
    product_id  bigint       NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    id_type     identifier_t NOT NULL,
    value_norm  text         NOT NULL,     -- uppercased, non-alphanumerics stripped
    merchant_id bigint,                    -- set only for MERCHANT_SKU (FK added in V2)
    source      text,                      -- jsonld | graphql | store_api | url | manual
    created_at  timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT identifier_merchant_scope CHECK (
        (id_type = 'MERCHANT_SKU' AND merchant_id IS NOT NULL) OR
        (id_type <> 'MERCHANT_SKU' AND merchant_id IS NULL)
    )
);

-- Global identifiers (MPN/GTIN/UPC) are unique across the whole catalogue.
CREATE UNIQUE INDEX product_identifier_global_uq
    ON product_identifier (id_type, value_norm)
    WHERE id_type <> 'MERCHANT_SKU';

-- A merchant SKU only has to be unique within that merchant.
CREATE UNIQUE INDEX product_identifier_merchant_uq
    ON product_identifier (merchant_id, value_norm)
    WHERE id_type = 'MERCHANT_SKU';

CREATE INDEX product_identifier_product_idx ON product_identifier (product_id);

-- -----------------------------------------------------------------------------
-- size_mapping -- not optional, proven necessary by recon
-- -----------------------------------------------------------------------------
-- Formats observed live on the 7 target stores:
--   sportvision.mk   "35,5"  and  "35.5"   (both, on the same page)
--   buzzsneakers.mk  "44 2/3"
--   sport-m.com.mk   "41 1/3" as "41<U+2153>" (Unicode VULGAR FRACTION ONE THIRD)
--   megasport        "37.5" in attribute terms but "37-5" in variation values
--   dsport           "BEZ VELICINA" for one-size articles
-- Every adapter emits size_label (verbatim) + size_eu (numeric); this table
-- resolves the leftovers and the brand-specific UK/US conversions.

CREATE TABLE size_mapping (
    id         bigserial PRIMARY KEY,
    brand_id   bigint    REFERENCES brand(id) ON DELETE CASCADE,  -- NULL = applies to all
    gender     gender_t,                                          -- NULL = applies to all
    raw_label  text      NOT NULL,
    size_eu    numeric(5,3),
    size_uk    numeric(5,3),
    size_us    numeric(5,3),
    size_cm    numeric(5,2),
    notes      text
);

-- The enum literal is cast explicitly: an index expression must resolve its
-- types without relying on context inference.
CREATE UNIQUE INDEX size_mapping_uq
    ON size_mapping (COALESCE(brand_id, 0),
                     COALESCE(gender, 'unisex'::gender_t),
                     raw_label);
