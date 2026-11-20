"""Deciding what kind of thing a product is, and who it is sold to.

This exists because of a bug the serving API made visible: a pack of socks was
filed under ``sneakers``. Not through a matching failure -- the article code
was read correctly and the offer joined the right product -- but because
``create_product`` hard-coded the footwear category for everything it created.
Megasport's discovery walks a sitemap containing its *entire* catalogue, so
socks, ski leggings and helmets all arrived labelled as sneakers.

Three design choices worth keeping:

**Unknown means no category, never a guessed one.** ``product.category_id`` is
nullable and that is the correct value for a title we cannot read. Defaulting
to a plausible category is precisely how the socks got in; a null shows up in
admin as something to look at, while a wrong value looks finished. Since V17
``product.gender`` works the same way, for the same reason.

**Keywords live here, in code, not in the database.** They need the same
Cyrillic/Latin transliteration as everything else, they change with the
parsers rather than with the data, and they are worth unit-testing against
real titles.

**The title is the weak source.** Four of the six shops put no category word
in their titles at all -- sportvision, sportreality, sizeer and sportm all
write "adidas Supernova Rise", brand and model and nothing else -- and gender
words reach 4.9 percent of titles at best. What this module reads is a
fallback. The strong source is the facet a product was discovered through,
which lands in ``merchant_offer`` and is combined with these guesses by
:mod:`mkagg.derive`. Hence ``product.category_source``: a title-derived value
exists to be improved on.
"""
from __future__ import annotations

import re

from .normalize import translit_mk

