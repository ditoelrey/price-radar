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
| Spring Boot serving API | not started |
| Next.js frontend | not started |
| Spring Boot serving API | not started |
| Next.js frontend | not started |

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
tools/
  probe_mk_stores.py  store recon prober (stdlib only)
docker-compose.yml    postgres + flyway + redis
```

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

11. **Zero is never falsy enough to skip a check.** The probe guard first read
   `if old_price and new_price and abs(...)`, so a price of `0` — the exact
   value a broken parser produces — bypassed it and would have been published.
   Compare with `is None` and `== 0` explicitly. Relatedly, sport-m's
   `GetVelicini` carries *no* price at all, so an all-zero payload means
   "stock only, keep the stored price", while zeros mixed in among real prices
   mean a parser fault and are quarantined.

12. **Postgres forbids `EXCLUDED` in `RETURNING`.** To learn whether an upsert
   actually changed anything, read the prior row in a CTE and compare against
   the bound parameters. `promote.py` does this, and it is what makes
   write-on-change work in the loader.

13. **A clock and a sleep must come from the same source.** `MemoryRateLimiter`
   and `Fetcher` take both. Injecting a test clock while sleeping on the real
   one makes every wait loop measure a time that never advances — it hangs
   rather than failing, which is the worst way for a bug to present.

14. **Bound HTML extraction on the element, never on a byte window.** The
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
- No serving API and no frontend, so nothing reads the catalogue yet.
