# Sneaker Aggregator (MK)

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
| Postgres schema (Flyway) | written, **not yet executed** (needs Docker running) |
| 4 Python adapters | **done**, 96 tests green against golden files |
| Matcher | **done** — both golden test cases pass |
| Fetcher / scheduler | not started |
| Loader (staging + swap) | not started |
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

| Adapter | Merchants | Route | Per-size stock |
|---|---|---|---|
| `magento` | dsport.mk | **open GraphQL**, no auth | yes, with quantities |
| `woocommerce` | megasportonlineshop.com | **open Store API**, no auth | yes, via variations |
| `sportvision` | sportvision.mk, sportreality.mk, buzzsneakers.mk | HTML + JSON-LD | yes, `li.disabled` |
| `aspnet_mk` | sport-m.com.mk, sizeer.com.mk | private JSON endpoint | sport-m only |

Two of the seven need no scraping at all.

## Layout

```
db/migrations/        Flyway SQL, V1..V4
ingest/
  src/mkagg/
    normalize.py      sizes, money, SKUs, MK transliteration
    models.py         RawOffer / RawVariant / MatchResult
    matching.py       MPN-first matcher with fuzzy fallback
    adapters/         the four platform adapters
  tests/
    fixtures/         golden files captured from the live stores
docker-compose.yml    postgres + flyway + redis
```

## Running it

Tests — no database, no network, no install:

```bash
cd ingest && python -m venv .venv && ./.venv/Scripts/python.exe -m pip install pytest
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

8. **Windows + Cyrillic:** always run Python with `-X utf8` or
   `PYTHONIOENCODING=utf-8`. The default `cp1252` console encoding raises on
   Macedonian product names.

## Known gaps

- Migrations have never been run against a live Postgres.
- `sizeer.com.mk` has no `robots.txt` and no sitemap; neither does the Sport
  Vision group. Discovery must use category pagination plus a brand-term
  search sweep.
- sizeer.com.mk and sport-m.com.mk share a platform, a host IP and an
  identical price for `M20325`. Probably one operator —
  `merchant.related_merchant_id` links them so the UI can collapse or badge
  them rather than looking padded.
- No fetcher yet, so nothing writes to the database.
