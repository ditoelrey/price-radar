# Price Radar (MK)

Price comparison for sneakers across North Macedonian stores. Idealo-style:
one unified product card showing the lowest price, opening to every offer
sorted cheapest first, with outbound clicks routed through `/out/{id}` for
CPC/affiliate attribution.

Launching MK-only, but the schema is multi-country from day one — the same
adapters cover the RS / HR / BA / SI siblings of most of these chains.

## Status

| Piece | State |
|---|---|
| Phase 1 store recon | **done** — all 7 stores profiled live |
| Postgres schema (Flyway) | **done** — V1–V4 applied to PostgreSQL 16.4 |
| 4 Python adapters | **done**, 100 tests green against golden files |
| Matcher | **done** — both golden test cases pass |
| End-to-end smoke load | **done** — `ingest/scripts/smoke_load.py` |
| Fetcher / scheduler | **done** — rate limiter, queue, robots, archive, adaptive TTL |
| Loader (stage / validate / promote) | **done** — a failed run cannot reach the site |
| HTML routes (dsport + megasport) | **done** |
| URL discovery | **done** — sitemap / paginated / sampled, per platform |
| Worker loop | **done** — `scripts/run_pipeline.py` runs it autonomously |
| Spring Boot serving API | **done** — listing, detail, `/out/{id}` redirect |
| Next.js frontend | **done** — listing + detail, size-aware throughout |

## The core finding

All seven stores expose the **manufacturer article code**, so product matching
is a primary-key lookup rather than a machine-learning problem. Fuzzy matching
is a long-tail fallback, not the engine.

Verified live, same SKU across stores:

| Product | SKU | Store | Price |
|---|---|---|---|
| Puma Caven 2.0 | `392290-02` | sportreality.mk | 2 863 MKD |
| | | sportvision.mk | 2 863 MKD |
| | | megasportonlineshop.com | 3 999 MKD |
| Adidas Stan Smith | `M20325` | buzzsneakers.mk | **4 072 MKD** |
| | | sport-m.com.mk | **6 799 MKD** |
| | | sizeer.com.mk | 6 799 MKD |

A 67% spread on an identical article code. That is the product thesis, and
`tests/test_matching.py::TestCaseB::test_price_spread_is_real` asserts it.

## Seven stores, four adapters

| Adapter | Merchants | Route | Per-size stock | robots.txt |
|---|---|---|---|---|
| `magento` | dsport.mk | open GraphQL, no auth | yes, with quantities | **`Disallow: /graphql`** |
| `woocommerce` | megasportonlineshop.com | open Store API, no auth | yes, via variations | **`Disallow: /wp-json/`** |
| `sportvision` | sportvision.mk, sportreality.mk, buzzsneakers.mk | HTML + JSON-LD | yes, `li.disabled` | product pages allowed |
| `aspnet_mk` | sport-m.com.mk, sizeer.com.mk | private JSON endpoint | sport-m only | no robots.txt at all |

### Correction: the two open APIs are off-limits

Phase 1 recon concluded that dsport and megasport "need no scraping at all".
The first live run of the fetcher disproved it. Both endpoints are
unauthenticated and both are explicitly forbidden by their site's robots.txt.
An endpoint being open is not permission to crawl it.

So today the usable picture is:

- **4 merchants crawlable now** — the three Sport Vision stores (product pages
  allowed) and sport-m + sizeer (no robots.txt, so unrestricted per RFC 9309,
  including `POST /ProductCatalog/GetVelicini/`).
- **2 merchants moved to their permitted HTML route** (V7) — dsport reads
  `data-product-sku` plus the Magento `spConfig` size matrix; megasport reads
  the JSON-LD `Product` node plus `data-product_variations`. Both emit the
  same `merchant_sku` their API counterparts do, so the switch updated the
  existing offers instead of forking them. `api_requires_permission` stays
  TRUE as the record of why the API route is unused, and
  `build_stock_probe` raises `RobotsBlocked` if anything tries it.

Then running the pipeline corrected this again: **dsport returns HTTP 403 to
our declared crawler on every content path** — sitemap, category pages and
product pages alike. Only `/robots.txt` answers. There is an obvious way round
that and we are not taking it; presenting a browser User-Agent to defeat a bot
check would be dishonest, would make the "please send us a feed" conversation
impossible, and would leave the project one rule change from breaking anyway.
So dsport is `is_active = false` (V8) with the reason recorded, and needs an
allowlist entry, a feed or an affiliate agreement. Its adapters stay tested;
re-enabling it is one `UPDATE`.

