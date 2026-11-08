-- =============================================================================
-- V3 -- Append-only history, the revenue ledger, and operational tables.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- price_point -- price/stock history, write-on-change only
-- -----------------------------------------------------------------------------
-- Volume note: 50k products x ~3 merchants x ~8 sizes x hourly probing would
-- be ~100M rows/year if written blindly. Writing only when a value actually
-- changes (~2% of observations) makes it ~2M rows/year, which Postgres does
-- not notice. The ingest loader is responsible for the "only on change" rule.

CREATE TABLE price_point (
    offer_variant_id bigint      NOT NULL,
    observed_at      timestamptz NOT NULL,
    price_minor      bigint      NOT NULL,
    in_stock         boolean,
    stock_qty        integer
) PARTITION BY RANGE (observed_at);

-- BRIN is the right index for an append-only, time-ordered table: tiny, and
-- perfect for the range scans the price-history chart issues.
CREATE INDEX price_point_time_brin ON price_point USING brin (observed_at);
CREATE INDEX price_point_variant_idx ON price_point (offer_variant_id, observed_at DESC);

-- -----------------------------------------------------------------------------
-- click_event -- THIS IS THE INVOICE DATA. Treat as a ledger.
-- -----------------------------------------------------------------------------
-- Logged synchronously in /out/{id} BEFORE any live verification runs, so a
-- slow merchant can never cost us a recorded click.

CREATE TABLE click_event (
    id                   bigserial   NOT NULL,
    occurred_at          timestamptz NOT NULL,

    product_id           bigint,
    offer_id             bigint,
    offer_variant_id     bigint,
    merchant_id          bigint      NOT NULL,
    country_code         char(2)     NOT NULL,

    -- Price the user was actually shown. Needed to settle disputes and to
    -- measure the click-time mismatch rate.
    price_at_click_minor bigint,
    currency_code        char(3),

    session_id           text,
    ip_hash              bytea,      -- salted hash only; LPPD/GDPR-aligned
    ua_hash              bytea,
    referer              text,
    is_bot               boolean     NOT NULL DEFAULT false,
    payout_minor         bigint,

    PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);

CREATE INDEX click_event_merchant_idx ON click_event (merchant_id, occurred_at DESC);
CREATE INDEX click_event_product_idx  ON click_event (product_id, occurred_at DESC);
CREATE INDEX click_event_time_brin    ON click_event USING brin (occurred_at);

-- -----------------------------------------------------------------------------
-- verification_event -- measures whether we are actually trustworthy
-- -----------------------------------------------------------------------------
-- The primary trust KPI of the whole platform:
--     click-time mismatch rate = share of verifications whose outcome was not
--     'match', per merchant. Target < 2-3% on each product's top offer.
-- A merchant sitting at 12% tells you exactly whose probe cadence or parser
-- is wrong, instead of leaving you to crawl everything harder and hope.

CREATE TYPE verify_trigger AS ENUM ('swr', 'hover', 'click', 'report', 'shadow');
CREATE TYPE verify_outcome AS ENUM ('match', 'price_changed', 'oos', 'timeout', 'error', 'delisted');

CREATE TABLE verification_event (
    id                bigserial      PRIMARY KEY,
    offer_variant_id  bigint         NOT NULL REFERENCES offer_variant(id) ON DELETE CASCADE,
    merchant_id       bigint         NOT NULL REFERENCES merchant(id) ON DELETE CASCADE,
    trigger           verify_trigger NOT NULL,
    requested_at      timestamptz    NOT NULL DEFAULT now(),
    latency_ms        integer,
    outcome           verify_outcome NOT NULL,
    shown_price_minor bigint,
    live_price_minor  bigint,
    shown_in_stock    boolean,
    live_in_stock     boolean
);

CREATE INDEX verification_merchant_idx ON verification_event (merchant_id, requested_at DESC);
CREATE INDEX verification_outcome_idx  ON verification_event (outcome, requested_at DESC);

-- -----------------------------------------------------------------------------
-- match_candidate -- the human review queue
-- -----------------------------------------------------------------------------
-- Fuzzy scores in [0.75, 0.92) land here. A human decision writes a
-- MERCHANT_SKU row into product_identifier, so the pair is never scored again.

CREATE TYPE candidate_status AS ENUM ('pending', 'accepted', 'rejected');