#: Ordered most specific first: a title reading "Патики" *and* "Sock" is a
#: sock in a sneaker-shaped category tree, so the sock rule has to win. The
#: first matching rule decides.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    # --- not footwear, but sold alongside it and easily mistaken for it ----
    ("socks", ("chorapi", "corapi", "shtuci", "stuci", "shtucni", "stucni",
               "sok 3p", "crew sock", "ankle sock",
               "quarter sock", "no show sock", "socks", "sock 3p")),
    # --- apparel, the eleven leaves V18 seeded ----------------------------
    # Order inside this block is doing real work, because several of these
    # words contain each other. "Шорцеви за пливање" is swimwear and not
    # shorts; "Долен дел тренерки" is trousers and not a tracksuit; "Ски
    # панталони" is trousers. The narrower phrase has to be tried first, the
    # same rule the socks entry above follows for the same reason.
    ("swimwear", ("kostim za kapenje", "kostimi za kapenje",
                  "shorcevi za plivanje", "shorc za plivanje", "kupakji",
                  "bikini", "swimsuit", "swim short", "swim trunk")),
    # Tracksuit *bottoms* before tracksuits, and jeans and ski pants with
    # them: all four are the thing you put your legs in.
    ("trousers", ("dolen del trenerki", "dolni delovi trenerki",
                  "dolna trenerka", "pantaloni", "farmerki", "ski pantaloni",
                  # "jogger" is absent: Skechers sells a shoe called the
                  # "Upper Neo Jogger", and these shops name the category
                  # in Macedonian anyway.
                  "trousers", "jeans", "sweatpant")),
    # Singular AND plural: megasport writes "Долна тренерка" (singular)
    # while other titles use "Тренерки", and a plural-only list missed the
    # first, leaving "Dolna Trenerka" inside a product name.
    ("tracksuits", ("trenerka", "trenerki", "komplet", "kompleti",
                    "tracksuit", "jumpsuit", "kombinezon")),
    ("leggings", ("helanki", "helanka", "legging", "tajice",
                  "biciklistichki", "biciklisticke", "biciklisticki",
                  "biciklisticka", "ski helanki")),
    # "Топ" is deliberately absent. It transliterates to "top", and
    # "COURT BOROUGH LOW TOP" is a shoe -- this block runs before the
    # footwear rules, so a bare "top" here would file trainers as sports
    # bras. The shops' own `top` facet still reaches this category.
    ("sports_bras", ("gradnik", "gradnici", "sportski gradnik", "bodi",
                     "crop top", "sports bra", "bralette")),
    ("dresses_skirts", ("fustan", "fustani", "suknja", "suknji",
                        "zdolnishte", "zdolnishta", "dress", "skirt")),
    ("underwear", ("pododelo", "dolna obleka", "bokserici", "bokserki",
                   "gakji", "underwear", "brief")),
    # "polar" singular is absent, for the same reason: Skechers'
    # "ILLUMI-BRIGHTS - POLAR STEPPE" is a shoe. The shops write the
    # category as "Полари".
    ("hoodies", ("dukser", "dukseri", "duks", "hoodie", "bluzon", "bluzoni",
                 "polari", "djemper", "djemperi", "sweatshirt", "fleece")),
    ("jackets", ("jakna", "jakni", "jacket", "elek", "eleci", "prsluk",
                 "vetrovka", "vetrovki", "softshel", "softshell",
                 "shushkavec", "shushkavci", "suskavec", "suskavci",
                 "teksas jakni", "vest",
                 "windbreaker", "parka", "anorak")),
    # Plural only. "short" singular matched UGG's "Чизми CLASSIC SHORT II",
    # a boot -- and this block runs before the footwear rules, so it won.
    #
    # The h-less spellings are the shops' own URL slugs: Шорц is "sorc" in a
    # sportvision path and "shorc" out of the transliterator, so the section
    # holding 835 offers was unreadable to every rule. Same for Шушкавец and
    # Кошула above. These are slugs, not English, so the singular is safe.
    ("shorts", ("shorc", "shorcevi", "shorts", "sorc", "sorcevi",
                "sorcevii", "bermudi")),
    ("tshirts", ("maica", "maici", "majica", "maici so dolgi rakavi",
                 "dres", "dresovi", "koshula", "koshuli", "kosula",
                 "kosuli", "polo", "fanela",
                 "t shirt", "tshirt", "tee", "jersey", "shirt")),
    # Clothing whose kind the title does not narrow. Last of the apparel
    # rules, and still a real answer: the parent category means "clothing,
    # kind unspecified", exactly as `footwear` does for shoes.
    ("apparel", ("obleka", "aktivna obleka", "vesta", "apparel")),
    # "Штитник" (shin guard) earns its place by having been misread: the
    # title "Штитник TIRO SG EU CLB" fell through to the footwear rules and
    # the SG there -- soft-ground studs on a football boot -- made a shin
    # guard into a pair of cleats.
    # --- Опрема, the ten leaves V23 seeded ---------------------------------
    # Order inside this block is load-bearing, because the narrow words sit
    # inside the broad ones. Each of these was a real facet on at least two
    # shops during recon.
    #
    # Swimming comes first and is the reason: "Капа за пливање" contains
    # "капа" and "Наочари за пливање" contains "наочари", so a swim cap would
    # be headwear and swim goggles would be ski goggles if `caps_hats` or
    # `protective_gear` ran ahead of it.
    ("swim_gear", ("plivanje", "za plivanje", "oprema za plivanje",
                   "kapa za plivanje", "kapi za plivanje",
                   "naocari za plivanje", "naochari za plivanje",
                   "maska i perai", "perai", "chepovi za ushi",
                   "cepovi za usi", "shtipka za nos", "stipka za nos",
                   "swim", "swimming", "goggles")),
    # Wallets before bags, and that ordering is the whole reason the leaf can
    # exist: megasport publishes one facet, "Ранци и Паричници", for both. A
    # wallet is only ever recognisable there by its own name.
    #
    # Singular only, and that is not a style choice. megasport's facet slug
    # is `ranci-i-parichnici`, which contains the plural -- so with the
    # plural here the URL alone matched, and since this rule runs before
    # `bags_backpacks`, every backpack on that shop became a wallet. The
    # whole-word padding then does the work: " parichnik " is not inside
    # " ranci i parichnici ", while a title that names one still wins.
    #
    # It costs nothing today. No shop publishes a wallets-only facet; if one
    # ever does, its plural slug goes in `bags_backpacks` first, the way the
    # combined facet would have had to.
    ("wallets", ("parichnik", "paricnik", "novchanik", "novcanik",
                 "wallet")),
    # Helmets, eyewear and gloves are one leaf, not three. On megasport --
    # the only shop that stocks helmets at all -- Кациги, Наочари, Ракавици
    # and Ски бандана are one ski outfit sold off one shelf, and split apart
    # each would be a menu entry serving a few dozen products.
    #
    # "Штитник" earns its place by having been misread: the title "Штитник
    # TIRO SG EU CLB" fell through to the footwear rules and the SG there --
    # soft-ground studs on a football boot -- made a shin guard into cleats.
    # The `h`-less spellings are the shops' own URLs again: Sport Reality
    # writes `/mk/stitnik/` for 11 offers and `/mk/sal/` for one, while the
    # transliterator produces `shtitnik` and `shal`. The first URL-section
    # audit after the first Опрема sweep found both, the same way the apparel
    # one found `/mk/sorc/`.
    ("protective_gear", ("kaciga", "kacigi", "helmet", "naocari", "naochari",
                         "rakavici", "rakavica", "gloves", "golmanski",
                         "kostobrani", "kostobran", "sticnici", "shtitnik",
                         "shtitnici", "stitnik", "stitnici",
                         "stitnik za zabi", "shtitnik za zabi", "bandazer",
                         "stegac", "stegach", "suspenzor", "mouthguard",
                         "shin guard", "visor")),
    ("caps_hats", ("kapa", "kapi", "kachket", "kacket", "kachketi",
                   "kacketi", "shapka", "shapki", "bandana", "bandani",
                   "zimski kapi", "zimska kapa", "podkapa", "traka za glava", "traka za kosa",
                   "grejac za vrat", "grejach za vrat", "headband",
                   "beanie", "cap", "shal", "sal")),
    # "torbici" is megasport's spelling for the women's bag facet, and it is
    # here because the slug probe caught it falling through to the parent
    # `accessories` -- a quieter failure than matching nothing, and one that
    # would have put thirty women's bags in the catch-all.
    ("bags_backpacks", ("ranec", "ranci", "backpack", "torba", "torbi",
                        "torbici", "torbica", "torbichka", "torbicka",
                        "torbichki", "torbicki", "chanta", "canta",
                        "vreka za trening", "vrekja za trening", "bag",
                        "duffel", "holdall", "kufer", "kuferi",
                        "suitcase")),
    ("skates_scooters", ("roleri", "roler", "rollers", "trotinet",
                         "trotineti", "scooter", "skiroli", "skirol",
                         "klizalki", "ostrica za klizalki", "skateboard",
                         "skejtbord")),
    ("balls_training", ("topka", "topki", " ball", "lopta", "raketa",
                        "racket", "shipka", "dumbbell", "tegovi", "podloga",
                        "prostirka", "balans topka", "drzhachi za sklekovi",
                        "drzaci za sklekovi", "sklekovi", "jaze za skokanje",
                        "oprema za trening", "pumpa za topka", "pumpa",
                        "fitnes rekvizit", "pomagalo za sklekovi",
                        "mat", "yoga")),
    ("bottles_thermos", ("shishe", "shishinja", "sise za voda", "termos",
                         "termosi", "bidon", "bottle", "flask", "thermos")),
    # Before the footwear rules, and these phrases are why. Sizeer files
    # "Средство за чистење на обувки" under its accessories group, and the
    # word обувки at the end of it carried the whole thing into the footwear
    # umbrella -- a cleaning spray classified as a shoe. Its three siblings
    # (водоотпорно средство, средство за миризби, четка за велур) matched
    # nothing at all. The probe found all four.
    ("shoe_care_laces", ("vrvki", "vrvka", "vrvci", "laces", "shoelace",
                         "oprema za chistenje", "oprema za cistenje",
                         "chistenje na obuvki", "cistenje na obuvki",
                         "sredstvo za chistenje", "sredstvo za cistenje",
                         "sredstvo za zashtita", "sredstvo za zastita",
                         "sredstvo za otstranuvanje", "chetka za velur",
                         "cetka za velur", "pribor i dodatoci za obuvki",
                         "sprej za obuvki", "sprej", "vloski", "vloshki",
                         "nega na obuvki", "shoe care")),
    # Last of the accessory leaves, and a real answer rather than a shrug:
    # the shops put face masks and odds and ends in a "Друго" of their own.
    # Keyrings and charms: buzz shelves them as Украс and Привезок, and
    # neither is a leaf of its own at seven offers between them.
    ("other_accessories", ("drugo", "ostanato", "maska za lice",
                           "zashtitna maska", "zastitna maska",
                           "ukras", "ukrasi", "privezok", "privezoci",
                           "keyring", "keychain")),
    # Equipment whose kind the title does not narrow, then the umbrella --
    # the parent category, meaning "equipment, kind unspecified", exactly as
    # `footwear` and `apparel` do for theirs.
    ("accessories", ("dodatoci", "dodatok", "oprema", "accessories",
                     "accessory")),

    # --- footwear, four canonical buckets (V17) ----------------------------
    # One named exception, before anything else reads a model name. Asics
    # sells a tennis shoe called the "Court Slide", and the slides rule below
    # matched it on the word "slide" -- the only false positive in 44 real
    # titles containing that word, the rest of which are genuine slides. A
    # keyword list cannot tell a product line from a noun, so the line is
    # named here rather than weakening the rule that works.
    ("sneakers", ("court slide",)),
    # Cleats first among the footwear rules: a boot for artificial turf is
    # listed by sportm as "Патики за вештачка трева", so the generic sneaker
    # word is present in a title that means something more specific.
    # The surface codes are included because they are the manufacturers' own
    # and unambiguous in a footwear catalogue: FG firm ground, AG artificial
    # grass, SG soft ground, TF turf. "IC" (indoor court) is left out -- two
    # letters that common would match more than it caught.
    # Model lines, after every non-footwear rule above and never before
    # them. adidas sells Predator goalkeeper gloves and shin guards as well
    # as Predator boots; none are in the catalogue today (checked: of 58
    # distinct Predator titles, 46 F50 and 143 Terrex, not one carries a
    # glove, guard, ball or garment word) but the day one arrives it must
    # still be an accessory, and rule order is what guarantees that rather
    # than luck.
    ("cleats", ("predator", "f50")),
    ("cleats", ("kopacki", "kopachki", "kopacka", "cleat", "futsal",
                "fudbal sala", "sala", "veshtachka treva",
                "veshtachka trava", "turf", "fg", "ag", "sg", "tf")),
    # Before shoes_boots, so "Обувки за вода" is read as water footwear
    # rather than as the generic shoe word it also contains.
    ("slides_sandals", ("papuci", "papuchi", "slide", "flip flop", "nanule",
                        "sandali", "sandal", "apostolki", "za voda",
                        "water shoe", "aqua shoe")),
    # Outdoor and hiking footwear. Terrex is adidas's outdoor line and the
    # range stocked here is hiking through and through -- AX4, EASTRAIL,
    # HIKSTER, HYPERHIKER, ANYLANDER MID GTX -- so it belongs with shoes and
    # boots rather than with Патики, whatever the shops' own shelves say.
    #
    # They mostly say otherwise, and it is worth knowing why that does not
    # matter here: of 261 Terrex offers, the shops file 228 under a sneakers
    # facet and 24 under boots. Facet beats title in `derive_category`, so
    # this rule does not overrule them -- it decides the products no facet
    # ever reached, which is exactly the "kind unspecified" bucket it was
    # written for.
    ("shoes_boots", ("terrex", "trailmaker", "planinarenje", "trekking")),
    ("shoes_boots", ("cizmi", "chizmi", "cizme", "boots", "gojzerica",
                     "konduri", "kondur", "baletanki", "ballerina",
                     "mokasini", "loafer")),
    ("sneakers", ("patiki", "patike", "patika", "sneaker", "tenisice",
                  "running shoe")),
    # Generic footwear nouns: a real shoe, but not specific enough to tier.
    # This is the parent category, and a legitimate answer -- see V17.
    ("footwear", ("obuvki", "obuvka", "shoes", "shoe", "calz")),
]

