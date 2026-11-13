-- Let an offer exist without a price, so a sold-out shop can be shown as
-- sold out instead of being dropped.
--
-- megasport removes the price entirely once every size of a product is gone:
-- the page says "Овој продукт е моментално без залиха и недостапен", the
-- JSON-LD Product node carries no `offers` key at all, and
-- `data-product_variations` is an empty array. There is no number on the page
-- to read. Until now such an offer had nowhere to go -- `price_minor` was NOT
-- NULL -- so the worker counted it as unpriced and dropped it, and the shop
-- vanished from the product page as though it had never stocked the item.
--
-- Storing 0 instead is not an option and was never on the table: 0 renders as
-- "0 ден.", which reads as free. An earlier bug in the stock probe wrote
-- exactly that and it is the single most damaging thing this site can display.
-- NULL says the one true thing -- the shop sells this and is out of it, and no
-- price is published -- and it is the same distinction the architecture
-- already draws between NOT_PUBLISHED and sold out.
--
-- `price_point` deliberately stays NOT NULL. It is the price *history*, and
-- "no price was published" is not a price observation; the loader skips the
-- write instead. The `price_minor >= 0` check needs no change: a CHECK is
-- satisfied when its expression is NULL.

ALTER TABLE offer_variant ALTER COLUMN price_minor DROP NOT NULL;
ALTER TABLE stage_variant ALTER COLUMN price_minor DROP NOT NULL;

-- A variant with no price must be one we positively know is unbuyable.
-- Without this, a parser regression that silently stopped finding prices
-- would look exactly like a shop selling out, and would quietly empty the
-- comparison tables instead of failing the gate.
ALTER TABLE offer_variant ADD CONSTRAINT offer_variant_unpriced_means_sold_out
    CHECK (price_minor IS NOT NULL OR in_stock IS FALSE);
