-- -----------------------------------------------------------------------------
-- V29 -- how a fragrance was matched
-- -----------------------------------------------------------------------------
-- `merchant_offer.match_method` records what joined an offer to a product, and
-- the six existing values all assume a code: mpn, gtin, merchant_sku, plus
-- fuzzy, image and manual for when there is none.
--
-- Fragrances have no code either shop shares. e-elixir's parent `sku` is its
-- own row number -- "278", "160", "1319" -- and Schatze's is a different
-- internal id for the same bottle, so matching on either joins nothing across
-- shops and risks joining the wrong things within one. What identifies a
-- fragrance is brand, line and concentration, matched exactly:
--
--     Schatze    "Pour Homme - edt"                  + Manufacturer: Versace
--     e-elixir   "Versace Pour Homme Eau de toilette"
--     both       ->  (versace, "pour homme", EDT)
--
-- That is neither a code match nor a fuzzy one, and calling it ''fuzzy'' would
-- be actively misleading: the whole point is that it is exact. These shops
-- stock "Born in Roma", "Born in Roma Intense", "Born in Roma Extradose" and
-- "Born in Roma Ruby" at four different prices, and a similarity score cannot
-- be trusted to keep them apart. An operator reading match_method needs to see
-- which offers were joined by a rule that admits no near misses.

ALTER TYPE match_method ADD VALUE IF NOT EXISTS 'identity';

COMMENT ON TYPE match_method IS
    'What joined an offer to a product. ''mpn'', ''gtin'' and '
    '''merchant_sku'' are code matches; ''identity'' is an exact match on '
    'brand + line + concentration, used for fragrances, where no code is '
    'shared between shops; ''fuzzy'' is a similarity score above threshold; '
    '''image'' and ''manual'' are the fallbacks. Only ''fuzzy'' tolerates a '
    'near miss.';