#: Gender words, most specific first. Weak on purpose: these reach a few
#: percent of titles, and exist only for products no facet covered. The
#: single-letter conventions some shops use ("SUPERNOVA RISE W", "TENSAUR RUN
#: EL C") are deliberately absent -- a bare "W" or "C" matches far too much to
#: be evidence, and the facet knows anyway.
_GENDER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("kids", ("deca", "za deca", "detski", "detska", "detsko", "kids", "kid",
              "junior", "bambino", "bebe", "infant")),
    ("women", ("za zheni", "zheni", "zhenski", "zhenska", "women", "womens",
               "wmns", "ladies")),
    ("men", ("za mazhi", "mazhi", "mashki", "mashka", "men", "mens")),
]

#: The eleven canonical apparel leaves seeded by V18, plus the parent.
#:
#: No title rule returns any of these yet -- apparel classification is its
#: own piece of work. They are declared here because the size parser needs to
#: know whether an offer came from an apparel facet: "38" is a dress size on
#: one and a shoe size on the other, and only this tells them apart.
APPAREL_SLUGS = frozenset({
    "apparel", "tshirts", "hoodies", "jackets", "trousers", "tracksuits",
    "shorts", "leggings", "sports_bras", "underwear", "dresses_skirts",
    "swimwear",
})

