-- =============================================================================
-- V4 -- Reference data seeded from the Phase 1 recon of the 7 MK stores.
-- Every merchant row below reflects a verified, measured finding.
-- =============================================================================

INSERT INTO currency (code, minor_unit, symbol) VALUES
    ('MKD', 0, 'ден.'),   -- the MK shops configure MKD with 0 decimals
    ('EUR', 2, '€'),
    ('RSD', 0, 'дин.'),
    ('BAM', 2, 'KM'),
    ('HRK', 2, 'kn');

INSERT INTO country (code, name, currency_code, default_locale, is_active) VALUES
    ('MK', 'North Macedonia', 'MKD', 'mk-MK', true),
    ('RS', 'Serbia',          'RSD', 'sr-RS', false),
    ('BA', 'Bosnia and Herzegovina', 'BAM', 'bs-BA', false),
    ('HR', 'Croatia',         'EUR', 'hr-HR', false),
    ('SI', 'Slovenia',        'EUR', 'sl-SI', false);

-- -----------------------------------------------------------------------------
-- Brands, with Cyrillic/Latin aliases for MK search and matching
-- -----------------------------------------------------------------------------

INSERT INTO brand (slug, name, aliases) VALUES
    ('adidas',        'Adidas',        ARRAY['adidas','АДИДАС','Адидас','adidas originals','ADIDAS']),
    ('nike',          'Nike',          ARRAY['nike','НАЈК','Најк','НАЈКИ','nike sportswear']),
    ('puma',          'Puma',          ARRAY['puma','ПУМА','Пума']),
    ('new-balance',   'New Balance',   ARRAY['new balance','НЮ БАЛАНС','Њу Баланс','nb']),
    ('reebok',        'Reebok',        ARRAY['reebok','РИБОК','Рибок']),
    ('converse',      'Converse',      ARRAY['converse','КОНВЕРС','Конверс','all star']),
    ('vans',          'Vans',          ARRAY['vans','ВАНС','Ванс']),
    ('asics',         'Asics',         ARRAY['asics','АСИКС','Асикс']),
    ('under-armour',  'Under Armour',  ARRAY['under armour','УНДЕР АРМОР','ua']),
    ('fila',          'Fila',          ARRAY['fila','ФИЛА','Фила']),
    ('skechers',      'Skechers',      ARRAY['skechers','СКЕЧЕРС']),
    ('jordan',        'Jordan',        ARRAY['jordan','air jordan','ЏОРДАН']);

-- -----------------------------------------------------------------------------
-- Categories -- footwear only for the MVP, tree ready for apparel/fragrance
-- -----------------------------------------------------------------------------

INSERT INTO category (slug, kind, name_en, name_mk, name_sq) VALUES
    ('footwear', 'footwear', 'Footwear', 'Обувки', 'Këpucë');

-- The ::category_kind casts are required, not cosmetic: in a UNION the column
-- type is resolved from the FIRST branch, where a bare 'footwear' is an
-- untyped literal that resolves to text, and the insert then fails with
-- "column kind is of type category_kind but expression is of type text".
INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'sneakers', 'footwear'::category_kind, 'Sneakers', 'Патики', 'Atlete'   FROM category WHERE slug = 'footwear'
UNION ALL
SELECT id, 'running',  'footwear'::category_kind, 'Running',  'Трчање', 'Vrapim'   FROM category WHERE slug = 'footwear'
UNION ALL
SELECT id, 'boots',    'footwear'::category_kind, 'Boots',    'Чизми',  'Çizme'    FROM category WHERE slug = 'footwear'
UNION ALL
SELECT id, 'slides',   'footwear'::category_kind, 'Slides',   'Папучи', 'Pantofla' FROM category WHERE slug = 'footwear';

-- -----------------------------------------------------------------------------
-- Merchants -- adapter assignment is the key recon outcome: 7 stores, 4 adapters
-- -----------------------------------------------------------------------------