CREATE TABLE match_candidate (
    id          bigserial        PRIMARY KEY,
    offer_id    bigint           NOT NULL REFERENCES merchant_offer(id) ON DELETE CASCADE,
    product_id  bigint           NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    score       numeric(4,3)     NOT NULL,
    features    jsonb            NOT NULL DEFAULT '{}',
    status      candidate_status NOT NULL DEFAULT 'pending',
    decided_by  text,
    decided_at  timestamptz,
    created_at  timestamptz      NOT NULL DEFAULT now(),

    CONSTRAINT match_candidate_uq UNIQUE (offer_id, product_id)
);

CREATE INDEX match_candidate_queue_idx
    ON match_candidate (score DESC) WHERE status = 'pending';

-- -----------------------------------------------------------------------------
-- user_price_report -- highest-precision staleness detector we have
-- -----------------------------------------------------------------------------

CREATE TABLE user_price_report (
    id               bigserial   PRIMARY KEY,
    offer_variant_id bigint      NOT NULL REFERENCES offer_variant(id) ON DELETE CASCADE,
    reported_at      timestamptz NOT NULL DEFAULT now(),
    issue            text        NOT NULL,   -- wrong_price | out_of_stock | dead_link | wrong_product
    session_id       text,
    resolved_at      timestamptz
);

CREATE INDEX user_price_report_open_idx
    ON user_price_report (reported_at DESC) WHERE resolved_at IS NULL;

-- -----------------------------------------------------------------------------
-- ingest_run -- parser health. An unhealthy run must NOT be committed.
-- -----------------------------------------------------------------------------
-- Staging-then-swap: the loader validates fill rates and record-count deltas
-- against the 7-day median before promoting a run. A broken parser showing
-- "0 MKD" on the homepage is far worse than data that is a few hours stale.

CREATE TYPE run_status AS ENUM ('running', 'ok', 'degraded', 'failed', 'rejected');
CREATE TYPE fetch_kind AS ENUM ('catalog_parse', 'stock_probe', 'discovery');

CREATE TABLE ingest_run (
    id              bigserial  PRIMARY KEY,
    merchant_id     bigint     NOT NULL REFERENCES merchant(id) ON DELETE CASCADE,
    kind            fetch_kind NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          run_status NOT NULL DEFAULT 'running',

    offers_seen     integer NOT NULL DEFAULT 0,
    offers_written  integer NOT NULL DEFAULT 0,
    variants_seen   integer NOT NULL DEFAULT 0,
    http_errors     integer NOT NULL DEFAULT 0,

    -- Per-field fill rates; the alert thresholds live in the loader config.
    -- A drop in sku_fill_rate is the earliest signal that a site changed.
    sku_fill_rate   numeric(4,3),
    price_fill_rate numeric(4,3),
    size_fill_rate  numeric(4,3),

    -- Which extractor tier actually won, per field. A rising share of the
    -- css/selector tier means a redesign is coming.
    extractor_stats jsonb NOT NULL DEFAULT '{}',
    notes           text
);

CREATE INDEX ingest_run_merchant_idx ON ingest_run (merchant_id, started_at DESC);

-- -----------------------------------------------------------------------------
-- Monthly partition helper
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION ensure_month_partition(base_table text, month date)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    start_at date := date_trunc('month', month)::date;
    end_at   date := (date_trunc('month', month) + interval '1 month')::date;
    part     text := format('%s_%s', base_table, to_char(start_at, 'YYYYMM'));
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
            part, base_table, start_at, end_at);
    END IF;
END $$;

COMMENT ON FUNCTION ensure_month_partition IS
    'Call monthly from a cron job, a few months ahead: '
    'SELECT ensure_month_partition(''price_point'', current_date + interval ''2 months'');';

-- Bootstrap the current and next two months so a fresh database can take
-- writes immediately.
DO $$
DECLARE m date;
BEGIN
    FOREACH m IN ARRAY ARRAY[
        date_trunc('month', current_date)::date,
        (date_trunc('month', current_date) + interval '1 month')::date,
        (date_trunc('month', current_date) + interval '2 months')::date
    ] LOOP
        PERFORM ensure_month_partition('price_point', m);
        PERFORM ensure_month_partition('click_event', m);
    END LOOP;
END $$;