#: The ten Опрема leaves V23 seeded, plus the parent and `socks`, which V10
#: placed under this kind before there was a vertical to put it in.
#:
#: `equipment` is gone: V23 folded that kind into `accessory` and deleted its
#: one leaf, so a rule returning it would now null the category instead.
ACCESSORY_SLUGS = frozenset({
    "accessories", "socks", "caps_hats", "bags_backpacks", "wallets",
    "protective_gear", "swim_gear", "balls_training", "bottles_thermos",
    "skates_scooters", "shoe_care_laces", "other_accessories",
})

#: Category slugs this module can return. Kept in step with V4 + V10 + V17 +
#: V18 + V23 so a typo here fails a test rather than silently nulling a
#: category.
KNOWN_SLUGS = frozenset({
    "footwear", "sneakers", "cleats", "shoes_boots", "slides_sandals",
}) | APPAREL_SLUGS | ACCESSORY_SLUGS

#: Which of those are footwear, i.e. the MVP's storefront. ``footwear`` itself
#: is in here: it is the parent row, and means "a shoe, kind unspecified".
FOOTWEAR_SLUGS = frozenset({
    "footwear", "sneakers", "cleats", "shoes_boots", "slides_sandals",
})

#: Gender values this module can return, matching the ``gender_t`` enum. Note
#: what is missing: ``classify_gender`` never returns ``unisex``. A title
#: saying nothing is ``None``, and "sold to men and women both" is a finding
#: about two facets, which only :mod:`mkagg.derive` can see.
KNOWN_GENDERS = frozenset({"men", "women", "kids"})

