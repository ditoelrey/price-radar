# Опрема — crawl plan, for review

**No products have been fetched.** The slug probe has run — 71 requests — and
its findings are folded in below. Taxonomy decisions live in
[accessories-vertical.md](accessories-vertical.md); the raw output is in
`accessories-slug-probe.log`.

---

## 0. The slug probe — done, and it changed the plan

Recon gave the shops' Macedonian **labels**, not their URLs. The probe asked
two questions per candidate, because they fail differently:

1. **Does it answer?** A guessed slug 404s silently inside a facet walk — the
   section is never crawled and nothing says so.
2. **Can a rule read it?** A slug can answer perfectly and still be invisible
   to `mkagg.taxonomy`. This is the one that already cost 835 shorts offers.

It found three things.

### The h-drop, on every Sport Vision family shop

| guessed | | confirmed | items |
|---|---|---|---|
| `chorapi` 404 | → | **`corapi`** | 30 |
| `kachketi-i-kapi` 404 | → | **`kacketi-i-kapi`** | 26 |
| `shishe-za-voda` 404 | → | **`sise-za-voda`** | 24 |
| `naochari-za-plivanje` 404 | → | **`naocari-za-plivanje`** | 12 |
| `oprema-za-chistenje` 404 | → | **`oprema-za-cistenje`** | 7 |
| `kachket` 404 | → | **`kacket`** | 6 |

Two were wrong in *both* spellings: `vreka-za-trening` and `vrekja-za-trening`
both 404, so Sport Vision's `Вреќа за тренинг` is named something else and is
**still unlocated**. `ranci` 404s on Sport Reality while `torbi` answers.

### megasport soft-404s, so its first pass was worthless

It returned 200 for every candidate including both spellings of everything.
A slug that cannot exist returns the same 54 products:

```
/kategorija/mazhi/oprema-mazhi/zzzz-nonsense-slug/   200, 54 products
```

Its real paths were read off its own navigation instead, and they carry the
gender a second time — the habit its apparel plan already records. The probe
now fetches a nonsense slug per shop first and marks anything matching it
`soft 404`, whatever the status line says.

Two consequences for this plan: **`torbi-ranci-i-parichnici` is one facet for
three things**, not two, and there is a **separate `ski-oprema` tree outside
the gender hierarchy** that recon did not mention.

### `torbici` fell through to the catch-all

`zheni/oprema-zheni/torbici` resolved to `accessories` — the parent — rather
than to nothing. It *looks* like an answer, and thirty women's bags would have
sat in "equipment, kind unspecified" with nothing recording that they had ever
been labelled. The word is now in the `bags_backpacks` rule, and the probe
counts a parent fall-through as a miss for any facet that is not an umbrella.

**Result: 43 slugs answering, every one mapping to a leaf.**

## 1. Per-merchant plans — confirmed slugs

Counts are products on the first page. The Sport Vision family and megasport
both page at 30, so **30 means "at least 30"** and anything lower is a
complete section.

### sportvision — `/mk/{slug}/{gender}/vozrasni`

| slug | items | leaf |
|---|---|---|
| `corapi` | 30+ | socks |
| `kacketi-i-kapi` | 26 | caps_hats |
| `ranec` | 26 | bags_backpacks |
| `sise-za-voda` | 24 | bottles_thermos |
| `oprema-za-plivanje` | 25 | swim_gear |
| `topka` | 25 | balls_training |
| `golmanski-rakavici` | 14 | protective_gear |
| `naocari-za-plivanje` | 12 | swim_gear |
| `podloga` | 3 | balls_training |
| `roleri` | **0** | skates_scooters |
| `oprema` (umbrella, last) | 30+ | accessories |

### sportreality — `/mk/{slug}/…`

| slug | items | leaf |
|---|---|---|
| `corapi` | 24 | socks |
| `topka` | 24 | balls_training |
| `torbi` | 15 | bags_backpacks |
| `torbica` | 13 | bags_backpacks |
| `kacket` | 6 | caps_hats |
| `roleri` | **0** | skates_scooters |
| `trotinet` | **0** | skates_scooters |
| `oprema` (umbrella, last) | 24 | accessories |

### buzz — `/mk/{slug}/{gender}/za-vozrasni`

| slug | items | leaf |
|---|---|---|
| `kacketi-i-kapi` | 32 | caps_hats |
| `corapi` | 27 | socks |
| `ranec` | 25 | bags_backpacks |
| `torbica` | 19 | bags_backpacks |
| `torba` | 13 | bags_backpacks |
| `oprema-za-cistenje` | 7 | shoe_care_laces |

### megasport — full paths, gender repeated in the slug

