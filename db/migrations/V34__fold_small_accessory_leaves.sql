-- Шишиња и термоси and Врвки и нега на обувки join Останата опрема.
--
-- Both sat under the hundred-product threshold the storefront menu uses --
-- 61 and 25 products -- so both were hidden, which made them unreachable by
-- clicking. Three leaves nobody could open is worse than one they can, and
-- "Останата опрема" is the shops' own word for the shelf these belong on.
--
-- `wallets` is deliberately NOT folded. It is smaller still, at 11 products,
-- but a wallet is a thing a shopper comes looking for by name, and the leaf
-- exists because megasport publishes one combined "Ранци и Паричници" facet
-- that only a wallet's own name can be separated out of -- see the ordering
-- note in `taxonomy._RULES`. It becomes visible in the same change.
--
-- The rules and facets move with the data: `taxonomy._RULES` keeps both
-- keyword lists exactly where they were and returns `other_accessories`
-- from them, and the eleven facet entries and seven sport-m subgroup codes
-- are repointed. So a later crawl classifies these the same way rather than
-- recreating the leaves. Measured over 35 873 live offers beforehand: 182
-- classifications move between these leaves and 28 that matched nothing at
-- all now land here, with no other shift.

-- Order matters: the products leave before the rows do, because
-- `product.category_id` references them.
UPDATE product
   SET category_id = (SELECT id FROM category WHERE slug = 'other_accessories'),
       updated_at = now()
 WHERE category_id IN (SELECT id FROM category
                        WHERE slug IN ('bottles_thermos', 'shoe_care_laces'));

-- The leaf now covers rather more than "Друго" promised: bottles, flasks,
-- laces, insoles, cleaning sprays, hair ties, sweatbands, wristbands, phone
-- covers, keyrings and charms.
UPDATE category
   SET name_en = 'Other equipment',
       name_mk = 'Останата опрема',
       name_sq = 'Pajisje të tjera'
 WHERE slug = 'other_accessories';

DELETE FROM category WHERE slug IN ('bottles_thermos', 'shoe_care_laces');
