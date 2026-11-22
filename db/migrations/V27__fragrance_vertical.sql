-- -----------------------------------------------------------------------------
-- V27 -- fragrances: a bottle has a volume, and two bottles are one product
-- -----------------------------------------------------------------------------
-- The fourth vertical, and the first served by shops that sell nothing else:
-- e-elixir.mk (WooCommerce, 987 fragrances) and shop.schatze.mk (nopCommerce,
-- ~1 100). `category_kind` has carried 'fragrance' since V1, so the vertical
-- was always expected; this is the schema it needs to arrive.
--
-- Three decisions, each measured against both shops' live data.
--
-- **Volume is a variant axis, not a product axis.** 30ml, 50ml and 100ml of
-- one fragrance are the same article in three bottles, exactly as a hoodie in
-- S/M/L is one garment. They belong under one product page with one chip rail
-- -- which is why this adds a column to `offer_variant` rather than minting
-- three products. The existing table already supports what that costs:
-- `price_minor` and `in_stock` are per-variant, so a 100ml at 6 040 den and a
-- 30ml at 4 240 den are both representable without a schema change. This is
-- the first axis where price genuinely varies per variant; for shoes it never
-- did, and the column was there anyway.
--
-- **Concentration is part of the product's identity, not a facet of it.**
-- Valentino Donna Eau de Parfum and Valentino Donna Eau de Toilette are
-- different liquids at different prices, and a shopper shown one price for
-- "Valentino Donna" has been misinformed. So it sits on `product` and takes
-- part in the uniqueness below, rather than living in `category` where a
-- filter would merge across it.
--
-- **Identity is exact, never fuzzy.** The similarity matcher that joins shoes
-- by title would merge "Born in Roma" with "Born in Roma Intense", which are
-- different fragrances sold side by side. Here the key is spelled out and
-- enforced by a unique index: brand, line, concentration. What makes that
-- workable is that the line name must be normalised *before* insert --
-- Schatze writes "Pour Homme - edt" with the brand only in a separate
-- Manufacturer field, while e-elixir writes "Versace Pour Homme Eau de
-- toilette". Same fragrance, and no index can see that on its own.
--
-- Deliberately absent: leaves for gift sets, scented candles and body mists.
-- All three live inside both shops' fragrance shelves -- "212 Vip Black 100ml
-- EDP + Shower Gel 100ml", a 180g candle, 73 mists at e-elixir alone -- and
-- all three are excluded at ingest for now. A set is not a volume of the
-- bottle it contains, and giving it a leaf here would invite exactly that
-- merge. When they earn a vertical of their own they get rows then.

-- -----------------------------------------------------------------------------
-- The size system a bottle uses
-- -----------------------------------------------------------------------------
-- NOTE: Postgres forbids *using* a new enum value in the transaction that adds
-- it. Nothing below writes 'volume_ml', so this stays a single migration --
-- but anything that does must wait for V28 or later.

ALTER TYPE size_system ADD VALUE IF NOT EXISTS 'volume_ml';

ALTER TABLE offer_variant
    ADD COLUMN IF NOT EXISTS size_ml integer;

COMMENT ON COLUMN offer_variant.size_ml IS
    'Bottle volume in millilitres, the fragrance size axis. size_label keeps '
    'the shop''s own spelling ("30ml", "30 ML") and is what the storefront '
    'renders; this is what makes two shops'' bottles comparable and sortable. '
    'NULL for every other vertical, and for a volume stated in grams -- a '
    'candle is not a smaller bottle of perfume.';

-- Mirrors offer_variant_size_idx: the rail and the filter both only ever care
-- about volumes a shopper can actually buy.
CREATE INDEX IF NOT EXISTS offer_variant_size_ml_idx
    ON offer_variant (size_ml) WHERE in_stock IS NOT FALSE;

-- -----------------------------------------------------------------------------
-- Concentration, and the identity it completes
-- -----------------------------------------------------------------------------

ALTER TABLE product
    ADD COLUMN IF NOT EXISTS concentration text;

COMMENT ON COLUMN product.concentration IS
    'Normalised fragrance concentration: EDP, EDT, EDC, PARFUM, EXTRAIT, '
    'COLOGNE. One spelling per strength, because the shops use several -- '
    'Schatze writes "- edt" and "EDT" and "Eau de Toilette" for one thing. '
    'NOT a place for Elixir, Intense or Intensement: those name the '
    'fragrance, not its strength ("Le Male ELIXIR - Eau de Parfum" is an '
    'EDP), and folding them in here would merge distinct articles. '
    'NULL outside the fragrance vertical.';

