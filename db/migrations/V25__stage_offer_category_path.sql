-- -----------------------------------------------------------------------------
-- V25 -- the shelf the product page states, carried through the gate
-- -----------------------------------------------------------------------------
-- `merchant_offer.merchant_category_path` had exactly one writer, the facet
-- walk, so a product knew only the listing it was found in. That is enough
-- until a shop publishes a listing that names nothing.
--
-- sport-m and sizeer do. Their department umbrella, `?Segment=NN&Grupa=02`,
-- carries no garment, and 1,010 products were reachable only through it --
-- a quarter of all the clothing on those two shops. They read "Текстил" and
-- the catalogue could say no more than "clothing", while sport-m's own
-- Спецификации table said "Градник", "Дресови-фудбал", "Костим за капење"
-- on the very page the crawler had already fetched and parsed.
--
-- Extending the facet plan could not reach them: the sidebar counts 27
-- subgroups and the navigation links 18, so nine of them -- Градник,
-- Пододело, Дресови among them -- have no `PodGrupa` code to address them
-- by. The page is the only place they are stated.
--
-- Everything reaching the catalogue goes through staging and is rebuilt
-- from these columns on the way out, so a field that does not exist here
-- is silently dropped between the adapter and the offer. It was: the
-- promote-side write landed on a value that was always NULL.
--
-- Nullable on purpose. Four of the six shops state no shelf on the page,
-- and the promote-side COALESCE turns that NULL into "leave the walk's
-- answer alone" rather than an erasure.

ALTER TABLE stage_offer
    ADD COLUMN IF NOT EXISTS category_path text;

COMMENT ON COLUMN stage_offer.category_path IS
    'The shop''s own shelf for this product, in the shop''s words, read off '
    'the product page rather than the listing it was found in (aspnet prints '
    'it as Подгрупа). NULL where the adapter reads no shelf, which must '
    'never overwrite what the facet walk established.';
