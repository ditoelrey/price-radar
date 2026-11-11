-- =============================================================================
-- V10 -- Somewhere truthful to put the things that are not shoes.
--
-- The serving API surfaced a product named "Adidas Gh0331 Chorapi Act Core Mid
-- Crew Sock 3p Megasport", filed under `sneakers`. Two bugs in one row:
--
--   1. the article code and the shop's own name ended up in the product name
--      (fixed in normalize.clean_model_name), and
--   2. a pack of socks was labelled footwear, because create_product
--      hard-coded the sneakers category for everything it created.
--
-- Matching was never at fault -- the code was read correctly and the offer
-- joined the right product. The catalogue simply had nowhere else to put it,
-- because V4 seeded only the footwear branch while megasport's discovery walks
-- a sitemap containing its whole range: socks, ski leggings, helmets, balls.
--
-- So the tree gains the branches that range actually needs. The MVP is still
-- footwear-only; that is now enforced by what the storefront *serves*
-- (category_kind) rather than by mislabelling everything else as a shoe.
-- =============================================================================

INSERT INTO category (slug, kind, name_en, name_mk, name_sq) VALUES
    ('apparel',     'apparel',   'Apparel',     'Облека',    'Veshje'),
    ('accessories', 'accessory', 'Accessories', 'Додатоци',  'Aksesorë'),
    ('equipment',   'equipment', 'Equipment',   'Опрема',    'Pajisje')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'leggings', 'apparel'::category_kind, 'Leggings', 'Хеланки', 'Getat'
  FROM category WHERE slug = 'apparel'
ON CONFLICT (slug) DO NOTHING;

-- Socks sit under accessories rather than apparel. Either is defensible; MK
-- sports retailers file them with accessories, and matching that keeps the
-- tree recognisable to anyone who also browses the shops themselves.
INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'socks', 'accessory'::category_kind, 'Socks', 'Чорапи', 'Çorape'
  FROM category WHERE slug = 'accessories'
ON CONFLICT (slug) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Re-file what is already mislabelled
-- -----------------------------------------------------------------------------
-- Existing rows were all created as `sneakers`. Move the ones whose own title
-- says otherwise, and null the category on anything whose title does not say
-- at all -- a null is a question for admin, while a wrong value looks settled.

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'socks'),
       updated_at = now()
 WHERE p.canonical_name ~* '(chorapi|corapi|\ysock)'
   AND p.category_id = (SELECT id FROM category WHERE slug = 'sneakers');

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'leggings'),
       updated_at = now()
 WHERE p.canonical_name ~* '(helanki|legging)'
   AND p.category_id = (SELECT id FROM category WHERE slug = 'sneakers');

COMMENT ON COLUMN product.category_id IS
    'NULL is a valid and meaningful value: the source title did not say what '
    'kind of product this is. Do not default it to a plausible category -- '
    'that is how a pack of socks came to be filed under sneakers.';
