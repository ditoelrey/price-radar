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
    ("socks", ("chorapi", "corapi", "sok 3p", "crew sock", "ankle sock",
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
    ("accessories", ("kapa", "shapka", "ranec", "backpack", "torba", "chanta",
                     "rakavici", "gloves", "shal", "kaciga", "helmet",
                     "naocari", "sticnici", "shin guard", "shtitnik",
                     "shtitnici")),
    ("equipment", ("topka", " ball", "raketa", "racket", "shipka",
                   "dumbbell", "tegovi", "lopta")),

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

#: Category slugs this module can return. Kept in step with V4 + V10 + V17 +
#: V18 so a typo here fails a test rather than silently nulling a category.
KNOWN_SLUGS = frozenset({
    "footwear", "sneakers", "cleats", "shoes_boots", "slides_sandals",
    "accessories", "socks", "equipment",
}) | APPAREL_SLUGS

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
