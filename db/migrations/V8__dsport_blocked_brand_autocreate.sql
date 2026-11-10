-- =============================================================================
-- V8 -- dsport.mk cannot be crawled by a self-identifying bot.
--
-- Discovered by running the pipeline, not by reading anything. dsport sits
-- behind Cloudflare and returns **HTTP 403 to our declared crawler on every
-- content path** -- the sitemap, category pages and product pages alike. Only
-- /robots.txt answers. Measured with the honest User-Agent the project ships:
--
--   /robots.txt                            200
--   /media/sitemap/dsport.xml              403
--   /muskarci/obuca                        403
--   /muskarci/obuca/cizme/...-kj8942       403
--
-- There is a well-known way to get around this and we are not taking it.
-- Presenting a browser User-Agent to defeat a bot check would be dishonest,
-- would make the "please send us a feed" conversation impossible, and would
-- leave the project one rule change away from breaking anyway.
--
-- So dsport is deactivated rather than hammered. It now needs an agreement
-- for two independent reasons:
--   1. robots.txt forbids /graphql (V5), and
--   2. its edge blocks our crawler outright (this migration).
--
-- Its adapters, both API and HTML, stay in the tree and stay tested. Turning
-- dsport back on is one UPDATE once there is an allowlist entry or a feed.
-- =============================================================================

UPDATE merchant
   SET is_active = false,
       robots_notes = robots_notes ||
           ' DEACTIVATED (V8): the edge returns 403 to our declared crawler on '
           'all content paths, so there is no compliant route in. Needs an '
           'allowlist entry, a feed, or an affiliate agreement. Re-enable with '
           'UPDATE merchant SET is_active = true WHERE slug = ''dsport''.'
 WHERE slug = 'dsport';

-- -----------------------------------------------------------------------------
-- Brand long tail
-- -----------------------------------------------------------------------------
-- The first live run left offers unmatched purely because their brand was not
-- in the seed list: "Mont" on sportvision, "Hoka" on sizeer. Brand is a long
-- tail in this market, and the matcher blocks on brand, so an unseeded brand
-- means no matching at all -- the offer is kept but never joins a product.
--
-- The loader now creates a brand on demand from a merchant's own brand field
-- (never guessed from a title). These are the ones the live run surfaced, plus
-- the obvious MK-market absences, so the common cases need no round trip.

INSERT INTO brand (slug, name, aliases) VALUES
    ('hoka',      'Hoka',       ARRAY['hoka','hoka one one','ХОКА']),
    ('mont',      'Mont',       ARRAY['mont','МОНТ']),
    ('lotto',     'Lotto',      ARRAY['lotto','ЛОТО']),
    ('kappa',     'Kappa',      ARRAY['kappa','КАПА']),
    ('champion',  'Champion',   ARRAY['champion','ЧАМПИОН']),
    ('ellesse',   'Ellesse',    ARRAY['ellesse']),
    ('umbro',     'Umbro',      ARRAY['umbro','УМБРО']),
    ('diadora',   'Diadora',    ARRAY['diadora','ДИАДОРА']),
    ('joma',      'Joma',       ARRAY['joma']),
    ('salomon',   'Salomon',    ARRAY['salomon','САЛОМОН']),
    ('columbia',  'Columbia',   ARRAY['columbia','КОЛУМБИЈА']),
    ('the-north-face', 'The North Face', ARRAY['the north face','north face','tnf']),
    ('crocs',     'Crocs',      ARRAY['crocs','КРОКС']),
    ('timberland','Timberland', ARRAY['timberland']),
    -- An apostrophe in a SQL literal is doubled; double quotes would make
    -- Postgres read it as a column name.
    ('levis',     'Levi''s',    ARRAY['levis','levi''s','levi s']),
    ('tommy-hilfiger', 'Tommy Hilfiger', ARRAY['tommy hilfiger','tommy']),
    ('calvin-klein', 'Calvin Klein', ARRAY['calvin klein','ck']),
    ('guess',     'Guess',      ARRAY['guess']),
    ('replay',    'Replay',     ARRAY['replay']),
    ('mizuno',    'Mizuno',     ARRAY['mizuno'])
ON CONFLICT (slug) DO NOTHING;