| path | items | leaf |
|---|---|---|
| `mazhi/oprema-mazhi/chorapi-oprema-mazhi` | 30+ | socks |
| `mazhi/oprema-mazhi/kapi` | 30+ | caps_hats |
| `mazhi/oprema-mazhi/torbi-ranci-i-parichnici` | 30+ | bags_backpacks |
| `mazhi/oprema-mazhi/rakavici-oprema-mazhi` | 12 | protective_gear |
| `mazhi/oprema-mazhi/ski-bandana` | 3 | caps_hats |
| `mazhi/oprema-mazhi/naochari` | 1 | protective_gear |
| `mazhi/oprema-mazhi/kacigi-oprema-mazhi` | 1 | protective_gear |
| `zheni/oprema-zheni/torbici` | 30+ | bags_backpacks |
| `zheni/oprema-zheni/rakavici-oprema-zheni` | 11 | protective_gear |
| `zheni/oprema-zheni/ski-bandana-oprema-zheni` | 3 | caps_hats |
| `zheni/oprema-zheni/kacigi-oprema-zheni` | **0** | protective_gear |
| `deca/oprema-deca/ranec` | 26 | bags_backpacks |
| `deca/oprema-deca/rakavici` | 23 | protective_gear |
| `deca/oprema-deca/kacigi-oprema-deca` | **0** | protective_gear |
| `ski-oprema/naochari-za-skijane` | 16 | protective_gear |

No catch-all, for the reason its apparel plan gives: that tree is not clean —
there is a legacy `/deca/oprema/` beside `/deca/oprema-deca/`.

### sportm and sizeer — numeric subgroups

`Grupa=03` **confirmed** on both, and the segments return distinct product
sets (a nonsense `Segment=99` gives 0 on Sport-M and 500 on Sizeer, so these
are real rather than defaults).

```
sportm   Segment=06  Опрема, standalone, no gender in any URL
         Segment=03|04|05  Додатоци, men / women / kids
sizeer   Segment=51|52|53  Додатоци, men / women / kids
```

Sport-M's `Segment=06` was seen earlier carrying PodGrupa 511 (balls), 111
(scooters), 277 (swim caps), 507 (backpacks), 106 and 348 (fitness).

## 2. The second pass — gaps closed

### Gender suffixes work, including the explicit unisex one

The suffixes already in `discover.py` filter correctly on leaf facets:

```
sportvision /mk/ranec/    men 26   women 27   unisex 26   kids 24
sportreality /mk/corapi/  men 24   women 24   unisex 24   kids 24
                          men != women, men != unisex
```

`ranec` is the proof: 26 against 27 means the department is really being
applied. Where counts come back identical it is the 30-item page cap plus
unisex dominance, not a broken filter — an earlier reading of this as "the
suffix is ignored" was wrong and is corrected here.

**Sport Reality's bare `unisex/vozrasni` returns a set distinct from both
adult departments** — 20 of its 24 men's results are shared, the rest are
not. That is the URL the whole `FACET_GENDERS` change exists for, and it
exists.

buzz's kids suffix is `za-tinejdzeri+mali-deca+za-bebe`, already in
`_BUZZ_GENDERS`; the `deca/za-deca` guess 404s.

### The aspnet subgroup dictionary, read off the shops

Both publish their whole PodGrupa list on every catalogue page. The accessory
half:

| code | label | leaf |
|---|---|---|
| 518 | Чорапи | socks |
| 493 | Капи | caps_hats |
| 591 | Бандани | caps_hats |
| 782 | Зимски капи | caps_hats *(sizeer only)* |
| 507 | Ранци | bags_backpacks |
| 512 | Торби | bags_backpacks |
| 761 | Торбички | bags_backpacks |
| 096 | Наочари | protective_gear |
| 487 | Голмански ракавици | protective_gear |
| 494 | Костобрани | protective_gear |
| 277 | Капи за пливање | swim_gear |
| 497 | Наочари за пливање | swim_gear |
| 106 / 107 / 111 | Ролери / Скироли / Тротинети | skates_scooters |
| 628 / 667 | Држачи за склекови / Баланс топка | balls_training |
| 519 / 678 | Шишиња / Термос | bottles_thermos |
| 607 | Врвки | shoe_care_laces |
| 489 / 704 | Друго / Заштитна маска за лице | other_accessories |
| 798 | Додатоци за миленици | *excluded* |
| 742 | Funko POP! фигури | *excluded* |

### Sport Vision's real sections

`Вреќа за тренинг` **does not exist as a URL** — it is a filter label, not a
section. Enumerating the shop's own page found eight sections the candidate
list never had:

```
kaciga                        protective_gear
pribor-i-dodatoci-za-obuvki   shoe_care_laces
oprema-za-trening             balls_training
oprema-za-fudbal              accessories
oprema-za-ping-pong           accessories
oprema-za-planinarenje        accessories
oprema-za-skijanje            accessories
ostanata-oprema               accessories
```