**Six of seven merchants are crawlable today**, none of them in violation of
anything, and the seventh needs a conversation rather than code.

The partnership conversation is still worth having — a feed is cheaper and
fresher than any page parse, and the API adapters stay in the tree and stay
correct for exactly that reason. It is no longer blocking.

One unexpected result: for the Puma Caven 2.0 the megasport Store API reported
`prices.price = 3999` while every variation on the product page is
`display_price = 3199.2`. The parent price had missed a 20% reduction applying
to all sizes. **The permitted route is also the more accurate one.**

### Correction: no store sends cache validators

The earlier volume estimate assumed conditional requests would turn most
probes into 304s. Measured against all six live stores, none sends an `ETag`,
and every one sends `Cache-Control: no-store` / `no-cache` / `private`; only
megasport sends a `Last-Modified`, on a `no-store` response. So **every probe
costs a full body.** The fetcher still sends `If-None-Match` and
`If-Modified-Since` — they cost nothing and a store may add support — but the
bandwidth savings should not be budgeted for.

Request *counts* are unchanged, and counts are what get a crawler blocked.
What this does change is that the `stock_probe` vs `catalog_parse` split is
now the main lever for keeping probes cheap: 2-8 KB of JSON against 400 KB of
product page is a 50-100x difference per check.

## Layout

```
db/migrations/        Flyway SQL, V1..V5
ingest/
  src/mkagg/
    normalize.py      sizes, money, SKUs, MK transliteration
    models.py         RawOffer / RawVariant / MatchResult
    matching.py       MPN-first matcher with fuzzy fallback
    adapters/         six platform adapters (pure bytes -> RawOffer)
    fetch/
      ratelimit.py    per-domain token bucket + circuit breaker
      queue.py        strict-priority queue with TTL dedupe
      rawstore.py     gzipped snapshot archive
      http.py         the only module that touches the network
      scheduler.py    adaptive TTL, demand tiering, write-on-change
    load/
      staging.py      append what the adapter saw, no interpretation
      validate.py     the gate: shape checks against the merchant's own median
      promote.py      match, upsert, write-on-change, refresh the read model
      run.py          stage -> validate -> promote, with the commit boundaries
  scripts/
    smoke_load.py     fixtures -> adapters -> matcher -> Postgres
    verify_fetcher.py live check against real stores (~8 requests)
  tests/
    fixtures/         golden files captured from the live stores
web/                  Next.js 16 / React 19 storefront (App Router, TS)
  src/app/products/     listing and detail pages (server components)
  src/components/       catalog/ (size picker, cards, offer rows) + ui/ (shadcn)
  src/lib/              typed API client, money and size formatting
api/                  Spring Boot 3.3 / Java 21 serving layer
  src/main/java/mk/priceradar/api/
    catalog/            listing + detail: Dtos, repository, service, controller
    outbound/           /out/{id}: click ledger then 302
  Dockerfile            multi-stage; builds with no local JDK
tools/
  probe_mk_stores.py  store recon prober (stdlib only)
docker-compose.yml    postgres + flyway + redis + api
```

## The serving API

