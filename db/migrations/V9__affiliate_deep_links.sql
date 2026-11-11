-- =============================================================================
-- V9 -- Affiliate deep-link template per merchant, for /out/{id}.
--
-- The schema already carried `affiliate_network` (who we are paid through) and
-- `cpc_rate_minor` (what a click is worth), but nothing saying *how* to build
-- an attributable link. Without it the redirect can only send a shopper to the
-- shop's own URL, which means a conversion through an affiliate network would
-- not be credited to us -- the clicks happen and the revenue does not.
--
-- The template is substituted at redirect time:
--
--   {url}        the shop's product URL, percent-encoded (the usual case,
--                since networks pass the destination as a query parameter)
--   {rawUrl}     the same URL unencoded, for templates that append a path
--   {variantId}  our offer_variant id, for sub-ID tracking so a payout can
--                be reconciled against click_event
--
-- NULL means "no affiliate relationship": redirect straight to product_url.
-- That is the state every merchant is in today, and it is a normal state, not
-- a missing configuration -- direct CPC deals need no template at all.
-- =============================================================================

ALTER TABLE merchant
    ADD COLUMN affiliate_url_template text;

COMMENT ON COLUMN merchant.affiliate_url_template IS
    'Deep-link template for outbound clicks. Placeholders: {url} (encoded '
    'product URL), {rawUrl} (unencoded), {variantId} (our offer_variant id, '
    'for sub-ID reconciliation against click_event). NULL = redirect directly '
    'to merchant_offer.product_url, which is correct for a direct CPC deal.';

-- A template that does not reference the destination would silently send every
-- shopper to the same landing page, so require one of the URL placeholders.
ALTER TABLE merchant
    ADD CONSTRAINT merchant_affiliate_template_has_url CHECK (
        affiliate_url_template IS NULL
        OR affiliate_url_template LIKE '%{url}%'
        OR affiliate_url_template LIKE '%{rawUrl}%'
    );