The five resolving to the parent do so correctly — a football shelf holds
balls, shin guards and gloves together, so no leaf is truer than "equipment,
kind unspecified".

### Four taxonomy bugs, found and fixed

The classify half of the probe earned its place again:

| section | was | now |
|---|---|---|
| `Средство за чистење на обувки` | **footwear** | shoe_care_laces |
| `Средство за заштита од влага` | nothing | shoe_care_laces |
| `Средство за отстранување на миризби` | nothing | shoe_care_laces |
| `Комбинирана четка за велур кожа` | nothing | shoe_care_laces |

The first is the worst: the word обувки at the end of the phrase carried a
bottle of cleaning spray into the footwear umbrella — a whole vertical away.
All four are pinned by tests.

## 2a. What the catalogue does not carry — decided

Four kinds, excluded, and the exclusion is **enforced in
`mkagg.taxonomy.is_excluded` rather than only by leaving a subgroup out of a
facet plan**. A facet plan is not the only way in: Sport-M's Спецификации
parser reads `Подгрупа` straight off the product page, and "Додатоци за
миленици" matched the `accessories` umbrella — so a dog collar reached by any
other shelf would have been filed as equipment of unspecified kind. Excluded
now means *uncategorised*, which shows up in a count, rather than *plausible*,
which does not.

| subgroup | shops | why |
|---|---|---|
| 798 Додатоци за миленици | sizeer, sportm | one operator, so never comparable; not sporting goods |
| 742 Funko POP! фигури | sizeer | same |
| 649 Велосипеди | sportm | a different market, not an accessory |
| 740 Часовници | sizeer | genuinely comparable, but no leaf — and inventing one for a single shop's shelf is how micro-buckets start |

Pinned by tests, including the near miss: **Бициклистички is not Велосипед**,
so cycling shorts stay in `leggings` with their 56 products.

## 3. Budgets and timing

Drain rates measured from the apparel sweeps: ~1.15 s/product on the Sport
Vision family and megasport, **2.24 s/product** on the aspnet shops, which
need a second POST per product.

| shop | products (recon) | discovery | drain | wall clock |
|---|---|---|---|---|
| sportvision | 1,467 | ~135 | 1,467 | **~27 min** |
| sportreality | 609 | ~60 | 609 | ~12 min |
| buzz | 500 | ~50 | 500 | ~10 min |
| megasport | 579 | ~70 | 579 | ~12 min |
| sizeer | 800 | ~90 | 1,600 | ~30 min |
| sportm | 1,400 | ~150 | 2,800 | **~52 min** |
| **total** | **~5,350** | ~555 | ~7,555 | |

The product counts are **recon figures, not measured** — if they have drifted,
every line drifts with them. megasport gains a little for the `ski-oprema`
tree.

```
discover -m <slug> --vertical accessory --max-requests 400 --max-jobs 8000 --rps 1.0
```

`--max-jobs 8000`, not 3000. Sport Vision's apparel sweep truncated **silently**
at 3,500; the ceiling costs nothing when the queue is smaller than it.

**No `--full-sweep`** on any first run. There is no baseline for this vertical,
so the relative gate checks are skipped and the run is a clean bootstrap.

### Lanes

sizeer and sport-m resolve to the same host (62.162.58.202) and share one
sequential lane. The other four are separate hosts.

```
lane A   sizeer → sportm          ~82 min   ← critical path
lane B   sportvision              ~27 min
lane C   sportreality             ~12 min
lane D   buzz                     ~10 min
lane E   megasport                ~12 min
```

Sequential is ~2h20; three or more lanes puts the critical path at **~82
minutes**. That figure assumes Sport-M at ~1,400 unique after overlap between
its two sections — if the overlap is small it is 1,758 products and lane A
goes to ~96 minutes.

Images afterwards, per shop: ~5,350 products at ~1 rps is another ~90 minutes
and, at the ~120 KB average across these six shops, roughly **650 MB** on top
of the current 3.7 GB.

## 3a. The plans, written

`ACCESSORY_FACET_PLANS` is in `discover.py`, **340 facets** over the six
shops, every slug confirmed by the probe:

| shop | facets | unisex walks | genderless |
|---|---|---|---|
| sportvision | 76 | 19 | — |
| sportreality | 32 | 8 | — |
| buzz | 28 | 7 | — |
| megasport | 15 | — | 1 *(ski tree)* |
| sizeer | 81 | — | — |
| sportm | 108 | — | 27 *(Segment=06)* |

Three things in there are not in the other two verticals' plans.

**Unisex is walked outright** on the Sport Vision family — a bare
`unisex/vozrasni` beside the two bundled suffixes. It is a fourth walk per
category and it is what genders 55–66% of the catalogue correctly instead of
leaving it to be inferred.

**sportvision and sportreality have separate lists.** Apparel shares one; here
one shop writes `kacketi-i-kapi` and the other `kacket`, and `ranec` answers
on one and 404s on the other.

