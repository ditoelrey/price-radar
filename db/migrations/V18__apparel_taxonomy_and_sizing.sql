-- =============================================================================
-- V18 -- The apparel vertical: eleven categories, and a size model that can
--        hold a jumper.
--
-- Recon first, as with V17. Across the six shops the apparel facets hold
-- 17,035 listings -- more than the entire footwear catalogue -- and the
-- counts were checked against a manual audit: megasport, sport-m, sizeer and
-- sportreality matched to the product, sportvision's women and kids matched
-- exactly, and buzz (which had never been counted) came to 833/936/351.
--
-- Two things that recon settled, which this migration is shaped by.
--
-- 1. THE SHOPS HAVE ALREADY CONSOLIDATED. sportvision runs legacy and current
--    slugs side by side -- `dolen-del-trenerki` (307 men) next to
--    `dolni-delovi-trenerki-` (307, the same products), `jakna` + `elek` next
--    to `jakni-i-eleci` -- and the current ones are merged exactly the way
--    this tree is. So these eleven are not our invention imposed on six
--    shops; they are what the largest of them already decided, and the others
--    map onto cleanly.
--
-- 2. APPAREL SIZES ARE NOT SHOE SIZES, AND THE DIFFERENCE IS NOT A BOUND.
--    `normalize_size` already refuses anything outside EU 16-60, which keeps
--    heights (116, 152, 176) out of `size_eu`. It cannot keep out a women's
--    dress size 38, because 38 is a perfectly plausible shoe size -- and
--    measured in the live catalogue, 148 apparel variants and 28 accessory
--    variants already claim an EU shoe size they do not have. A shopper
--    filtering footwear by EU 38 gets trousers. Only knowing the product is
--    not footwear can stop that, so this migration adds the columns that make
--    an apparel size expressible and repairs the rows already affected.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- The eleven canonical apparel categories
-- -----------------------------------------------------------------------------
-- `apparel` and its one child `leggings` already exist from V10, which added
-- somewhere truthful to put the things that are not shoes. The child is
-- reused rather than replaced -- it already holds products -- and renamed to
-- the consolidated label the shops use.

UPDATE category
   SET name_en = 'Leggings and cycling shorts',
       name_mk = 'Хеланки и бициклистички',
       name_sq = 'Getat dhe çiklizëm'
 WHERE slug = 'leggings';

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'tshirts', 'apparel'::category_kind,
       'T-shirts', 'Маици', 'Bluza'                       FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'hoodies', 'apparel'::category_kind,
       'Hoodies and sweatshirts', 'Дуксери и блузони', 'Duks dhe pulovra'
                                                        FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'jackets', 'apparel'::category_kind,
       'Jackets and vests', 'Јакни и елеци', 'Xhaketa dhe jelekë'
                                                        FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'trousers', 'apparel'::category_kind,
       'Trousers and joggers', 'Долни делови и панталони', 'Pantallona'
                                                        FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'tracksuits', 'apparel'::category_kind,
       'Tracksuits', 'Тренерки', 'Kostume sportive'      FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'shorts', 'apparel'::category_kind,
       'Shorts', 'Шорцеви', 'Pantallona të shkurtra'     FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'sports_bras', 'apparel'::category_kind,
       'Sports bras and tops', 'Градници и топови', 'Sutjena sportive'
                                                        FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'underwear', 'apparel'::category_kind,
       'Underwear', 'Долна облека', 'Të brendshme'       FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'dresses_skirts', 'apparel'::category_kind,
       'Dresses and skirts', 'Фустани и сукњи', 'Fustane dhe funde'
                                                        FROM category WHERE slug = 'apparel'
UNION ALL
SELECT id, 'swimwear', 'apparel'::category_kind,
       'Swimwear', 'Костими за капење', 'Rroba banje'    FROM category WHERE slug = 'apparel'
ON CONFLICT (slug) DO NOTHING;

-- Sports bras and dresses are shown in the women's and kids' columns of the
-- storefront nav and left out of the men's. That restriction lives with the
-- nav, in `web/src/lib/navigation.ts`, not here: it is a statement about one
-- menu, and a column here would be data nothing reads.

-- -----------------------------------------------------------------------------
-- How a size is expressed
-- -----------------------------------------------------------------------------
-- Measured on all six shops, by fetching apparel products through the real
-- adapters:
--
--   sportvision   S M L XL 2XL 3XL      7-8г. 9-10г. 11-12г. 14-15г.
--   sportreality  S..3XL, SM MD LG      12-13г. AND 6Y 8Y 10Y AND 4 5 6 7 AND 128
--   buzz          S..2XL                7-8г. .. 14-15г.
--   megasport     S M L XL              7
--   sport-m       S M L XL XXL          12-18 мес. 1-2 год. 2-3 год.
--   sizeer        XL ..                 same as sport-m
--
-- Four systems, and one shop using four of them at once. `size_label` keeps
-- the shop's own word and is what the storefront shows; these columns are
-- what makes two shops' sizes comparable.

CREATE TYPE size_system AS ENUM (
    'alpha',     -- XS S M L XL XXL 3XL
    'age',       -- a range in months, however the shop spelled it
    'height',    -- body height in centimetres: 86, 128, 164
    'eu_shoe',   -- the footwear case, already in size_eu
    'numeric',   -- a bare number we could not place
    'one_size'
);

