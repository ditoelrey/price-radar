-- -----------------------------------------------------------------------------
-- V26 -- a garment sized "M/L" belongs under both M and L
-- -----------------------------------------------------------------------------
-- `offer_variant.size_alpha` holds one letter, so a label naming two had
-- nowhere to go and fell through to `size_system = 'numeric'` -- the reading
-- that means "a number we could not place". The listing's letter rail and
-- the `size` filter both read `size_alpha`, so 1 200-odd garments sized
-- XS/S, S/M, M/L or L/XL were invisible to a shopper filtering by any
-- letter at all, including the two printed on the label.
--
-- The span is stored rather than resolved. Picking one end would be a guess
-- about which size the article really is, and the shops are telling us it is
-- both; `size_alpha` keeps the lower letter so every existing reader -- the
-- rail, the ordering, the API DTO -- carries on working unchanged, and
-- `size_alpha_max` carries the upper one for those that want the range.
--
-- What is NOT a span, and why the parser is strict about it: these shops
-- write a slash for two different things.
--
--     M/L   L/XL   XS/S   2XS/XS      a span of two sizes
--     L/S   M/S    XL/S   S/S         a size and a *length* -- Short
--     L-T   2XL-T  4XL-T              a size and a length -- Tall
--     S A-C XS A-C                    a bra band and a cup range
--
-- Only the first group climbs the ladder, which is the test
-- `mkagg.sizing._alpha_span` applies. "L/S" read as a range runs backwards
-- and "S/S" collapses to one size; both are refused. Dashes are excluded
-- outright, because "XS-S" does climb the ladder and is still XS-Short.
--
-- The fit suffixes stay `numeric` and stay invisible to the letter rail.
-- That is 1 700-odd rows and a bigger population than this migration fixes,
-- but "L-T" means Large in a long cut, and this schema has no column for a
-- cut. Inventing one here would be guessing at a second axis while fixing
-- the first.

ALTER TABLE offer_variant
    ADD COLUMN IF NOT EXISTS size_alpha_max text;

COMMENT ON COLUMN offer_variant.size_alpha_max IS
    'The upper letter when the shop''s label names a span of two sizes '
    '("M/L"), with size_alpha holding the lower. NULL for an ordinary '
    'single letter, where size_alpha is the whole answer.';

COMMENT ON COLUMN offer_variant.size_alpha IS
    'Letter size, canonicalised to the ladder. When size_alpha_max is also '
    'set this is the LOWER end of a span, so a reader that ignores the max '
    'still gets a letter the article is sold in rather than nothing.';

-- -----------------------------------------------------------------------------
-- Expanding a span onto the ladder
-- -----------------------------------------------------------------------------
-- The summary rail stores the letters a shopper can buy, so an M/L article
-- has to contribute both M and L -- otherwise filtering "L" still misses it,
-- and the column would be fixed everywhere except where it is read.
--
-- STRICT would be wrong: the overwhelmingly common call has a NULL max, and
-- it must return the single letter rather than NULL.

CREATE OR REPLACE FUNCTION alpha_size_span(lo text, hi text)
RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN lo IS NULL THEN '{}'::text[]
        WHEN hi IS NULL OR hi = lo THEN ARRAY[lo]
        ELSE coalesce((
            SELECT array_agg(rung ORDER BY n)
              FROM unnest(ARRAY['XXS','XS','S','M','L','XL','XXL',
                                '3XL','4XL','5XL'])
                   WITH ORDINALITY AS t(rung, n)
             WHERE n >= array_position(
                       ARRAY['XXS','XS','S','M','L','XL','XXL',
                             '3XL','4XL','5XL'], lo)
               AND n <= array_position(
                       ARRAY['XXS','XS','S','M','L','XL','XXL',
                             '3XL','4XL','5XL'], hi)), ARRAY[lo])
    END;
$$;

COMMENT ON FUNCTION alpha_size_span(text, text) IS
    'Every rung from lo to hi inclusive, in ladder order; just lo when hi '
    'is NULL. Mirrors mkagg.sizing.ALPHA_LADDER, as alpha_size_rank does.';
