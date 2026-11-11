"""Deciding what kind of thing a product is, from its title.

This exists because of a bug the serving API made visible: a pack of socks was
filed under ``sneakers``. Not through a matching failure -- the article code
was read correctly and the offer joined the right product -- but because
``create_product`` hard-coded the footwear category for everything it created.
Megasport's discovery walks a sitemap containing its *entire* catalogue, so
socks, ski leggings and helmets all arrived labelled as sneakers.

Two design choices worth keeping:

**Unknown means no category, never a guessed one.** ``product.category_id`` is
nullable and that is the correct value for a title we cannot read. Defaulting
to a plausible category is precisely how the socks got in; a null shows up in
admin as something to look at, while a wrong value looks finished.

**Keywords live here, in code, not in the database.** They need the same
Cyrillic/Latin transliteration as everything else, they change with the
parsers rather than with the data, and they are worth unit-testing against
real titles.
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
    ("leggings", ("helanki", "helanka", "legging", "tajice")),
    # Singular AND plural: megasport writes "Долна тренерка" (singular) while
    # other titles use "Тренерки", and a plural-only list missed the first,
    # leaving "Dolna Trenerka" inside a product name.
    ("apparel", ("trenerki", "trenerka", "majica", "maica", "duks", "hoodie",
                 "jakna", "jakni", "pantaloni", "shorc", "shorts", "dukser",
                 "t shirt", "tshirt", "polo", "fanela", "vesta",
                 "ski helanki", "komplet")),
    ("accessories", ("kapa", "shapka", "ranec", "backpack", "torba", "chanta",
                     "rakavici", "gloves", "shal", "kaciga", "helmet",
                     "naocari", "sticnici", "shin guard")),
    ("equipment", ("topka", " ball", "raketa", "racket", "shipka",
                   "dumbbell", "tegovi", "lopta")),

    # --- footwear -----------------------------------------------------------
    ("slides", ("papuci", "papuchi", "slide", "flip flop", "nanule")),
    ("boots", ("cizmi", "chizmi", "cizme", "boots", "gojzerica")),
    ("sneakers", ("patiki", "patike", "patika", "sneaker", "tenisice")),
    # Generic footwear nouns: a real shoe, but not specific enough to tier.
    ("footwear", ("obuvki", "obuvka", "konduri", "kondur", "shoes", "shoe")),

    # Last, because this is the only rule that reads the *model name* rather
    # than the shop's own category word. "Adidas RESPONSE RUNNER 2" is listed
    # by megasport under Патики, and the shop saying so outranks a word that
    # happens to appear in the model.
    ("running", ("za trchanje", "running shoe", "runner")),
]

#: Category slugs this module can return. Kept in step with V4 + V10 so a
#: typo here fails a test rather than silently nulling a category.
KNOWN_SLUGS = frozenset({
    "footwear", "sneakers", "running", "boots", "slides",
    "apparel", "leggings", "accessories", "socks", "equipment",
})

#: Which of those are footwear, i.e. the MVP's storefront.
FOOTWEAR_SLUGS = frozenset({"footwear", "sneakers", "running", "boots", "slides"})

_PUNCT = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    """Transliterate and flatten punctuation, so keywords match either script."""
    return " " + _PUNCT.sub(" ", translit_mk(text or "")).strip() + " "


def classify(title: str | None, *, url: str | None = None) -> str | None:
    """Return a category slug, or ``None`` when the title does not say.

    Real titles this is derived from::

        "GH0331 Чорапи ACT CORE MID CREW SOCK 3P - Megasport"  -> socks
        "JQ2626 Патики GALAXY 7 M - Megasport"                 -> sneakers
        "857797631I-990 ICEPEAK IRWINTON SKI HELANKI"          -> leggings
        "ADIDAS TERREX SKYCHASER AX5 MID GTX ЗА МАЖИ"          -> None
        "Nike Патики Vomero 18"                                -> sneakers

    The Terrex is the honest case: nothing in that title names a category, so
    nothing is claimed. The URL is consulted as a second source, because
    dsport's path carries the category even when its title does not
    (``/muskarci/obuca/cizme/...``).
    """
    haystacks = [_normalise(title)]
    if url:
        haystacks.append(_normalise(url))

    for haystack in haystacks:
        for slug, keywords in _RULES:
            for keyword in keywords:
                # Keep the padding: matching whole words, not substrings.
                # Stripping it made "ball" match inside "HANDBALL SPEZIAL" and
                # classify a shoe as equipment.
                needle = _normalise(keyword)
                if needle.strip() and needle in haystack:
                    return slug
    return None


def is_footwear(slug: str | None) -> bool:
    return slug in FOOTWEAR_SLUGS
