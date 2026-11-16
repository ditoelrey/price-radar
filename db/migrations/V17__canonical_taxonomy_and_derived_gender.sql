-- =============================================================================
-- V17 -- Four canonical footwear categories, and a gender column that can
--        admit it does not know.
--
-- Two problems, one cause.
--
-- 1. CATEGORY WAS FROZEN AT CREATION. `create_product` set category_id once,
--    from `classify(title) or hint`, and nothing ever revised it. Re-sweeping
--    a shop therefore cannot repair a product it already created: sportm's
--    uncategorised count moved 221 -> 223 across a full re-sweep, because the
--    1,348 new products were classified and the old ones were never revisited.
--    2,767 products sat in the generic `footwear` bucket and 489 in no
--    category at all, almost all of them shoes.
--
--    Measured before choosing the shape: four of the six shops put no category
--    word in their titles at all (sportvision, sportreality, sizeer, sportm
--    all title products "adidas Supernova Rise"), and pooling every merchant's
--    title for a product leaves 2,580 of those 2,767 still silent. The title
--    is exhausted as a source. Category here is a property of the facet a
--    product was discovered through, which is why the hint has to survive in
--    `merchant_offer` and the product's category has to be *derived* from the
--    offers rather than stamped once.
--
-- 2. GENDER WAS A DEFAULT MASQUERADING AS DATA. V1 declared it NOT NULL
--    DEFAULT 'unisex', so all 10,731 products claimed unisex and nothing could
--    distinguish "we never looked" from "the shop says unisex" -- and buzz
--    alone lists 279 genuinely unisex adult shoes. Gender is knowable from the
--    same facets as category (title tokens reach 4.9 percent for men, and EU
--    sizes cannot separate men from women at all, since 36-46 is shared), so
--    it is derived in the same pass and stored the same way.
--
-- The taxonomy consolidates to the four buckets MK sports retail actually
-- navigates by -- the tree sportvision and sportreality both publish -- rather
-- than the finest tree any one shop happens to use. sportm and sizeer split
-- sneakers into low-top and high-top; that distinction is derivable for 6.2
-- percent of footwear products, and it is the shop's merchandising decision
-- rather than a property of the shoe, so it is preserved verbatim per offer in
-- `merchant_category_path` and kept out of the canonical tree. A canonical
-- column has to answer the same way whichever shop we met the product through.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- The four canonical footwear leaves
-- -----------------------------------------------------------------------------
-- Slugs, like every other identifier in this schema, are English; name_mk
-- carries what the storefront shows. `sneakers` already exists from V4 and
-- keeps its id, so the 6,315 products already filed there do not move.
--
-- The ::category_kind casts are required in a UNION -- see the note in V4.

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'cleats', 'footwear'::category_kind,
       'Football boots', 'Копачки', 'Këpucë futbolli'
  FROM category WHERE slug = 'footwear'
UNION ALL
SELECT id, 'shoes_boots', 'footwear'::category_kind,
       'Shoes and boots', 'Кондури и чизми', 'Këpucë dhe çizme'
  FROM category WHERE slug = 'footwear'
UNION ALL
SELECT id, 'slides_sandals', 'footwear'::category_kind,
       'Slides and sandals', 'Папучи и сандали', 'Pantofla dhe sandale'
  FROM category WHERE slug = 'footwear'
ON CONFLICT (slug) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Re-file the retiring leaves
-- -----------------------------------------------------------------------------
-- 882 products move. The order matters: category_id is ON DELETE SET NULL, so
-- deleting the old rows first would silently null every one of them instead.
--
-- `running` goes to `sneakers` rather than surviving as its own bucket. Its
-- 129 products came from the weakest rule in the classifier -- the only one
-- that reads the model name instead of the shop's own category word, which is
-- how "Adidas RESPONSE RUNNER 2" became a running shoe while the shop that
-- sells it files it under Патики. The merge retires the rule with the row.

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'sneakers'),
       updated_at = now()
 WHERE p.category_id = (SELECT id FROM category WHERE slug = 'running');

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'shoes_boots'),
       updated_at = now()
 WHERE p.category_id = (SELECT id FROM category WHERE slug = 'boots');

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'slides_sandals'),
       updated_at = now()
 WHERE p.category_id = (SELECT id FROM category WHERE slug = 'slides');

DELETE FROM category WHERE slug IN ('running', 'boots', 'slides');

