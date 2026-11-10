-- =============================================================================
-- V6 -- Staging tables, so a bad ingest run can never reach the read model.
--
-- The rule being enforced: **stage, validate, then swap.** A parser that has
-- quietly started returning "0 MKD", or half the sizes, or 10% of the
-- catalogue, must not be able to publish that to the site. Serving a price
-- that is confidently wrong destroys trust far more thoroughly than serving
-- one that is a few hours stale, and it is much harder to notice.
--
-- Why staging tables rather than one long transaction: a full catalogue crawl
-- runs for many minutes over thousands of products. Holding a single
-- transaction open for that bloats the live tables and blocks vacuum. Instead
-- the parsed rows land here -- cheap, append-only, no FKs into the catalogue
-- -- and promotion is a short transaction at the end, once the aggregate
-- metrics have been checked against history.
--
-- A rejected run keeps its staged rows on purpose. That is the evidence for
-- working out what the parser did wrong, and it is what a re-parse replays.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ingest_run: decision bookkeeping
-- -----------------------------------------------------------------------------

ALTER TABLE ingest_run
    ADD COLUMN promoted_at      timestamptz,
    ADD COLUMN offers_promoted  integer NOT NULL DEFAULT 0,
    ADD COLUMN decision_detail  jsonb   NOT NULL DEFAULT '{}',
    ADD COLUMN rejected_reason  text;

COMMENT ON COLUMN ingest_run.decision_detail IS
    'Every metric the validator looked at and the threshold it was compared '
    'against, so a rejection can be understood months later without rerunning '
    'anything.';

COMMENT ON COLUMN ingest_run.rejected_reason IS
    'Null unless status = rejected. Set from the first failed check.';

-- -----------------------------------------------------------------------------
-- stage_offer / stage_variant
-- -----------------------------------------------------------------------------
-- Deliberately denormalised and FK-free towards the catalogue: staging holds
-- what the adapter saw, not what we concluded. Matching happens at promotion.

CREATE TABLE stage_offer (
    id             bigserial PRIMARY KEY,
    ingest_run_id  bigint    NOT NULL REFERENCES ingest_run(id) ON DELETE CASCADE,
    merchant_id    bigint    NOT NULL REFERENCES merchant(id) ON DELETE CASCADE,

    merchant_sku   text      NOT NULL,
    raw_mpn        text,
    raw_title      text      NOT NULL,
    raw_brand      text,
    product_url    text      NOT NULL,
    image_url      text,
    currency_code  char(3)   NOT NULL,

    --  field -> which extractor tier produced it (api/graphql/jsonld/
    --  datalayer/url/css/regex). A rising share of 'css' means a redesign is
    --  coming; a drop in 'jsonld' is the earliest breakage signal there is.
    extractors     jsonb     NOT NULL DEFAULT '{}',
    quality_issues text[]    NOT NULL DEFAULT '{}',
    snapshot_key   text,

    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT stage_offer_uq UNIQUE (ingest_run_id, merchant_id, merchant_sku)
);

CREATE INDEX stage_offer_run_idx ON stage_offer (ingest_run_id);

CREATE TABLE stage_variant (
    id                  bigserial PRIMARY KEY,
    stage_offer_id      bigint    NOT NULL REFERENCES stage_offer(id) ON DELETE CASCADE,

    size_label          text      NOT NULL,
    size_eu             numeric(5,3),
    size_uk             numeric(5,3),
    size_cm             numeric(5,2),
    merchant_variant_id text,

    price_minor         bigint    NOT NULL,
    list_price_minor    bigint,
    currency_code       char(3)   NOT NULL,
    shipping_cost_minor bigint,

    -- NULL means the merchant does not publish stock (sizeer). Never coerced.
    in_stock            boolean,
    stock_qty           integer,

    CONSTRAINT stage_variant_uq UNIQUE (stage_offer_id, size_label),
    CONSTRAINT stage_variant_price_nonneg CHECK (price_minor >= 0)
);

CREATE INDEX stage_variant_offer_idx ON stage_variant (stage_offer_id);

-- -----------------------------------------------------------------------------
-- Historical baseline for the validator
-- -----------------------------------------------------------------------------
-- The validator compares a run against this merchant's own recent history for
-- the same kind of work, not against a global constant. A store with 600
-- sneakers and one with 60 have very different normal.

CREATE VIEW ingest_run_baseline AS
SELECT merchant_id,
       kind,
       count(*)                                   AS runs,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY offers_seen)     AS median_offers,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY sku_fill_rate)   AS median_sku_fill,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY price_fill_rate) AS median_price_fill,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY size_fill_rate)  AS median_size_fill
  FROM ingest_run
 WHERE status IN ('ok', 'degraded')
   AND promoted_at IS NOT NULL
   AND started_at > now() - interval '7 days'
 GROUP BY merchant_id, kind;

COMMENT ON VIEW ingest_run_baseline IS
    'Seven-day median per merchant and run kind, over promoted runs only. '
    'A rejected run must never widen the band that would have caught it.';