-- Adapter 1: "sportvision" -- three stores on one codebase.
-- Verified: JSON-LD Product with manufacturer sku + productID, dataLayer
-- productCode, and per-size stock via <li data-productsize-combid> where the
-- CSS class "disabled" means sold out.
INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, rating, review_count) VALUES
    ('sportvision',  'Sport Vision',  'MK', 'sportvision', 'https://www.sportvision.mk',   'scrape', true, 1.0, 4.1, 0),
    ('sportreality', 'Sport Reality', 'MK', 'sportvision', 'https://www.sportreality.mk',  'scrape', true, 1.0, 4.0, 0),
    ('buzz',         'Buzz Sneakers', 'MK', 'sportvision', 'https://www.buzzsneakers.mk',  'scrape', true, 1.0, 4.2, 0);

-- Adapter 2: "magento" -- dsport.mk. Verified: /graphql is fully open, no auth.
-- Returns sku (= manufacturer code), MKD price, stock_status, and per-size
-- variants with only_x_left_in_stock. Behind Cloudflare but never challenged.
INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, rating, review_count) VALUES
    ('dsport', 'D-Sport', 'MK', 'magento', 'https://www.dsport.mk', 'api', true, 2.0, 4.0, 0);

-- Adapter 3: "woocommerce" -- megasportonlineshop.com. Verified: the public
-- Store API /wp-json/wc/store/products needs no auth and reports
-- currency_minor_unit = 0 for MKD. 665 products in the Патики category.
INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, rating, review_count) VALUES
    ('megasport', 'Megasport', 'MK', 'woocommerce', 'https://megasportonlineshop.com', 'api', true, 2.0, 3.9, 0);

-- Adapter 4: "aspnet_mk" -- sport-m + sizeer, same ASP.NET MVC platform and
-- the same host IP. Sizes come from POST /ProductCatalog/GetVelicini/.
--   sport-m -> Zaliha is a real per-size quantity        => publishes_stock true
--   sizeer  -> Zaliha is null for every size             => publishes_stock FALSE
INSERT INTO merchant (slug, name, country_code, adapter, base_url, source_type,
                      publishes_stock, crawl_rps, rating, review_count) VALUES
    ('sportm', 'Sport-M', 'MK', 'aspnet_mk', 'https://www.sport-m.com.mk', 'api', true,  1.0, 3.8, 0),
    ('sizeer', 'Sizeer',  'MK', 'aspnet_mk', 'https://sizeer.com.mk',      'api', false, 1.0, 4.0, 0);

-- Link the two: identical platform, IP and price for M20325 (6.799,00 ден.).
-- Almost certainly one operator; the UI must badge or collapse them.
UPDATE merchant m SET related_merchant_id = o.id
  FROM merchant o WHERE m.slug = 'sizeer' AND o.slug = 'sportm';
UPDATE merchant m SET related_merchant_id = o.id
  FROM merchant o WHERE m.slug = 'sportm' AND o.slug = 'sizeer';

-- -----------------------------------------------------------------------------
-- Size mappings for the formats actually observed in recon
-- -----------------------------------------------------------------------------

INSERT INTO size_mapping (raw_label, size_eu, notes) VALUES
    ('BEZ VELICINA', NULL, 'dsport one-size articles; emit no size row'),
    ('ONE SIZE',     NULL, 'generic one-size'),
    ('UNI',          NULL, 'generic one-size');

-- UK -> EU for the run returned by sport-m / sizeer GetVelicini, which gives
-- UK as the primary label. EU values use Unicode vulgar fractions upstream.
INSERT INTO size_mapping (raw_label, size_uk, size_eu, notes) VALUES
    ('7.5',  7.5,  41.333, 'sport-m/sizeer UK primary; EU 41 1/3'),
    ('8',    8.0,  42.000, 'sport-m/sizeer UK primary'),
    ('8.5',  8.5,  42.667, 'sport-m/sizeer UK primary; EU 42 2/3'),
    ('9',    9.0,  43.333, 'sport-m/sizeer UK primary; EU 43 1/3'),
    ('9.5',  9.5,  44.000, 'sport-m/sizeer UK primary'),
    ('10',  10.0,  44.667, 'sport-m/sizeer UK primary; EU 44 2/3'),
    ('10.5',10.5,  45.333, 'sport-m/sizeer UK primary; EU 45 1/3'),
    ('11',  11.0,  46.000, 'sport-m/sizeer UK primary'),
    ('11.5',11.5,  46.667, 'sport-m/sizeer UK primary; EU 46 2/3');