ALTER TABLE offer_variant
    ADD COLUMN size_system         size_system,
    ADD COLUMN size_alpha          text,
    ADD COLUMN size_height_cm      smallint,
    ADD COLUMN size_age_min_months smallint,
    ADD COLUMN size_age_max_months smallint;

COMMENT ON COLUMN offer_variant.size_system IS
    'Which system size_label is written in. NULL means we have not read it; '
    'that is a different thing from ''numeric'', which means we read it and '
    'could not tell what the number counts.';
COMMENT ON COLUMN offer_variant.size_alpha IS
    'Letter size normalised to one spelling: sportreality writes both '
    '"S/M/L" and "SM/MD/LG", and sport-m writes "XXL" where sportvision '
    'writes "2XL". The shop''s own spelling stays in size_label.';
COMMENT ON COLUMN offer_variant.size_height_cm IS
    'Body height in centimetres. Deliberately NOT size_cm, which is footwear '
    'insole length -- a 128 there would describe a 128 cm foot, which is the '
    'same category error size_eu already refuses.';
COMMENT ON COLUMN offer_variant.size_age_min_months IS
    'Months, not years, because "12-18 мес." exists and years divide into it '
    'exactly: "7-8г." is 84 to 96.';

-- Browsing apparel means filtering by one of these, so each gets an index
-- over the rows that actually carry it.
CREATE INDEX offer_variant_size_alpha_idx  ON offer_variant (size_alpha)
    WHERE size_alpha IS NOT NULL;
CREATE INDEX offer_variant_size_height_idx ON offer_variant (size_height_cm)
    WHERE size_height_cm IS NOT NULL;
CREATE INDEX offer_variant_size_age_idx
    ON offer_variant (size_age_min_months, size_age_max_months)
    WHERE size_age_min_months IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Children's sizes: the conversion, taken from the merchants
-- -----------------------------------------------------------------------------
-- sport-m and sizeer publish both sides of this in one record:
--
--   {"Velicina":"86", "EvropskaVelicina":"12-18 мес.", "VelicinaOpis":"86 / 12-18 мес."}
--
-- `Velicina` is the height, `EvropskaVelicina` the age the shop pairs it
-- with. The other four shops state one side only -- sportvision and buzz give
-- ages, megasport gives a bare number -- so this table is what lets a shopper
-- filter by either.
--
-- Every row below was harvested from those two shops' live size payloads, 24
-- products sampled, each pair seen between 2 and 10 times. That matters more
-- than it sounds: a chart copied out of a growth table would be a claim about
-- children, while this is a claim about what these shops mean by "140", which
-- is the only thing the filter has to get right.
--
-- It is a table rather than a constant so the apparel sweep can extend it
-- from the same evidence. 110 cm is absent because the sample never showed
-- it, not because it does not exist.
--
-- Nothing derived from this is ever written onto a variant. A variant records
-- what its shop said; the storefront joins through here to match the other
-- representation at query time. Same separation as category_source in V17.

CREATE TABLE kids_size_chart (
    height_cm      smallint PRIMARY KEY,
    age_min_months smallint NOT NULL,
    age_max_months smallint NOT NULL,
    CHECK (age_min_months < age_max_months)
);

COMMENT ON TABLE kids_size_chart IS
    'Height-to-age mapping as sport-m and sizeer publish it, used to answer '
    'a filter in the representation the shopper chose. Learned from merchant '
    'payloads, extended by the sweep, never written onto a variant.';

INSERT INTO kids_size_chart (height_cm, age_min_months, age_max_months) VALUES
    ( 86,  12,  18),
    ( 92,  12,  24),
    ( 98,  24,  36),
    (104,  36,  48),
    (116,  60,  72),
    (122,  72,  84),
    (128,  84,  96),
    (134,  96, 108),
    (140, 108, 120),
    (146, 120, 132),
    (152, 132, 144),
    (158, 144, 156),
    (164, 156, 168),
    (170, 168, 180),
    (176, 180, 192);

-- -----------------------------------------------------------------------------
-- Repair: the EU sizes that are not shoe sizes
-- -----------------------------------------------------------------------------
-- 148 apparel and 28 accessory variants carry a size_eu taken from labels
-- like '38', '34', '44' -- EU *clothing* sizes, stored where EU shoe sizes
-- live. The label itself is correct and stays; only the claim goes.
--
-- Scoped to products whose category positively says they are not footwear.
-- A product with no category is left alone: unknown is not the same as
-- wrong, and nulling those would throw away real shoe sizes on the 203
-- products nothing has classified yet.

UPDATE offer_variant v
   SET size_eu = NULL
  FROM merchant_offer o, product p, category c
 WHERE v.offer_id = o.id
   AND o.product_id = p.id
   AND p.category_id = c.id
   AND c.kind <> 'footwear'
   AND v.size_eu IS NOT NULL;

COMMENT ON COLUMN offer_variant.size_eu IS
    'EU shoe size, and only ever that. Bounded to 16-60 by normalize_size, '
    'and cleared on products known not to be footwear -- a bound alone '
    'cannot tell a dress size 38 from a shoe size 38.';
