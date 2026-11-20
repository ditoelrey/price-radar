-- -----------------------------------------------------------------------------
-- V24 -- a run kind for Опрема
-- -----------------------------------------------------------------------------
-- The same move V19 made for apparel, for the same reason.
--
-- `ingest_run_baseline` is keyed on (merchant_id, kind), and every gate check
-- that compares a run to "normal" reads it: the offer-count band, the
-- fill-rate medians, and the delisting a full sweep would do. One kind across
-- verticals would judge Sport Vision's first equipment run -- perhaps 1,500
-- offers -- against a footwear median near 3,800 and an apparel one near
-- 6,700. Rejection, guaranteed, and if it ever promoted the median would
-- become a blend that means nothing for any of the three.
--
-- It also decides what a full sweep may retire. `promote_run` scopes
-- delisting to the categories whose kind matches the run's vertical, so a
-- complete equipment sweep cannot touch a shoe.

ALTER TYPE fetch_kind ADD VALUE IF NOT EXISTS 'accessory_parse';

COMMENT ON TYPE fetch_kind IS
    'What a fetch was for. The three *_parse kinds are the three verticals: '
    '''catalog_parse'' is footwear, ''apparel_parse'' clothing and '
    '''accessory_parse'' equipment. Keeping them apart is not bookkeeping -- '
    'ingest_run_baseline is keyed on it, so a shared kind would compare each '
    'vertical against the other verticals'' medians and reject every first run.';
