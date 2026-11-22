-- -----------------------------------------------------------------------------
-- V28 -- a run kind for fragrances
-- -----------------------------------------------------------------------------
-- The same move V19 made for apparel and V24 for equipment, for the same
-- reason, and this vertical needs it more than either of them did.
--
-- `ingest_run_baseline` is keyed on (merchant_id, kind), and every gate check
-- that compares a run to "normal" reads it: the offer-count band, the
-- fill-rate medians, and the delisting a full sweep would do. e-elixir sells
-- nothing but perfume and cosmetics, so its fragrance run IS its catalogue --
-- roughly 723 single bottles out of 987 listings. Filed under
-- ''catalog_parse'' it would be measured against a footwear median built from
-- shops that sell thousands of shoes, and rejected on the count alone.
--
-- It also decides what a full sweep may retire. `promote_run` scopes
-- delisting to the categories whose kind matches the run's vertical, so a
-- complete fragrance sweep cannot touch a shoe -- and, once Schatze arrives,
-- a sweep of one perfumery cannot retire the other's offers.
--
-- Separated from V27 because Postgres will not let a value added to an enum
-- be used in the transaction that added it, and V27 already adds
-- ''volume_ml'' to size_system. Two migrations, two transactions, and the
-- first crawl is what proved it: `ingest_run.kind` is this enum, so the run
-- could not be opened at all.

ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'fragrance_parse';

COMMENT ON TYPE fetch_kind IS
    'What a fetch was for. The four *_parse kinds are the four verticals: '
    '''catalog_parse'' is footwear, ''apparel_parse'' clothing, '
    '''accessory_parse'' equipment and ''fragrance_parse'' perfume. Keeping '
    'them apart is not bookkeeping -- ingest_run_baseline is keyed on it, so '
    'a shared kind would compare each vertical against the other verticals'' '
    'medians and reject every first run.';