Spring Boot 3.3 on Java 21, with virtual threads on — the layer is almost
entirely waiting on Postgres, so that lifts the thread ceiling with no
reactive rewrite. Plain `JdbcClient`, no ORM: the queries *are* the value
here, and an ORM would hide the one thing that has to stay readable.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/products?q=&brand=&sizeEu=&page=&pageSize=` | listing, cheapest first |
| `GET /api/v1/products/{slug}?sizeEu=` | detail, every offer by total price |
| `GET /out/{offerVariantId}` | log the click, then 302 to the shop |
| `GET /actuator/health` | liveness |

Three rules it exists to enforce:

**The listing never aggregates.** It reads `product_price_summary`, one
pre-computed row per product. Computing `MIN(price)` over `offer_variant` at
request time would scan ~1.2M rows per search today and more per merchant
added.

**`sizeEu` changes the price, and the response says so.** Without it you get
the product's cheapest offer; with it, the cheapest offer *in that size*,
recomputed from the variants, and `fromPriceIsSizeSpecific: true`. For the
Stan Smith that is the difference between the 4 072 MKD headline and the
6 799 a shopper asking for EU 44 actually pays.

**Offers sort by total, not sticker.** 2 863 MKD plus 400 postage is dearer
than 3 000 delivered free, and sorting on the sticker would mislead on
precisely the comparison the site exists to make.

### The redirect is the business

`/out/{id}` logs the click **synchronously, before** the 302, and **fails
open**: if the insert throws, the shopper is still redirected and the failure
is logged with every id needed to reconstruct the row by hand. Losing a ledger
row is bad; breaking the shopper's journey — and the shop's sale — because our
database hiccuped is worse. The response is `no-store`, since a cached
redirect would both stale the destination and stop the click reaching us.

No raw IP is ever stored: `click_event.ip_hash` is a salted SHA-256 truncated
to 16 bytes. An unsalted hash of an IPv4 address is not anonymisation — the
space is four billion values — so `CLICK_IP_HASH_SALT` is required
configuration, not a default. Bot clicks are **flagged and kept**, never
dropped, so the ledger can still explain itself when a merchant disputes an
invoice.

`merchant.affiliate_url_template` (V9) builds attributable deep links, with
`{url}` / `{rawUrl}` / `{variantId}` substituted at redirect time. NULL means
a direct redirect, which is correct for a direct CPC deal and is where every
merchant is today.

## The priority ladder

Everything the fetcher does for a merchant draws on one shared per-domain
budget, so the ordering is the design:

```
CLICK  >  HOVER  >  SWR  >  HOT  >  WARM  >  COLD
```

Background work is preemptible by definition, and the token bucket holds back
a reserve that only `CLICK` and `HOVER` may spend. A nightly crawl saturating
a domain therefore *cannot* consume the headroom a user waiting at `/out/{id}`
needs; the crawl pauses instead. Freshness degrades, the user-facing path does
not.

Budgets are wall-clock and hard: `CLICK` is capped at 1.2 s, past which the
redirect goes out unverified. A fetch never raises and never blocks past its
budget — a missed verification costs an unverified redirect, never a lost
click.

## Discovery, per platform

Each strategy was chosen by measuring the live site, not by assuming.

| Strategy | Merchants | How | Cost |
|---|---|---|---|
| `sitemap` | megasport | `/sitemap_index.xml` → 11+ product sitemaps | 1 request per ~200 products |
| `paginated` | sportvision, sportreality, buzz | `{category}/page-{n}`, with `data-total-pages` on page 1 (124 pages of sneakers on sportvision) | 1 request per page |
| `sampled` | sportm, sizeer | see below | ~6 requests per facet |

### The sampled strategy, and why it exists

sport-m and sizeer have no sitemap, no `robots.txt`, and **no deterministic
pagination at all**. They return a *random sample* of about 18 matching
products per request: the same URL fetched twice shared 1 of 18 results, and
`&Page=2` is not honoured. Measured against a narrow facet, repeated requests
saturate at 21 products after about 5 tries:

```
req   new   cumulative
  1    18     18
  2     1     19
  3     1     20
  4     0     20
  5     1     21
  6-10  0     21        <- saturated
