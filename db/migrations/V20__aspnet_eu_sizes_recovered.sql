-- =============================================================================
-- V20 -- The EU sizes sport-m and sizeer had, that we filed as UK.
--
-- Found from the storefront. "Adidas Tensaur Sport 2.0" listed Sport-M first
-- at 1 195 ден. with two sizes available, and the shop's own page offers EU
-- 34 and EU 35 -- but clicking EU 34 in our size filter made the Sport-M
-- offer vanish, and the page explained that Sport-M "does not have EU 34".
-- The clue was in the label: every other shop read "from EU 28", Sport-M
-- read "from 34", with no EU.
--
-- The cause is in the shape of the size payload. `Velicina` is the
-- platform's primary label and what it means depends on the row:
--
--     {"Velicina": "7.5", "EvropskaVelicina": "41⅓"}   <- UK, then EU
--     {"Velicina": "34",  "EvropskaVelicina": null}     <- EU, and only EU
--
-- The adapter had `Velicina` documented as the UK size and read it that way
-- always, so when the shop served a child's shoe the EU size went into
-- `size_uk`. There it failed `normalize_size`'s 16-60 bound -- because UK
-- sizes stop around 15 -- and the EU size was lost. The offer kept its
-- label, lost its size, and disappeared from every size-filtered page.
--
-- 3 873 variants across 846 products, every one of them sport-m or sizeer.
--
-- That bound is also what makes the repair safe: a `size_uk` inside the EU
-- range cannot be a UK size, so these rows are EU sizes in the wrong column.
-- =============================================================================

-- Recover the size. Scoped to products not positively known to be something
-- other than footwear -- a NULL category is left in, the same asymmetry the
-- storefront applies, because 203 products have no category and most of them
-- are shoes.
UPDATE offer_variant v
   SET size_eu = v.size_uk,
       size_uk = NULL
  FROM merchant_offer o
  JOIN product p        ON p.id = o.product_id
  LEFT JOIN category c  ON c.id = p.category_id
 WHERE v.offer_id = o.id
   AND v.size_eu IS NULL
   AND v.size_uk IS NOT NULL
   AND (c.kind IS NULL OR c.kind = 'footwear');

-- Whatever is left is a UK claim we could never have made honestly: the
-- column is only ever reachable by a value inside the EU range, and the
-- serving API has never read it. Clearing it stops a 34 masquerading as a
-- UK size on an apparel row, where V18 deliberately removed the EU claim.
UPDATE offer_variant
   SET size_uk = NULL
 WHERE size_uk IS NOT NULL;

COMMENT ON COLUMN offer_variant.size_uk IS
    'UK shoe size. Empty in practice: normalize_size bounds sizes to EU '
    '16-60 and UK sizes stop around 15, so no real UK size can reach this '
    'column. Filling it anyway is how sport-m''s EU 34 became a UK 34 and '
    'vanished from the size filter -- see V20.';

-- `product_price_summary.available_sizes_eu` is derived from these rows and
-- is what the storefront filters on, so it is stale for the repaired
-- products until something recomputes it. The loader refreshes it per
-- product on every promotion, so the next sweep of either shop heals it; a
-- one-off pass over the affected products does it sooner.
