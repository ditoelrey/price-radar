-- Gloves get their own leaf, and the two buckets they were mixed into get
-- names that match what is left in them.
--
-- `protective_gear` held four unrelated intents in 444 products: 298 gloves,
-- 87 shin and body guards, 23 helmets and 20 pieces of eyewear. A shopper
-- looking for ski gloves was shown goalkeeper gloves, shin guards and a bike
-- helmet on the same shelf.
--
-- **Why gloves and not winter gloves.** The obvious split is cold-weather
-- gloves into the headwear leaf and sport gloves into the training one. It
-- cannot be done from what the shops publish. Measured over all 298, with
-- title, `merchant_category_path` and `product_url` read together and a wide
-- cold-weather vocabulary (zimski, thermal, insulated, knit, fleece, storm,
-- primaloft, mitten, ski): 66 state a sport kind, 49 state cold weather, and
-- 183 state nothing at all -- they are "Brugi Rakavici Crni", brand plus
-- article plus colour. No merchant publishes a winter-glove shelf either:
-- `golmanski-rakavici` is the only glove kind any of them separates, 62
-- offers across two shops, against 141 offers on a generic `Ракавици` shelf.
--
-- So the leaf is the question the evidence can answer -- "is this a glove",
-- true for 298 of 298 -- rather than the one it cannot. It is also the word
-- four of the six shops use for the shelf, and the one a shopper types. A
-- winter/sport split later divides a clean leaf instead of un-mixing two.
--
-- No `product.category_id` is touched here. This adds one row and edits two
-- labels; `mkagg.derive.rederive` moves the products afterwards, reading the
-- `merchant_offer` rows already stored. Nothing is re-crawled.

INSERT INTO category (parent_id, slug, kind, name_en, name_mk, name_sq)
SELECT id, 'gloves', 'accessory'::category_kind,
       'Gloves', 'Ракавици',
       'Doreza'                                         FROM category WHERE slug = 'accessories'
ON CONFLICT (slug) DO NOTHING;

-- What is left once the gloves leave: helmets, eyewear and the guards.
-- "Заштитници" rather than "заштита": the leaf holds шин guards, костобрани,
-- стегачи and суспензори, which are articles, not a property.
UPDATE category
   SET name_en = 'Helmets, eyewear and guards',
       name_mk = 'Кациги, наочари и заштитници',
       name_sq = 'Helmeta, syze dhe mbrojtëse'
 WHERE slug = 'protective_gear';

-- "фитнес" undersold it: the leaf holds jump ropes, push-up bars, yoga mats,
-- pumps and training aids alongside the balls.
UPDATE category
   SET name_en = 'Balls and training equipment',
       name_mk = 'Топки и тренинг опрема',
       name_sq = 'Topa dhe pajisje stërvitore'
 WHERE slug = 'balls_training';