-- The exact-identity rule, made real. Partial, so it constrains fragrances
-- and leaves all 28 808 shoes, garments and accessories untouched.
--
-- lower() covers case alone. Everything else -- punctuation, the brand prefix
-- Schatze omits, "Eau de Toilette" against "EDT" -- has to be settled by the
-- matcher before it gets here. The index is the backstop that turns a
-- normalisation bug into a failed insert rather than two product pages for
-- one bottle, or one page for two different ones.
CREATE UNIQUE INDEX IF NOT EXISTS product_fragrance_identity_idx
    ON product (brand_id, lower(model_name), concentration)
 WHERE concentration IS NOT NULL;

-- -----------------------------------------------------------------------------
-- The listing's volume rail
-- -----------------------------------------------------------------------------
-- Same contract as available_sizes_eu and available_sizes_alpha: the listing
-- reads this table and never aggregates over offer_variant at request time.

ALTER TABLE product_price_summary
    ADD COLUMN IF NOT EXISTS available_volumes_ml integer[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN product_price_summary.available_volumes_ml IS
    'Bottle volumes a shopper can actually buy, smallest first. Mirrors '
    'available_sizes_alpha: distinct, in_stock IS NOT FALSE, so a shop that '
    'publishes no availability still contributes its volumes.';

-- -----------------------------------------------------------------------------
-- The vertical's two rows
-- -----------------------------------------------------------------------------
-- A root and one leaf, matching footwear/apparel/accessories. The root is the
-- honest weak answer -- "a fragrance, kind unspecified" -- and mkagg.taxonomy
-- lists it in PARENT_SLUGS so it can fill a gap but never overwrite a leaf.

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT NULL, 'fragrances', 'fragrance'::category_kind,
       'Fragrances', 'Парфеми', 'Parfume'
 WHERE NOT EXISTS (SELECT 1 FROM category WHERE slug = 'fragrances');

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'perfume', 'fragrance'::category_kind,
       'Perfume', 'Парфем', 'Parfum'
  FROM category WHERE slug = 'fragrances'
   AND NOT EXISTS (SELECT 1 FROM category WHERE slug = 'perfume');

-- -----------------------------------------------------------------------------
-- The two merchants
-- -----------------------------------------------------------------------------
-- e-elixir is the first merchant to run on the `woocommerce` API adapter.
-- megasport has been on `woocommerce_html` since V5, because its robots.txt
-- disallows /wp-json/ -- so the API adapter has never served live traffic,
-- and the minor-unit bug it carried was latent rather than wrong in public.

INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, api_requires_permission,
                      robots_checked_at, robots_notes)
SELECT 'eelixir', 'Elixir', 'MK', 'woocommerce', 'https://e-elixir.mk', 'api',
       true, 2.0, false, now(),
       'robots.txt disallows only *?filter_ and &filter_ -- the WooCommerce '
       'Store API at /wp-json/wc/store/v1/ is permitted, unlike megasport. '
       'Discovery uses category pagination, never a filter URL. Per-volume '
       'price, stock and EAN all come from the variation endpoint.'
 WHERE NOT EXISTS (SELECT 1 FROM merchant WHERE slug = 'eelixir');

-- Schatze is seeded inactive: its nopCommerce adapter does not exist yet, and
-- `is_active` is what the scheduler, promote and the serving query all read.
--
-- api_requires_permission records the finding, not a veto. Per-volume price,
-- SKU, GTIN and stock exist only behind
-- POST /shoppingcart/productdetails_attributechange, and robots.txt says
-- `Disallow: /shoppingcart/*`. The static page carries one price -- the
-- preselected, smallest volume -- and renders the sku/gtin/stock elements
-- empty. Whoever activates this merchant decides that question deliberately
-- and records the answer here; a product feed would settle it best, and would
-- also hand us the GTINs that make cross-shop matching exact.
INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, is_active,
                      api_requires_permission, robots_checked_at, robots_notes)
SELECT 'schatze', 'Schatze', 'MK', 'nopcommerce', 'https://shop.schatze.mk',
       'scrape', false, 0.5, false, true, now(),
       'robots.txt: Disallow: /shoppingcart/* -- which is where nopCommerce '
       'serves productdetails_attributechange, the only source of per-volume '
       'price, SKU, GTIN and stock. Also Disallow: /search?, so discovery '
       'must use /parfemi pagination (53 pages) or sitemap.xml. Product and '
       'category pages are allowed. publishes_stock is false until a route '
       'to per-volume availability is settled.'
 WHERE NOT EXISTS (SELECT 1 FROM merchant WHERE slug = 'schatze');
