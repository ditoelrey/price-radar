-- -----------------------------------------------------------------------------
-- V22 -- a third evidence source: a person
-- -----------------------------------------------------------------------------
-- V17 gave the taxonomy two sources, the shop's facet and the product title,
-- and ranked them. Both are automatic, and both are wrong when the shop's own
-- data contradicts itself.
--
-- The case that forced this. Sport Reality sells 150243 at
-- `/mk/gradnik/150243-puma-wardrobe-essentials`, badges it ГРАДНИК, files it
-- under Текстил > Градник и топ > Градник -- and describes it, on the same
-- page, as a "женска lifestyle slim маица". Its shelving says bra and its
-- prose says t-shirt. The title ("Puma Wardrobe Essentials") names no garment
-- at all, so neither automatic source can reach the right answer: the facet
-- is wrong and the title is silent.
--
-- Parsing descriptions is not the fix. A bra listing routinely describes the
-- top worn over it, so the field is weaker evidence than either source we
-- already rank -- it would lose more products than it rescued.
--
-- So: let a person decide, and record that a person decided. `manual` outranks
-- both, and `rederive` leaves it alone. That is the honest shape. The
-- alternative on offer was to write 'facet' over the corrected row, which
-- `rederive` already preserves when no offer carries a facet -- and which
-- would have been this schema telling itself the shop said something it never
-- said.

ALTER TABLE product
    DROP CONSTRAINT IF EXISTS product_category_source_check,
    DROP CONSTRAINT IF EXISTS product_gender_source_check;

ALTER TABLE product
    ADD CONSTRAINT product_category_source_check
        CHECK (category_source IN ('facet', 'title', 'manual')),
    ADD CONSTRAINT product_gender_source_check
        CHECK (gender_source IN ('facet', 'title', 'manual'));

COMMENT ON COLUMN product.category_source IS
    'Which evidence set this category: ''facet'' (the shop''s own department, '
    'strong), ''title'' (a keyword in the product name, weak), or ''manual'' '
    '(a person, after the automatic sources disagreed or were silent -- '
    'rederive never overwrites one). NULL alongside a NULL category_id means '
    'nothing has said yet.';

COMMENT ON COLUMN product.gender_source IS
    'As category_source: ''facet'', ''title'', or ''manual''.';

-- -----------------------------------------------------------------------------
-- The correction itself
-- -----------------------------------------------------------------------------
-- Applied here rather than by hand so it survives a rebuild of the database.
-- A hand-run UPDATE would be undone by the next `derive` pass and lost
-- entirely by anyone restoring from migrations.
--
-- Matched on the slug, which is stable, and guarded so re-running changes
-- nothing. If the product is gone the statement is a no-op rather than an
-- error: a correction to a row that no longer exists is not a failure.

UPDATE product p
   SET category_id = (SELECT id FROM category WHERE slug = 'tshirts'),
       category_source = 'manual',
       updated_at = now()
 WHERE p.slug = 'puma-wardrobe-essentials-62974230'
   AND p.category_id IS DISTINCT FROM
       (SELECT id FROM category WHERE slug = 'tshirts');