```

So discovery re-requests a narrowed facet (`Segment` / `Grupa` / `PodGrupa` /
`Brend`, plus a brand-term sweep through `Search?SearchKey=`) until it stops
yielding anything new, with a hard per-facet request ceiling.

Be clear about the limit: **sampling cannot prove it has seen everything.**
These two stores will always have an unknown tail, and `DiscoveryReport`
reports unsaturated facets rather than hiding them. They are also the two most
likely to hand over a feed — one operator, no robots.txt, no SEO tooling —
which would remove the problem outright.

## Running it

Tests — no database, no network, no install:

```bash
cd ingest && python -m venv .venv && ./.venv/Scripts/python.exe -m pip install pytest "psycopg[binary]" "httpx[http2]" redis
```

```bash
cd ingest && ./.venv/Scripts/python.exe -X utf8 -m pytest
```

Database (start Docker Desktop first):

```bash
docker compose up -d postgres redis && docker compose run --rm flyway migrate
```

```bash
docker compose run --rm flyway info
```

End-to-end check — fixtures through the adapters and matcher into Postgres,
then the real offer-list and size-filter queries:

```bash
cd ingest && ./.venv/Scripts/python.exe -X utf8 scripts/smoke_load.py
```

The pipeline itself — discovery, then the worker loop, against the live stores:

```bash
cd ingest && ./.venv/Scripts/python.exe -X utf8 scripts/run_pipeline.py discover --limit 20
```

```bash
cd ingest && ./.venv/Scripts/python.exe -X utf8 scripts/run_pipeline.py probe
```

The API — builds and tests with **no JDK or Maven on the host**:

```bash
docker compose run --rm api-test
```

```bash
docker compose up -d --build api && curl -s localhost:8080/actuator/health
```

**The database tests TRUNCATE, so they point at a separate `mkagg_test`
database** (`MKAGG_TEST_DSN`). Create it once with:

```bash
docker compose exec postgres createdb -U mkagg mkagg_test && docker compose run --rm -e FLYWAY_URL=jdbc:postgresql://postgres:5432/mkagg_test flyway migrate
```

Flyway's connection settings live in `environment:`, **not** `command:`.
`docker compose run <service> <args>` replaces the compose `command`, so
`-url`/`-user`/`-password` placed there are dropped and Flyway fails with
*"Unable to connect to the database. Configure the url, user and password!"*.

## Rules this codebase enforces

These exist because recon proved each one necessary. Please don't "simplify"
them away.

1. **Money is integer minor units.** `currency.minor_unit` is **0** for MKD as
   these shops configure it — megasport's Store API literally reports
   `currency_minor_unit: 0`. Never hard-code 100. Never use a float.

2. **Unknown stock is `None`, not `False`.** sizeer.com.mk returns its size
   list with `Zaliha: null` for every size. The UI must render that as
   "listed", never as "in stock" and never as "sold out". See
   `merchant.publishes_stock`.

3. **Sizes are normalised, labels are preserved.** Observed on target stores:
   `35,5` and `35.5` on the *same page*; `44 2/3`; `41⅓` (U+2153); `37-5`;
   `BEZ VELICINA`. Normalise with `normalize_size()` for comparison, keep
   `size_label` verbatim for display.

4. **Never NFKC a size string.** NFKC decomposes `41⅓` into `411⁄3` and
   silently destroys the value.

5. **Adapters are pure.** `bytes -> RawOffer`. No network, no database. That
   is what makes the golden-file tests possible and what lets a fixed parser
   be re-run over archived raw HTML instead of losing the price history.

6. **Fuzzy matching never auto-links.** It is capped below the 0.92 auto
   threshold. A wrong auto-match merges two different shoes onto one page,
   which is far harder to notice and undo than an unmatched offer.

7. **A failed-validation ingest run is not committed.** Stage, check fill
   rates and record-count deltas against the 7-day median, then swap. A parser
   showing "0 MKD" on the homepage is worse than data a few hours stale.

8. **An open endpoint is not permission to crawl it.** Check robots.txt for
   the exact path an adapter will call, not just for the site. Both of this
   project's best data sources are unauthenticated *and* forbidden. Honouring
   that is also what makes the feed conversation possible later.

9. **Stage, validate, then promote.** A run that fails its shape checks is
   never published, and its staged rows are kept as the evidence for
   diagnosing the parser. Checks are relative to that merchant's own 7-day
   median over *promoted* runs only, so a bad run cannot widen the band that
   would have caught it.

10. **Never take a product title from a bare JSON `"name"`.** On buzzsneakers
   the first `"name"` in the document is the Organization's, so the rescue
   path produced the catalogue product "Adidas buzz online shop" — and every
   test still passed, because they only asserted the SKU and the price. Titles
   come from `<h1>`, then `og:title` with the site suffix stripped.

11. **Never default a category.** `create_product` hard-coded `sneakers` for
   everything it created, so a pack of socks became footwear. `category_id` is
   nullable and NULL is the right value for a title that does not say: a null
   reads as a question in admin, a wrong value reads as settled. See
   `taxonomy.classify`, which returns None rather than guessing.

12. **Match keywords on whole words.** The classifier compared
   space-padded text but stripped the padding off its needles, so `ball`
   matched inside `HANDBALL SPEZIAL` and filed a shoe as equipment.

13. **List both the singular and the plural.** The noise list had `тренерки`
   but not `тренерка`, which left "Dolna Trenerka" sitting inside a product
   name. Macedonian category nouns need both forms, in both scripts.

14. **Zero is never falsy enough to skip a check.** The probe guard first read
   `if old_price and new_price and abs(...)`, so a price of `0` — the exact
   value a broken parser produces — bypassed it and would have been published.
   Compare with `is None` and `== 0` explicitly. Relatedly, sport-m's
   `GetVelicini` carries *no* price at all, so an all-zero payload means
   "stock only, keep the stored price", while zeros mixed in among real prices
   mean a parser fault and are quarantined.

15. **Postgres forbids `EXCLUDED` in `RETURNING`.** To learn whether an upsert
   actually changed anything, read the prior row in a CTE and compare against
   the bound parameters. `promote.py` does this, and it is what makes
   write-on-change work in the loader.

16. **A clock and a sleep must come from the same source.** `MemoryRateLimiter`
   and `Fetcher` take both. Injecting a test clock while sleeping on the real
   one makes every wait loop measure a time that never advances — it hangs
   rather than failing, which is the worst way for a bug to present.

17. **Bound HTML extraction on the element, never on a byte window.** The
   Sport Vision size reader originally took a fixed 20 KB slice. That
   truncated sportvision's own 23-element size run (which spans ~20.6 KB) and,
   read any wider, bled into the recommendation tiles lower on the page —
   160+ stray size elements on sportreality, 249 on buzz. Both failures look
   the same from outside: a plausible list of wrong sizes. It is now bounded
   by the size list's own `</ul>`, and `TestSizeBlockBoundary` locks the exact
   counts (20 / 20 / 30).

8. **Windows + Cyrillic:** always run Python with `-X utf8` or
   `PYTHONIOENCODING=utf-8`. The default `cp1252` console encoding raises on
   Macedonian product names.

## Why the size filter is not optional

The smoke load makes the case better than any argument. For the Stan Smith,
the headline is **"from 4 072 MKD"** at Buzz — true, and Buzz has 30 sizes
listed. But only **one** of them is actually in stock (EU 45 1/3). Ask for
EU 44 and the real cheapest offer is **6 799 MKD**, a 67% jump.

A comparison site that shows the 4 072 headline to someone shopping for size
44 has told them something true and useless, and they find out after the
click. Size-aware pricing is the whole difference.

## Autonomous run, measured

A live bounded run (5 products per merchant, 1 req/s, robots honoured):

```
merchant      strategy      reqs  found  queued
buzz          paginated        1      5       5     /mk/patiki: 73 pages
megasport     sitemap          2      5       5
sizeer        sampled          4      5       5
sportm        sampled          4      5       5
sportreality  paginated        1      5       5     /mk/patiki: 71 pages
sportvision   paginated        1      5       5     /mk/patiki: 124 pages