-- The parent stays, and keeps its meaning: a shoe whose kind is unspecified.
-- The 2,767 products filed directly against it are not an error to be cleared
-- -- they are shoes we have not yet resolved to a leaf, and products arriving
-- between facet walks will keep landing here. Forcing them into a leaf is how
-- a pack of socks came to be filed under sneakers in the first place (V10).
-- A storefront leaf filter matches an exact category_id, so asking for
-- Копачки returns cleats and never this pile.
COMMENT ON TABLE category IS
    'Two levels, deliberately. `kind` decides what the storefront serves; the '
    'leaf decides what it is. The parent `footwear` row is itself a valid '
    'value meaning "a shoe, kind unspecified" -- do not promote those rows to '
    'a plausible leaf.';

-- -----------------------------------------------------------------------------
-- The shop's own words, per offer
-- -----------------------------------------------------------------------------
-- Where a product was found is evidence, and until now it was thrown away
-- after `create_product` read it once. These two columns keep it on the offer,
-- which is the row that actually has a shop and a URL, so the product's
-- category and gender can be re-derived at any time from the union of its
-- offers instead of depending on which shop we happened to meet first.
--
-- They hold the shop's vocabulary verbatim ("Патики-ниски", "Zheni"), not a
-- canonical slug. Deliberately: the whole point is to keep what the shop said
-- separate from what we concluded, so a later reading of the same evidence can
-- disagree with this one without having lost the evidence.

ALTER TABLE merchant_offer
    ADD COLUMN merchant_category_path text,
    ADD COLUMN merchant_gender        text;

COMMENT ON COLUMN merchant_offer.merchant_category_path IS
    'The shop''s own category path for this offer, verbatim, from the facet it '
    'was discovered through. Never a canonical slug.';
COMMENT ON COLUMN merchant_offer.merchant_gender IS
    'The shop''s own department for this offer, verbatim ("Mazhi", "Zheni", '
    '"deca"). Never a canonical gender_t value.';

-- Discovery already carries a category hint through staging (V12). Gender
-- needs the same channel, or a new sweep would land products that the
-- derivation then has to guess at.
ALTER TABLE stage_offer
    ADD COLUMN gender_hint text;

COMMENT ON COLUMN stage_offer.gender_hint IS
    'Gender implied by the facet discovery found this product through. Used by '
    'the loader exactly as category_hint is: as context, never as a guess.';

-- -----------------------------------------------------------------------------
-- Gender: nullable, because unknown is the honest answer for most of it
-- -----------------------------------------------------------------------------
-- Dropping the default and nulling every row is not data loss. There is no
-- data here to lose: every one of the 10,731 values is the DEFAULT that V1
-- wrote, and none of them was ever derived from anything. Keeping them would
-- mean 10,731 unverified claims that look settled, which is precisely the
-- failure V10's comment on product.category_id warns about.
--
-- Checked before doing it: `gender` is not used in matching. matching.py
-- blocks the fuzzy fallback on brand alone -- the docstring's claim about
-- "+gender where both sides declare it" describes an intention, not the code
-- -- and every match in the catalogue is an exact `mpn` match anyway, so the
-- fuzzy path has never fired. product_block_idx keeps the column for the day
-- that changes.

ALTER TABLE product
    ALTER COLUMN gender DROP DEFAULT,
    ALTER COLUMN gender DROP NOT NULL;

UPDATE product SET gender = NULL;

COMMENT ON COLUMN product.gender IS
    'NULL means no facet or title told us. ''unisex'' is a positive finding -- '
    'the shop lists the article in both an adult men''s and an adult women''s '
    'department -- not a fallback for silence.';

-- -----------------------------------------------------------------------------
-- Where each value came from
-- -----------------------------------------------------------------------------
-- What makes re-derivation safe to run repeatedly. A facet-derived category
-- must not be overwritten by a weaker title guess on the next pass, and when a
-- product is mislabelled this is the column that says which source to go and
-- fix. Without it, re-derivation either clobbers good values or cannot tell
-- whether it is allowed to.

ALTER TABLE product
    ADD COLUMN category_source text
        CHECK (category_source IN ('facet', 'title')),
    ADD COLUMN gender_source   text
        CHECK (gender_source IN ('facet', 'title'));

COMMENT ON COLUMN product.category_source IS
    'Which evidence set this category: ''facet'' (the shop''s own department, '
    'strong) or ''title'' (a keyword in the product name, weak). NULL '
    'alongside a NULL category_id means nothing has said yet.';

-- Everything already in the table was set from a title keyword or a hint by
-- the old frozen path; marking it `title` means the first facet walk is free
-- to improve on it, and nothing claims facet-strength evidence it never had.
UPDATE product SET category_source = 'title' WHERE category_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Browsing index
-- -----------------------------------------------------------------------------
-- The storefront's new filters are category and gender together. The existing
-- product_block_idx leads with brand_id, which does not serve that query.

CREATE INDEX product_browse_idx ON product (category_id, gender);