**27 Sport-M facets carry no gender at all** — `Segment=06`, where the
Спецификации parser supplies it. A facet claiming a department it cannot see
would give `resolve_departments` two answers to reconcile instead of one to
find.

The plumbing around them: **V24** adds `accessory_parse` to `fetch_kind`
(same reasoning as V19 — `ingest_run_baseline` is keyed on it), `run_kind_for`
routes on `ACCESSORY_SLUGS`, `promote_run` scopes delisting to the matching
category kind, and `--vertical accessory` is a CLI choice.

Discovery is now **340 requests minimum** rather than the ~555 estimated —
the per-shop table below still holds once pagination is added, since most
aspnet subgroups return a single page or none.

## 3b. Run 38 — sportreality, and the lesson from it

```
discovery   94 requests  ->  609 product URLs
drain       609 fetched  0 errors  (639s)
promote     run 38 sportreality/accessory_parse  OK
            offers=609  promoted=609  unmatched=0  sku_fill=100%
            variants=2,695  new_products=592
```

609 discovered against 609 on recon, zero errors, gate OK on the first
`accessory_parse` run.

**The explicit unisex facet works.** 351 articles resolved to `unisex` with
`gender_source = 'facet'`, against 187 kids, 38 women, 33 men — and **zero
NULL**. That is the whole `FACET_GENDERS` change validated on live data, and
it is what the other five shops now rest on.

### The plan was wrong, and only the audit could tell us

The first pass left **326 of 609 offers on the umbrella**. The section list
had eight entries; the shop uses forty-eight. `kapa` holds 92 offers, `ranec`
60, `vreka-za-trening` 11 — the section an earlier draft of this document
called unlocated.

The probe was not at fault. It confirmed everything it was asked and could
say nothing about what it was never asked, because its candidates came from
recon labels. **A probe validates a list; it cannot discover one.**

Rebuilding `_SR_ACCESSORY` from the URL sections of ingested products — the
one source that cannot omit what the shop sells — then re-walking the facets
and re-deriving:

| | before | after |
|---|---|---|
| `accessories` catch-all | 334 | **42** (6.9%) |
| `bags_backpacks` | 54 | 125 |
| `caps_hats` | 18 | 110 |
| `protective_gear` | 17 | 93 |

The 42 remaining are the genuinely ambiguous sections — `set`, `potnik`,
`traka`, `rosuli`, `rakav` — plus `ostanata-oprema` and the excluded
`velosiped`. The umbrella is the honest answer for those.

### So the per-shop recipe is two passes, not one

1. **Sweep** with the umbrella last. It catches everything, whatever the leaf
   list misses.
2. **Audit** the URL sections of what arrived, and classify each.
3. **Extend** the plan from that list.
4. **`facets`** walk to record the labels, then **`derive`**.

Steps 2–4 cost about four minutes and moved 292 products into a real leaf on
this shop. Expect sportvision's nineteen-section list and buzz's seven to be
just as incomplete.

## 4. Order of operations

1. ~~Finish the probe~~ — done.
2. ~~Write `ACCESSORY_FACET_PLANS`~~ — done.
3. **sportreality first.** Smallest shop that exercises the explicit `unisex`
   facet, which is the riskiest new path. (If you would rather validate the
   common case first, buzz at ~500 products and ~10 minutes is the
   alternative — it is also the most typical of the six.)
4. **sportm second**, because it is the one that exercises the Спецификации
   parser against 758 otherwise-genderless articles.
5. The remaining four in any order, lanes permitting.
6. `derive`, then review leaf counts and decide which hidden leaves to show.
7. Images per shop.

## 5. What to check after the first shop

- Gate decision and `sku_fill`. A DEGRADED like buzz's apparel run is worth
  understanding before four more shops land.
- **`product.gender` spread** — how much resolves to `unisex`, how much to
  NULL. NULL is excluded from every gender filter, so a large NULL share is
  the signal that a plan is missing its gender.
- Leaf spread against the hidden-leaf threshold.
- A URL-section audit over the new offers — the same query that found
  `/mk/sorc/`. The probe checks the slugs we *expect*; the audit catches the
  ones we never thought to probe.

## 6. One leaf in doubt, one rescued

**`skates_scooters` survives.** `roleri` returns 0 on both Sport Vision and
Sport Reality, but Sport-M carries *three* subgroups for it — 106 Ролери, 107
Скироли, 111 Тротинети — so the leaf has a real source. Its volume still
comes from one shop, which is worth knowing before it keeps a menu entry.

**`protective_gear` is thinner than recon suggested.** Megasport's helmet
sections are empty — 0 for women, 0 for kids, 1 for men — so the leaf leans on
gloves (12 + 11 + 23) and the ski tree (16). Probably seasonal, worth
re-checking rather than assuming.