#: What a *facet* may declare, which is one value more. A department can say
#: unisex outright, and three of the six shops do: Sport Vision and Sport
#: Reality publish Унисекс as its own filter on their equipment sections, 803
#: and 404 articles respectively.
#:
#: That is a different claim from the one :func:`resolve_departments` infers.
#: The inference -- listed in both the men's and the women's department --
#: needs two memberships and is all the footwear and apparel plans can
#: produce, because their gender suffixes bundle unisex into both adult
#: departments (``maski+unisex``, ``unisex+zenski``). An explicit facet is
#: the shop stating it in one place, which is stronger, and it is the only
#: way to gender a section that has no men's or women's URL at all.
#:
#: Separate from ``KNOWN_GENDERS`` rather than folded into it, so the
#: narrower promise about titles keeps being tested.
FACET_GENDERS = KNOWN_GENDERS | {"unisex"}

_PUNCT = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    """Transliterate and flatten punctuation, so keywords match either script."""
    return " " + _PUNCT.sub(" ", translit_mk(text or "")).strip() + " "


def _first_match(rules, haystacks) -> str | None:
    """The first rule any haystack satisfies, rules tried in order.

    The loop nesting is the whole point, and it used to be the other way
    round: every rule was tried against the title before the URL was looked
    at even once. That made a weak word in a marketing name outrank the
    section the shop itself shelved the article in.

    What it cost, measured over 29 611 live offers: ``tf`` is in the cleats
    list because it means *turf*, and Nike abbreviates Therma-FIT the same
    way, so ``Nike W NK TF SYN CLSSC JKT`` was a football boot -- while its
    own URL said ``/mk/jakna/``, the shop's jacket section. ``terrex`` did
    the same to the Terrex clothing line. 42 garments sat in footwear
    categories, and no re-crawl could repair them: the title said the same
    thing every time.

    Trying each rule against every haystack puts the URL on equal footing
    and lets rule order resolve the rest, which is what the facet-first
    precedence in :mod:`mkagg.derive` already assumes. 212 offers move, 196
    of them to a better answer -- including 99 ``Fleece Jogger``s that were
    hoodies because of the word "fleece" and are shelved under
    ``/mk/dolen-del-trenerki/``.

    The remainder is a real trade, not a free win: where a title names one
    garment and the shop's section names another, the shop now wins. A
    "WOVEN UTILITY JACKET" filed under ``/mk/dukser/`` becomes a hoodie, 14
    offers' worth. That is the shop's own shelving, which is the source this
    taxonomy trusts most elsewhere, so it is allowed to win here too.
    """
    for slug, keywords in rules:
        for haystack in haystacks:
            for keyword in keywords:
                # Keep the padding: matching whole words, not substrings.
                # Stripping it made "ball" match inside "HANDBALL SPEZIAL" and
                # classify a shoe as equipment.
                needle = _normalise(keyword)
                if needle.strip() and needle in haystack:
                    return slug
    return None


