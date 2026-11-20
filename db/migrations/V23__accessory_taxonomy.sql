-- -----------------------------------------------------------------------------
-- V23 -- the third vertical: Опрема
-- -----------------------------------------------------------------------------
-- Two kinds become one, and the one that survives gets leaves.
--
-- The catalogue held `accessory` (92 products, two leaves) and `equipment`
-- (13 products, one leaf) as separate kinds, and the storefront nav listed
-- only `equipment` -- so the smaller of the two was the one shoppers could
-- reach and the larger was invisible. Both halves came in incidentally,
-- swept up by footwear and apparel walks rather than by any plan of their
-- own, which is also why gender is NULL on 99 of those 105 offers.
--
-- `accessory` survives because it holds seven times as many rows. The
-- `equipment` enum value stays in `category_kind` unused: dropping a value
-- from an enum in place is not worth a table rewrite for a name nothing
-- reads.
--
-- -----------------------------------------------------------------------------
-- The shape of the leaves
-- -----------------------------------------------------------------------------
-- Eleven leaves, from a recon of all six shops' own equipment sections. Two
-- forces shaped the list, both the same one that shaped V18.
--
-- **A leaf can be no finer than the coarsest facet that feeds it.** Megasport
-- publishes one facet, "Ранци и Паричници", for backpacks and wallets
-- together. `wallets` is a separate leaf anyway, because wallet-led shops are
-- coming, but it can only be filled from titles on that shop -- see the
-- `wallets` rules in `mkagg.taxonomy`, which run before `bags_backpacks` so
-- the narrower word wins.
--
-- **Thin leaves are defined but not shown.** `bottles_thermos`, `swim_gear`,
-- `shoe_care_laces` and `wallets` each draw on two or three shops and may
-- come in under a hundred products. They exist here so the data has somewhere
-- truthful to go; whether the menu offers them is decided in
-- `web/src/lib/navigation.ts`, where showing one is a one-line change and
-- costs no migration. An entry serving six percent of the stock reads as an
-- empty site rather than an unfinished one.
--
-- Winter hats are deliberately *not* their own leaf. Only Sizeer facets
-- "Зимски капи" apart from "Капи"; Sport Vision and buzz publish a single
-- merged "Качкети и капи", so the split would have been fed by one shop's
-- facets and guesswork everywhere else.
--
-- Pet accessories and Funko POP! figures are not here, and not crawled.
-- They appear only at Sizeer and Sport-M, which are one operator on one host,
-- so neither can ever carry a second independent price -- and a comparison
-- site with one seller has nothing to compare. They are also not sporting
-- goods by any reading.
--
-- The Albanian names are a best effort and worth a native reading before the
-- `sq` locale is ever served; the Macedonian and English ones are the pair
-- the storefront and the API actually use today.

-- -----------------------------------------------------------------------------
-- 1. The parent
-- -----------------------------------------------------------------------------
-- Renamed to match its vertical, as `footwear` is "Обувки" and `apparel` is
-- "Облека". It keeps its slug: that is an identifier and travels in URLs.

UPDATE category
   SET name_en = 'Equipment and accessories',
       name_mk = 'Опрема',
       name_sq = 'Pajisje dhe aksesorë'
 WHERE slug = 'accessories';

-- -----------------------------------------------------------------------------
-- 2. The leaves
-- -----------------------------------------------------------------------------
-- `socks` already exists from V10 and is already filed under `accessory`, so
-- it is left alone rather than reinserted.

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'caps_hats', 'accessory'::category_kind,
       'Caps, hats and bandanas', 'Капи, качкети и бандани',
       'Kapele dhe bandana'                             FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'bags_backpacks', 'accessory'::category_kind,
       'Bags and backpacks', 'Торби и ранци',
       'Çanta dhe çanta shpine'                         FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'wallets', 'accessory'::category_kind,
       'Wallets', 'Паричници',
       'Portofola'                                      FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'protective_gear', 'accessory'::category_kind,
       'Helmets, eyewear and gloves', 'Кациги, наочари и ракавици',
       'Helmeta, syze dhe doreza'                       FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'swim_gear', 'accessory'::category_kind,
       'Swimming gear', 'Опрема за пливање',
       'Pajisje notimi'                                 FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'balls_training', 'accessory'::category_kind,
       'Balls and training gear', 'Топки и фитнес опрема',
       'Topa dhe pajisje stërvitore'                    FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'bottles_thermos', 'accessory'::category_kind,
       'Bottles and flasks', 'Шишиња и термоси',
       'Shishe dhe termose'                             FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'skates_scooters', 'accessory'::category_kind,
       'Skates and scooters', 'Ролери и тротинети',
       'Patina dhe trotinet'                            FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'shoe_care_laces', 'accessory'::category_kind,
       'Laces and shoe care', 'Врвки и нега на обувки',
       'Lidhëse dhe kujdes këpucësh'                    FROM category WHERE slug = 'accessories'
UNION ALL
SELECT id, 'other_accessories', 'accessory'::category_kind,
       'Other accessories', 'Друго',
       'Të tjera'                                       FROM category WHERE slug = 'accessories'
ON CONFLICT (slug) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3. Fold `equipment` into the parent
-- -----------------------------------------------------------------------------
-- Its thirteen products move to "Опрема, kind unspecified", which is what the
-- `equipment` leaf meant anyway. They keep whatever the next derive pass
-- makes of them: none carries a facet yet, so none is being downgraded.
--
-- `category_source` is left as it is. A product whose category came from a
-- title keyword still did; moving it between two catch-alls is not new
-- evidence and must not claim to be. A `manual` row (V22) is untouched for
-- the same reason -- there are none in this kind today, and if one appears
-- later this statement would quietly overwrite a person's decision, so it is
-- excluded explicitly.

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'accessories'),
       updated_at = now()
 WHERE p.category_id = (SELECT id FROM category WHERE slug = 'equipment')
   AND coalesce(p.category_source, '') <> 'manual';

-- Only once nothing points at it. A row still in use is a sign the move
-- above did not do what it claimed, and deleting it would take the evidence
-- with it.
DELETE FROM category c
 WHERE c.slug = 'equipment'
   AND NOT EXISTS (SELECT 1 FROM product p WHERE p.category_id = c.id)
   AND NOT EXISTS (SELECT 1 FROM category k WHERE k.parent_id = c.id);

COMMENT ON TABLE category IS
    'The canonical tree. Three kinds are served: footwear, apparel and '
    'accessory. The equipment kind was folded into accessory by V23; its '
    'enum value survives unused.';
