-- -----------------------------------------------------------------------------
-- V30 -- one line, two audiences, two bottles
-- -----------------------------------------------------------------------------
-- V27 made brand + line + concentration unique for fragrances, on the reading
-- that those three name the article. For 683 of 690 products they do. For
-- seven they do not, and the seven are all the same shape:
--
--     Ajmal Amaze Eau de parfum for men     100ml   2 145 den
--     Ajmal Amaze Eau de parfum for women    75ml   3 065 den
--
-- The Arabic houses -- Ajmal, Armaf, Lattafa -- sell one line in a men's and
-- a women's version, and Dolce & Gabbana does it with Devotion. Different
-- compositions, different bottles, different prices. `mkagg.fragrance`
-- strips "for women" out of the line name, because that is what lets
-- e-elixir's "Moschino Toy 2 Eau de parfum for women" meet Schatze's "Toy 2
-- - edt" -- 243 of e-elixir's titles state an audience and only 12 percent
-- of Schatze's do. So the audience cannot live in the line name, and the
-- index has to carry it instead.
--
-- Gender rather than the title's wording, because the shops do not agree on
-- the wording: one writes "for men", the other "за мажи", the third says
-- nothing and files the bottle on a men's shelf. The derived gender is the
-- one value all three produce.
--
-- NOT a straight equality in the matcher, though, and that distinction is
-- the point of `mkagg.load.promote.genders_conflict`. e-elixir marks a
-- fragrance `unisex` when it appears in both its departments -- 218 of 690 --
-- while Schatze files most things under one gender. Requiring the genders to
-- match would split nearly a third of the catalogue into two product pages
-- per bottle. Only an explicit men-versus-women pair conflicts; unisex,
-- kids and NULL conflict with nothing. The index below is the backstop for
-- what that matcher decides, not the rule itself.

DROP INDEX IF EXISTS product_fragrance_identity_idx;

CREATE UNIQUE INDEX IF NOT EXISTS product_fragrance_identity_idx
    ON product (brand_id, lower(model_name), concentration, gender)
 WHERE concentration IS NOT NULL;

COMMENT ON INDEX product_fragrance_identity_idx IS
    'A fragrance is brand + line + concentration + audience. The first '
    'three are read from the title and stable; gender is derived and may be '
    'revised, which is why the matcher treats it as a veto on a candidate '
    'rather than part of a lookup key -- a product whose gender changes must '
    'not become unreachable and get minted a second time.';