#: Kinds the catalogue deliberately does not carry, whatever shelf they are
#: found on.
#:
#: Four of them, each excluded for a reason rather than a taste:
#:
#: * **Pet accessories** and **Funko POP! figures** sell only at Sizeer and
#:   Sport-M, which are one operator on one host, so neither can ever carry a
#:   second independent price. A comparison site with one seller has nothing
#:   to compare, and neither is a sporting good.
#: * **Bicycles** are a different market, not an accessory.
#: * **Watches** are the arguable one -- a sport watch is genuinely
#:   comparable -- but there is no leaf for them and inventing one for a
#:   single shop's shelf is how micro-buckets start.
#:
#: Enforced here rather than only by leaving the subgroup out of a facet
#: plan, because a facet plan is not the only way in. Sport-M's Спецификации
#: parser reads `Подгрупа` straight off the product page, and "Додатоци за
#: миленици" matches the `accessories` umbrella -- so a dog collar reached by
#: any other shelf would have been filed as equipment of unspecified kind.
#: Excluded means uncategorised, which is visible, rather than filed
#: somewhere plausible, which is not.
EXCLUDED_PHRASES = ("dodatoci za milenici", "milenici", "funko",
                    "pet ogrlica", "ogrlica za milenici",
                    "velosiped", "velosipedi", "chasovnik", "chasovnici",
                    "casovnik", "casovnici")


def is_excluded(text: str | None) -> bool:
    """Whether this names something the catalogue does not carry."""
    if not text:
        return False
    haystack = _normalise(text)
    return any(_normalise(p) in haystack for p in EXCLUDED_PHRASES)


def classify(title: str | None, *, url: str | None = None) -> str | None:
    """Return a category slug, or ``None`` when the title does not say.

    Real titles this is derived from::

        "GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport"  -> socks
        "JQ2626 Патики GALAXY 7 M - Megasport"                 -> sneakers
        "857797631I-990 ICEPEAK IRWINTON SKI HELANKI"          -> leggings
        "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ"          -> None
        "10421 КОПАЦКИ АДИДАС ББ1032 - Megasport"              -> cleats

    The Terrex is the honest case: nothing in that title names a category, so
    nothing is claimed. The URL is consulted as a second source, because
    dsport's path carries the category even when its title does not
    (``/muskarci/obuca/cizme/...``).
    """
    if is_excluded(title) or is_excluded(url):
        return None
    haystacks = [_normalise(title)]
    if url:
        haystacks.append(_normalise(url))
    return _first_match(_RULES, haystacks)


def classify_gender(title: str | None, *, url: str | None = None) -> str | None:
    """Return ``men``, ``women``, ``kids``, or ``None`` when nothing says.

    ::

        "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ"  -> men
        "Patiki za deca Nike Revolution"               -> kids
        "adidas Supernova Rise"                        -> None

    Never ``unisex``. That value means an article is listed in both an adult
    men's and an adult women's department -- evidence from two facets, not
    something a single title can show. Silence is ``None``.
    """
    haystacks = [_normalise(title)]
    if url:
        haystacks.append(_normalise(url))
    return _first_match(_GENDER_RULES, haystacks)


def is_footwear(slug: str | None) -> bool:
    return slug in FOOTWEAR_SLUGS


def resolve_departments(values) -> str | None:
    """Collapse the departments an article was found in to one gender.

    ::

        {"men"}                  -> "men"
        {"men", "women"}         -> "unisex"
        {"men", "unisex"}        -> "unisex"
        {"kids"}                 -> "kids"
        {"kids", "men"}          -> None
        {}                       -> None

    One rule, used in two places, because they are the same question asked
    at two scales: which departments of *one shop* list this URL, and which
    genders do *all the shops* between them report. Collapsing a set of
    departments is also the only way unisex can ever be found -- the Sport
    Vision shops publish it as membership of both "maski+unisex" and
    "unisex+zenski" and nowhere else.

    Kids mixed with an adult department stays unresolved on purpose. It is
    either a shop mis-shelving the article or two different articles merged
    into one product, and both are worth seeing rather than averaging.
    """
    values = {v for v in values if v}
    if not values:
        return None
    if "kids" in values:
        return "kids" if values == {"kids"} else None
    if len(values) == 1:
        return next(iter(values))
    return "unisex"