jobs=30  fetched=30  errors=0  offers=30  40.2s
  6 runs, all OK, 30 promoted, 0 unmatched, sku_fill=100%
```

Then the probe path, with 60 variants due:

```
re-tiered 287 variants; queued 5 probes (55 deduped, 0 robots-blocked)
jobs=5  fetched=5  probes=64(changed=0,rejected=0)  4.9s
```

**Five requests answered 64 variants.** That is the dedupe and the
per-offer probe design working: one page fetch resolves every size of an
offer, so sizes do not multiply requests.

## The API, verified live

Detail page for the Stan Smith, straight out of `/api/v1/products/{slug}`:

```
Adidas Stan Smith   MPN M20325
  from 4,072 to 6,799 MKD | 3 offers / 3 shops

  shop             from(total)  sizes  in stock  unknown  operator
  Buzz Sneakers          4,072     30         1        0  -
  Sizeer                 6,799      8         0        8  sportm
  Sport-M                6,799      8         8        0  sizeer
```

Sizeer reports eight sizes and zero stock claims — `NOT_PUBLISHED`, not
`SOLD_OUT` — and both it and Sport-M are badged as the same operator, because
both are on the page.

Now add `?sizeEu=44`:

```
  Buzz Sneakers      4,072 MKD  size 44   SOLD_OUT                -> /out/348
  Sizeer             6,799 MKD  size 44   NOT_PUBLISHED           -> /out/119
  Sport-M            6,799 MKD  size 44   IN_STOCK        qty 1   -> /out/368
