# Опрема — the third vertical

Design decisions for `category_kind = 'accessory'`, agreed before any crawl.
Written alongside the taxonomy notes that live in the migrations themselves:
V10 seeded the first non-footwear categories, V18 the apparel tree, **V23**
this one.

---

## 1. One kind, not two

The catalogue carried `accessory` (92 products) and `equipment` (13) as
separate kinds, and `web/src/lib/navigation.ts` listed only `equipment` — so
the smaller half was the reachable one and the larger was invisible in the
menu. Both arrived incidentally, swept up by footwear and apparel walks
rather than by any plan of their own, which is also why gender was NULL on 99
of those 105 offers.

V23 keeps `accessory`, moves the thirteen products to the parent, and deletes
the `equipment` leaf. The `equipment` value survives unused in the
`category_kind` enum: dropping an enum value in place is not worth a table
rewrite for a name nothing reads.

The storefront label is unchanged — **Опрема**. It was never the slug that
shoppers read.

## 2. The leaves

Eleven, from a recon of all six shops' own equipment sections.

| slug | Macedonian | shops | in the menu |
|---|---|---|---|
| `bags_backpacks` | Торби и ранци | 6 | yes |
| `caps_hats` | Капи, качкети и бандани | 6 | yes |
| `socks` | Чорапи | 6 | yes |
| `protective_gear` | Кациги, наочари и ракавици | 3 | yes |
| `balls_training` | Топки и фитнес опрема | 3 | yes |
| `skates_scooters` | Ролери и тротинети | 3 | yes |
| `swim_gear` | Опрема за пливање | 2 | hidden |
| `bottles_thermos` | Шишиња и термоси | 2 | hidden |
| `wallets` | Паричници | 1 | hidden |
| `shoe_care_laces` | Врвки и нега на обувки | 3 | hidden |
| `other_accessories` | Друго | 2 | hidden |

**Hidden means defined but not offered.** The row exists, the URL works, the
data has somewhere truthful to go — the menu and the sidebar simply do not
list it until the first sweep says it clears roughly a hundred products. An
entry serving six percent of the stock reads as an empty site rather than an
unfinished one, which is the same judgement the footwear tree records about
splitting sneakers by collar height. Flipping one on is a one-line change in
`navigation.ts` and needs no migration.

### Why these groupings

**A leaf can be no finer than the coarsest facet that feeds it.** Megasport
publishes one facet for bags, backpacks **and** wallets together — the slug
probe found it is `torbi-ranci-i-parichnici`, coarser still than the `Ранци и
Паричници` recon reported. `wallets` exists anyway, because wallet-led shops
are planned, but on that shop it can only ever be filled from titles.

**Helmets, eyewear and gloves are one leaf, not three.** On Megasport — the
only shop stocking helmets at all — `Кациги`, `Наочари`, `Ракавици` and `Ски
бандана` are one ski outfit sold off one shelf. Split apart, each would serve
a few dozen products.

**Winter hats are not their own leaf.** Only Sizeer facets `Зимски капи` apart
from `Капи`; Sport Vision and buzz publish a single merged `Качкети и капи`.
The split would have been fed by one shop's facets and guesswork everywhere
else.

**The labels enumerate rather than abstract** — `Кациги, наочари и ракавици`,
not `Заштитна опрема`. That is the existing house style (`Дуксери и блузони`,
`Кондури и чизми`, `Градници и топови`) and it also dodges the problem that
nobody looking for sunglasses reads a heading that says "protection".

### Not carried at all

Four kinds, listed in `mkagg.taxonomy.EXCLUDED_PHRASES` and refused by
`classify` before any rule runs.

**Pet accessories and Funko POP! figures** appear only at Sizeer and Sport-M,
which are one operator on one host (62.162.58.202), so neither can ever carry
a second independent price — and a comparison site with one seller has nothing
to compare. **Bicycles** are a different market. **Watches** are the arguable
one, since a sport watch is genuinely comparable, but there is no leaf for
them and inventing one for a single shop's shelf is how micro-buckets start.

Enforced in code rather than by omission from a facet plan, because a facet
plan is not the only way in — the Спецификации parser reads subgroups off the
product page, and "Додатоци за миленици" matched the `accessories` umbrella.
Excluded means uncategorised, which is visible in a count; filed somewhere
plausible is not. All reversible.

## 3. Rule order in `mkagg.taxonomy`

The accessory block runs after apparel and before footwear. Inside it, order
is load-bearing, because the narrow words sit inside the broad ones:

1. **`swim_gear` first.** `Капа за пливање` contains `капа` and `Наочари за
   пливање` contains `наочари`, so a swim cap would be headwear and swim
   goggles would be ski goggles if either ran ahead of it.
2. **`wallets` before `bags_backpacks`**, so the narrower word wins inside
   Megasport's combined facet.
3. Everything else, then the parent `accessories` as "equipment, kind
   unspecified".

**`wallets` keywords are singular only**, and that is not a style choice.
Megasport's facet slug is `ranci-i-parichnici`, which contains the plural — so
with the plural in the rule the URL alone matched, and since `wallets` runs
first, every backpack on that shop became a wallet. The whole-word padding
then does the work: `" parichnik "` is not inside `" ranci i parichnici "`,
while a title naming one still wins. Both halves are pinned by tests.

