-- =============================================================================
-- V19 -- A run kind for apparel, so the two verticals cannot judge each other.
--
-- `ingest_run_baseline` is keyed on (merchant_id, kind), and every "is this
-- run normal?" check reads it: the offer-count band, the SKU, price and size
-- fill medians, and the delisting a full sweep performs. With one kind for
-- both verticals, sportvision's first apparel sweep -- roughly 6,500 offers
-- -- would have been measured against its footwear median of about 3,800.
-- That is far outside the +/-20 percent band, and on a shop with more than
-- three promoted runs the band is enforced rather than provisional, so the
-- run would have been rejected outright. Promoting it anyway would have been
-- worse: the median would then describe a blend of shoes and clothing, and
-- stop meaning anything for either.
--
-- `kind` is an enum rather than free text (V3), which is how this was caught:
-- the loader was already passing 'apparel_parse' and the unit tests were
-- green, because they stub the connection. A two-product smoke sweep against
-- the real database failed on the enum in the first second.
--
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block in older
-- Postgres and cannot be rolled back, which is why this migration does
-- nothing else. Flyway runs each file in its own transaction; from
-- PostgreSQL 12 this form is allowed there, and IF NOT EXISTS makes a repeat
-- run harmless.
-- =============================================================================

ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'apparel_parse';

COMMENT ON COLUMN ingest_run.kind IS
    'What the run was doing, and the partition its baseline lives in. '
    '''catalog_parse'' is footwear and anything unclassified; '
    '''apparel_parse'' is the clothing vertical. Keeping them apart is not '
    'bookkeeping -- a shared baseline would reject every apparel sweep and '
    'then poison the footwear median with clothing counts.';