```

The 4,072 headline is **sold out in size 44**. A shopper asking for that size
really pays 6,799 — a 67% jump — and the API says so rather than advertising a
price they cannot buy.

And the redirect:

```
GET /out/368
  HTTP 302
  Location: https://www.sport-m.com.mk/ProductCatalog/ProductDetails?ProductID=M20325
  Cache-Control: no-store, no-cache, must-revalidate, max-age=0
  Referrer-Policy: no-referrer

click_event
 variant | merchant | price | cur | is_bot | ip_hash_bytes
     368 | sportm   |  6799 | MKD | t      |            16
```

The price is captured *as shown at click time*, which is what makes the
click-time mismatch KPI computable and an invoice defensible.

## Product naming

Shop titles are not product names. Megasport's are shaped
`"{article code} {category word} {model} - Megasport"`, so a naive clean
produced the catalogue entry **"Adidas Gh0331 Chorapi Act Core Mid Crew Sock
3p Megasport"**. `clean_model_name` now also takes the `mpn` and the
`merchant`:

| shop title | catalogue name | category |
|---|---|---|
| `GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport` | Adidas Act Core Mid Crew Sock 3p | `socks` |
| `JQ2626 Патики GALAXY 7 M - Megasport` | Adidas Galaxy 7 M | `sneakers` |
| `857797631I-990 ICEPEAK IRWINTON SKI HELANKI/CR` | Icepeak Irwinton Ski Cr | `leggings` |
| `1357128-001 Долна тренерка UA Rival Fleece Joggers - Megasport` | Under Armour Ua Rival Fleece Joggers | `apparel` |
| `ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ` | Adidas Terrex Skychaser Ax5 Mid Gtx | `boots` (from the URL) |

The article code is removed by **exact match on the known MPN**, never by
pattern: anything loose enough to catch `7312-200` also eats "Caven 2.0",
"Galaxy 7" and "Air Max 90". The shop suffix is anchored to the end of the
string. The English word "sock" survives because it is part of the real model
name, while the shop's Cyrillic category word does not.

Measured over the live catalogue after the fix: **0 of 29 product names
contain an article code, and 0 contain a shop name.**

## The storefront

Next.js 16 (App Router) + TypeScript, Tailwind and shadcn/ui, Lucide icons.
Layout follows the references: filter rail on the left, product grid on the
right, flat minimal cards.

**Everything renders on the server.** Filtering is driven by URL search params
rather than client state, so the browser never calls the Spring API: no CORS
surface, no API origin exposed, and a filtered view is a real URL that can be
shared, bookmarked and hit with the back button.

### The size picker is the whole design

A grid of chips, not a dropdown. A shopper knows their size and should be able
to hit it in one click; a select would add two interactions to the single
filter that changes what every price on the page *means*. Sizes render as
`44 ⅔`, not `44.667` — the pipeline's number is for comparing, the fraction is
what is printed on the box.

Pick EU 44 on the Stan Smith and the page says so outright:

> The **4.072 ден.** headline is from Buzz Sneakers, which does not have EU 44.
> In your size the cheapest is **6.799 ден.** at Sport-M.

### Rules the offer table enforces

1. **One row per shop, not per size.** Buzz carries that shoe in 30 sizes at
   one price; a row each buried every other shop under thirty near-identical
   lines.
2. **The row's price must be buyable.** Each shop is represented by its
   cheapest variant that is *not* sold out. Sorting purely on price first
   produced a top row reading "Best total price — EU 35.5 — Sold out": true,
   useless, and exactly the bait this site exists to prevent.
3. **Ties go to the shop that confirms stock.** Sizeer and Sport-M quote an
   identical 6.799 ден. and Sizeer publishes no availability, so crowning it
   "best" would send shoppers to the weaker of two identical offers.
4. **Totals, never stickers**, and the check time sits beside the price rather
   than in a footnote.

Buy buttons always point at `/out/{variantId}` with `rel="sponsored nofollow"`.
That path is **same-origin** and proxied to the API by a rewrite in
`next.config.ts` — without it the browser asks Next for `/out/368`, finds no
route, and the one button that must never fail returns a 404. A rewrite
rather than an absolute `:8080` URL keeps both services behind one domain in
production and avoids a cross-origin hop on the revenue path. Next passes the
API's 302, its `no-store` and its `Referrer-Policy: no-referrer` straight
through.

Because the click is now proxied, the API runs with `TRUST_FORWARDED_FOR=true`
— otherwise every click would hash to the Next server's own address and the
bot and deduplication statistics would be worthless. Verified: three distinct
clients produce three distinct `ip_hash` values through the proxy.

### Merchant logos

Each offer row carries the shop's logo in a fixed `h-10 w-28` box with
`object-contain`, centred. Source files are trimmed to their content by
`tools/prepare_logos.py` first — without that the box letterboxes each logo
by its *canvas* rather than its artwork, and Sport Vision (a wide wordmark in
a 400x400 square, ratio 1.00) renders at a third the size of the others for
no visible reason. Trimmed, every ratio lands between 3.08 and 5.51, all
wider than the box, so all six render at exactly 112px wide and centre
vertically: a tidy column.

Logos of different proportions cannot share both a width and a height.
Uniform width with varying height reads as a column; uniform height would
give widths from 111px to 229px and read as a mess.

`mix-blend-multiply` is applied per merchant, from measurement rather than
appearance: **Buzz** is 28% opaque white and needs it, while Sport-M — the
one that looks white-matted — is fully transparent already, as are the other
four. It is scoped to light mode, because multiply against a dark background
turns a black wordmark invisible.

Two alignment bugs that only showed up under measurement, not on screen:

* each offer row is **its own CSS grid**, so `auto` columns sized to their own
  content and the logo column drifted 1.6px between rows. Fixed track widths
  (`minmax(0,1fr)_7rem_19rem`) pin it.
* the `outline` button variant has a 1px border and `buy` did not, making the
  best-price button 2px narrower and staggering the right-hand column. All
  variants now carry a transparent border so their boxes match.

Measured after: zero spread on logo positions, button positions and button
widths; equal row heights.

### Category scope

The storefront serves footwear. The pipeline crawls shops that also sell
socks, ski leggings and helmets, so `GET /api/v1/products` defaults to
`kind=footwear`; `kind=all` lifts it and any other value selects one kind.

The filter **excludes known non-footwear rather than admitting only known
footwear**, and that asymmetry is the whole point. Twelve products have no
category because their titles never named one ("Adidas Handball Spezial",
"Hoka Clifton UTL") — they are shoes, reached through footwear facets and
footwear sitemaps. Admitting only confirmed footwear would hide them. So the
default view is 18 confirmed + 12 unclassified = 30 of 32, with the two
apparel rows removed. An explicit `kind=apparel` drops the unclassified,
since someone asking for apparel does not want twelve uncategorised sneakers
as well.

## Product images

All seven platforms now yield a real product photo (32 of 32 products, up
from 5). Three separate causes, none of which announced itself:

**JSON-LD `image` is rarely a string.** schema.org allows four shapes and
these stores use three: sportvision sends a *list of strings*, megasport a
*list of `ImageObject` dicts*, buzz nothing at all. Reading it with a scalar
text helper returned `None` for both list forms, silently.

**`og:image` is sometimes the company logo.** sport-m advertises
`Content/FacebookLogo.png` and sizeer `Content/Logo.png`. Trusting that tag
would have put a Facebook logo on every one of their product cards — working
code, wrong picture. Their real photos sit at
`/ProductImages/{ProductID}.webp`, matched against *this* product's id so the
carousel's neighbours and the brand-logo directory cannot be picked up
instead. `looks_like_product_image()` rejects the known chrome either way.

**A product took its image once, at creation.** A product first seen through
a shop with no photo stayed blank for good, even after three other shops
listed it. Promotion now backfills `product.image_url` from the first offer
that has one, and reports the count.

## A crash that was hiding a worse bug

`/products/adidas-terrex-skychaser-ax5-mid-gtx-kj8942` threw
`Cannot read properties of undefined (reading 'toFixed')` in `formatSizeEu`.
The formatter was the symptom. The chain underneath:

1. V8 deactivated dsport, whose edge 403s our crawler.
2. `refresh_summary` filtered `merchant_offer.status` but **not**
   `merchant.is_active`, so that product kept its summary row.
3. The listing reads summaries, so the site went on advertising
   **"from 8 599 ден. · 1 shop"**.
4. The detail page's offer query *does* filter `m.is_active`, so it returned
   zero offers.
5. The empty-state branch assumed a size filter must be active and called
   `formatSizeEu(sizeEu!)` — and that `!` is what stopped TypeScript
   catching any of it.

Quoting a price nobody can buy is the exact failure this project exists to
prevent, and nothing in the pipeline flagged it. It took a TypeError in a
size formatter to make it visible.

Fixed in four places: `refresh_summary` now requires `m.is_active`; V11
clears the rows it already wrote; the detail page distinguishes "no offers in
your size" from "no offers at all" and never falls back to the summary's
price for its headline; and `formatSizeEu` is null-safe, which it needed to
be anyway for one-size articles (dsport's `BEZ VELICINA`).

## Self-hosted images

Product photos are fetched once and served from our own infrastructure, not
hotlinked. At catalogue scale hotlinking spends six shops' bandwidth on every
page view, and one referer rule at any of them blanks that shop's photos with
no error on our side.

Images go through the same `Fetcher` as everything else — an image request is
still a request to a merchant, so it belongs under the same rate limiter,
robots check and circuit breaker, at `COLD` priority.

Storage is **content-addressed by SHA-256 of the bytes**, which buys three
things at once: deduplication (13 of 29 on the last run, because the shops
publish the same manufacturer press photo), immutability (so `/media/...` is
served `max-age=31536000, immutable` and never needs invalidating), and
idempotent re-fetching.

What gets refused matters as much as what gets stored. A shop returning its
error page with `Content-Type: image/jpeg` and a 200 is a real occurrence, so
the bytes are checked for an actual image signature rather than trusting the
header — otherwise it would be stored and rendered as a broken photo with
nothing in the logs. Tracking pixels, spacers and anything over 8 MB are
rejected too, and `image_checked_at` is stamped even on failure so a dead URL
is retried on a schedule instead of on every pass.

```bash
cd ingest && ./.venv/Scripts/python.exe -X utf8 scripts/run_pipeline.py images
```

The API serves `/media/**` from the shared volume and Next proxies it, so the
storefront stays same-origin. `product.image_url` is kept as provenance only.

## Category hints from discovery

Classification reads a product's title, and a third of the catalogue had no
category because their titles never named one — "Adidas Handball Spezial",
"Hoka Clifton UTL". At 50k products that is thousands of uncategorised rows
in a storefront that filters by category.

Discovery knew all along: those products were reached through a footwear
facet or a footwear category page. Each entry in `DISCOVERY_PLANS` now
carries the category it implies, which travels on the `FetchJob`, through
`stage_offer.category_hint`, to the loader.

**A hint is context, not evidence.** The loader still prefers what the title
actually says, and only falls back to the hint when the title is silent — so
a pack of socks found through a footwear facet is still filed as socks. Brand
facets carry no hint at all, because a brand says nothing about category.

Measured over the same sweep:

| | before | after |
|---|---|---|
| sneakers | 16 | 16 |
| footwear | 0 | 10 |
| apparel | 2 | 2 |
| socks | 1 | 1 |
| **unclassified** | **12** | **0** |

## Known gaps

- `sizeer.com.mk` has no `robots.txt` and no sitemap; neither does the Sport
  Vision group. Discovery must use category pagination plus a brand-term
  search sweep.
- sizeer.com.mk and sport-m.com.mk share a platform, a host IP and an
  identical price for `M20325`. Probably one operator —
  `merchant.related_merchant_id` links them so the UI can collapse or badge
  them rather than looking padded.
- **No cross-store matches in the live sample yet.** The fixture run proves
  matching (same SKU on 3 shops, 67% spread), but a 5-product-per-store crawl
  starting from different discovery entry points produces no overlap by
  chance. Real comparison coverage needs a full sweep — roughly 50k product
  fetches at 1 req/s per merchant, so hours, not minutes. That is a decision
  to take deliberately, not a bug.
- Discovery covers footwear categories only; apparel is more strings in
  `DISCOVERY_PLANS`.
- The queue and rate limiter are the in-memory implementations. The Redis
  versions exist and are interface-compatible; switch when more than one
  worker runs, or the per-domain budget is silently multiplied by the worker
  count.
- No live price verification in front of `/out/{id}` yet. It belongs there
  with a hard sub-second budget and must never delay the redirect.