## 4. Gender

This is where Опрема departs from the other two verticals, and the numbers are
the reason.

| vertical | unisex share |
|---|---|
| apparel (live) | 0.2% |
| footwear (live) | 4.2% |
| Sport Vision Опрема (recon) | **55%** — 803 of 1,467 |
| Sport Reality Опрема (recon) | **66%** — 404 of 609 |

### An explicit Унисекс facet is now first-class evidence

Until this vertical, unisex could only be *inferred*: an article found in both
`maski+unisex` and `unisex+zenski` resolves to unisex because it was seen in
two departments. That is all the footwear and apparel plans can produce, and
it is enough for them.

It is not enough here. Sport Reality's equipment section carries no men's or
women's URL for its 404 unisex articles — only a Унисекс filter — and Sport-M
publishes 758 with no gender in any URL at all.

So `mkagg.taxonomy.FACET_GENDERS` now exists beside `KNOWN_GENDERS`: a
*department* may say unisex, a *title* still may not. `resolve_departments`
needed no change — a single `{"unisex"}` already collapses to `unisex`, and
`{"unisex", "men"}` does too, since both mean "adults, not only one
department".

### Sport-M's Спецификации table

Every product page carries one, and it states both fields the facet cannot:

```html
<div id="collapseOpis">
  <ul>
    <li><span class="opis">Возраст</span><b> — </b> <span>За возрасни</span></li>
    <li><span class="opis">Пол</span><b> — </b> <span>Унисекс</span></li>
    <li><span class="opis">Подгрупа</span><b> — </b> <span>Ранци</span></li>
  </ul>
</div>
```

`Возраст` is read **before** `Пол`, because a child's article carries both and
only one of them is the department it belongs in: a Speedo swim cap reads
`За бебиња (до 3 год.)` and `Пол — Машки`. Taking `Пол` there files an
infant's cap in the men's department, and kids mixed with an adult department
resolves to no gender at all downstream.

The values land in `RawOffer.category_hint` / `gender_hint` rather than new
fields, because `worker.run_once` overwrites a hint **only when the discovery
job carried one**. So a facet still wins and the page fills the gap — which is
exactly the precedence wanted.

## 5. The storefront

**Опрема's menu is category-first.** No Мажи / Жени / Деца columns.

At 55–66% unisex, and with a men's listing already including unisex
(`CatalogRepository.java`, the `gender` predicate), the two adult columns
would be roughly 85% the same links — thirty links presenting a choice that
barely discriminates. Two of six shops agree: Sport Reality's Опрема sits
outside its gender tabs entirely.

Kids is the one cut that earns its place — ролери, тротинети, кациги are a
genuinely different shelf — so it gets a link, not a column:

```
Опрема ▾
┌──────────────────────────────────────────────────────────────┐
│ Торби и ранци       Капи, качкети и бандани   Чорапи         │
│ Кациги, наочари…    Топки и фитнес опрема     Ролери и трот… │
├──────────────────────────────────────────────────────────────┤
│ Опрема за деца →                        Сета опрема →        │
└──────────────────────────────────────────────────────────────┘
```

This is a deliberate departure from shop convention, and there is precedent
for making one: `navigation.ts` already records why verticals sit above
gender when every MK shop does the opposite.

**The sidebar is unchanged** — `Оддел` (Сите / Мажи / Жени / Деца) and
`Категорија`, exactly as apparel got them.

**There is no Унисекс entry in `Оддел`, deliberately.** Because `?gender=men`
already includes unisex, a Унисекс option would return a strict *subset* of
what Мажи returns: a shopper clicking the more specific-sounding filter would
see fewer items than one clicking the broader, which reads as a broken site.
Unisex is a value in the data, not a department in the UI.

Since unisex dominates here, **Сите is the sensible default** on an Опрема
listing — the opposite of apparel, where a shopper usually picks gender first.

## 6. What is not settled

- **The facet slugs** are now measured for the men's/unisex suffix — see the
  crawl plan. The probe confirmed the `h`-drop on every Sport Vision family
  shop (`corapi`, not `chorapi`), caught megasport soft-404ing every guess,
  and caught `torbici` falling through to the parent catch-all. The women's
  and kids' suffixes, Sport Reality's Унисекс URL and the aspnet shops'
  PodGrupa codes are still unprobed.
- **`skates_scooters` rests on one shop.** `roleri` returns zero products on
  both Sport Vision and Sport Reality, but Sport-M carries three subgroups
  for it (106 Ролери, 107 Скироли, 111 Тротинети), so the leaf is real --
  just single-sourced.
- **Bicycles and watches have no leaf.** Sport-M files Велосипеди and Sizeer
  files Часовници under the same accessories group; neither maps to anything
  and neither has been decided. See the crawl plan.
- **`18-24м.`** parses as `size_system = 'numeric'` rather than an age band —
  378 variants, 147 of them live. A sizing-parser gap, not a taxonomy one.
- **The Albanian labels** in V23 are a best effort and want a native reading
  before the `sq` locale is ever served.
