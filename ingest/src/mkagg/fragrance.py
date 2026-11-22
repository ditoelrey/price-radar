"""Reading a fragrance: its strength, its name, and who it is sold to.

Every other vertical in this catalogue is matched on a manufacturer code.
Fragrances have none that both shops publish, so identity has to be read out
of words -- and the words disagree between the two shops that sell them::

    shop.schatze.mk    "Pour Homme - edt"                brand in a separate field
    e-elixir.mk        "Versace Pour Homme Eau de toilette"   brand in the title

One fragrance. The job of this module is to turn both of those into the same
triple -- ``("versace", "pour homme", "EDT")`` -- so an exact index can do
what a similarity score must not be trusted to do here.

**Why exactness matters more than usual.** The shops stock whole families of
near-identical names. "Born in Roma", "Born in Roma Intense", "Born in Roma
Extradose" and "Born in Roma Ruby" sit side by side at different prices, and
a fuzzy matcher scores them as the same product. Merging two of them would
quote a shopper a price for a bottle they cannot buy, which is the one
failure this project exists to prevent. So every rule below prefers to
return None over a guess.

**The three traps, all measured on live titles.**

``Elixir`` is almost always part of the name, not a strength. "Le Male ELIXIR
- Eau de Parfum" is an EDP whose fragrance is called Le Male Elixir, and
"1 MILLION ELIXIR PARFEM INTENSE" is the same shape. Folding it into the
concentration would merge it with plain Le Male EDP.

``Intense`` and ``Intensement`` are flanker modifiers. "La vie est belle"
and "La Vie Est Belle Intensement" are different fragrances.

``Pour Homme`` and ``Pour Femme`` are part of the name *and* the best gender
signal there is. They stay in the line name -- Versace Pour Homme is the
fragrance's actual name -- while also being read for gender.
"""
from __future__ import annotations

import html
import re
import unicodedata

from .normalize import translit_mk

# -----------------------------------------------------------------------------
# Concentration
# -----------------------------------------------------------------------------

#: Spelling -> canonical strength. Order matters at match time, not here:
#: :func:`read_concentration` tries the longest spelling first, so
#: "eau de parfum" is never read as the "parfum" inside it.
#:
#: Measured across both shops: e-elixir writes the full words on 853 of 987
#: products, Schatze splits roughly evenly between "Eau de Parfum" (66 of a
#: 214-product sample) and "EDP" (49). Both spellings are live, in both
#: directions, which is exactly the normalisation the match key needs.
CONCENTRATIONS: dict[str, str] = {
    "eau de parfum": "EDP",
    "eau de parfume": "EDP",
    "eau de perfum": "EDP",
    "edp": "EDP",
    "eau de toilette": "EDT",
    "eau de toilete": "EDT",
    "edt": "EDT",
    "eau de cologne": "EDC",
    "edc": "EDC",
    "extrait de parfum": "EXTRAIT",
    "extrait": "EXTRAIT",
    "parfum": "PARFUM",
    "parfem": "PARFUM",
    "cologne": "COLOGNE",
    "body mist": "MIST",
    "mist": "MIST",
    # Macedonian, which e-elixir writes out in full on 98 of its 987 titles.
    # Counted rather than guessed: "toaletna voda" 18, "parfimiran sprej" 48,
    # "sprej za telo" 4, "kolonska voda" 2, "mirizliva voda" 1. Spellings
    # that never appear are left out -- an unused rule is an untested one.
    "toaletna voda": "EDT",
    "parfimirana voda": "EDP",
    "kolonska voda": "EDC",
    "parfimiran sprej za telo": "MIST",
    "parfimiran sprej": "MIST",
    "sprej za telo": "MIST",
    "mirizliva voda": "MIST",
    "mirisliva voda": "MIST",
}

#: Words that look like a strength and are not. See the module docstring --
#: each one of these is a real product whose name contains it, and folding
#: any of them into `concentration` merges articles the shops sell apart.
NOT_CONCENTRATION = frozenset({"elixir", "intense", "intensement", "extreme",
                               "absolu", "absolute", "legend", "essence"})

#: Longest first, so "eau de parfum" wins over "parfum" and "extrait de
#: parfum" over "extrait".
_CONCENTRATION_ORDER = tuple(sorted(CONCENTRATIONS, key=len, reverse=True))


def _fold(text: str | None) -> str:
    """Lower-case, transliterate, strip accents, squeeze punctuation.

    Accents have to go: e-elixir writes "Lancôme" and Schatze writes
    "Lancome", and they are the same brand. Punctuation collapses to single
    spaces so "Woman -Eau de Parfum" (no space, live on Schatze) reads the
    same as "Woman - Eau de Parfum".
    """
    if not text:
        return ""
    # Entities first, and before transliteration. WooCommerce serves 154 of
    # e-elixir's 987 names with a curly apostrophe escaped -- "La Nuit de
    # L&#8217;Homme", "Gucci Bloom Ambrosia d&#8217;Oro". Left alone the
    # digits survive the punctuation squeeze as a word, so the title folds
    # to "la nuit de l 8217 homme" and cannot match Schatze's spelling of
    # the same fragrance. That is a silent 16 percent match failure.
    flat = translit_mk(html.unescape(text)).lower()
    flat = unicodedata.normalize("NFKD", flat)
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    # Curly apostrophes arrive HTML-escaped from WooCommerce ("L&#8217;Elixir")
    # and raw from the page; both become nothing, so "l'elixir" and "lelixir"
    # cannot be two different fragrances.
    flat = flat.replace("'", "").replace("’", "")
    flat = re.sub(r"[^a-z0-9]+", " ", flat)
    return " ".join(flat.split())


def read_concentration(title: str | None) -> tuple[str | None, str | None]:
    """The strength a title states, and the exact phrase that said so.

    Returns ``(canonical, phrase)`` -- the phrase folded, so a caller can
    remove it from the line name without re-deriving where it was::

        read_concentration("Valentino Donna Eau de parfum")
            -> ("EDP", "eau de parfum")
        read_concentration("Pour Homme - edt")
            -> ("EDT", "edt")
        read_concentration("Le Male ELIXIR - Eau de Parfum")
            -> ("EDP", "eau de parfum")        # Elixir stays in the name
        read_concentration("Adidas Adicolor")
            -> (None, None)

    A title naming no strength yields None rather than a default. Both shops
    leave it out sometimes -- 134 of e-elixir's 987 -- and "probably EDP" is
    exactly the guess that merges an EDT into it.
    """
    flat = _fold(title)
    if not flat:
        return None, None
    for phrase in _CONCENTRATION_ORDER:
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", flat):
            return CONCENTRATIONS[phrase], phrase
    return None, None


#: A volume written into the title rather than carried as a variant, which
#: both shops do on gift sets and on some single bottles.
_VOLUME_IN_TITLE = re.compile(r"(?<![a-z0-9])\d{1,4}\s*(?:ml|g)(?![a-z0-9])")


def line_name(title: str | None, brand: str | None = None) -> str | None:
    """The fragrance's own name: no brand, no strength, no volume.

    This is the half of the identity that no shop states cleanly::

        line_name("Versace Pour Homme Eau de toilette", "Versace")
            -> "pour homme"
        line_name("Pour Homme - edt", "Versace")
            -> "pour homme"

    Both reduce to the same string, which is the whole point -- Schatze omits
    the brand from the title and keeps it in a Manufacturer field, so
    comparing raw titles would never join these two.

    What deliberately stays: ``Pour Homme``, ``Intense``, ``Elixir``,
    ``Ruby``, ``Extradose``. Every one of them distinguishes one real
    fragrance from another sold beside it.
    """
    flat = _fold(title)
    if not flat:
        return None

    brand_flat = _fold(brand)
    if brand_flat and flat.startswith(brand_flat + " "):
        flat = flat[len(brand_flat) + 1:]
    elif brand_flat and flat == brand_flat:
        # A title that is only the brand names no fragrance.
        return None

    _, phrase = read_concentration(flat)
    if phrase:
        flat = re.sub(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])",
                      " ", flat)

    flat = _VOLUME_IN_TITLE.sub(" ", flat)
    # "for women" / "for men" are shelf words the shops append; they carry no
    # fragrance of their own, unlike "pour femme" which is part of a name.
    flat = re.sub(r"(?<![a-z0-9])for (?:women|men|her|him)(?![a-z0-9])",
                  " ", flat)
    flat = " ".join(flat.split())
    return flat or None


# -----------------------------------------------------------------------------
# Gender
# -----------------------------------------------------------------------------

#: What a shelf says. Both shops publish three, in their own languages, and
#: these are the strong source -- a shelf states a gender on every product
#: while a title states one on roughly 12 percent of Schatze's.
SHELF_GENDERS: tuple[tuple[str, str], ...] = (
    ("women", ("zhenski", "zenski", "women", "woman", "female", "her")),
    ("men", ("mashki", "maski", "men", "man", "male", "him")),
    ("unisex", ("uniseks", "unisex")),
)

#: What a title says outright. Narrower than the shelf words on purpose:
#: a bare "men" inside a title is as likely to be part of a name, so only
#: these explicit forms count.
_TITLE_MEN = re.compile(
    r"(?<![a-z0-9])(pour homme|for men|for him|for man|uomo|homme)"
    r"(?![a-z0-9])")
_TITLE_WOMEN = re.compile(
    r"(?<![a-z0-9])(pour femme|for women|for her|for woman|donna|femme)"
    r"(?![a-z0-9])")


def read_gender(shelf: str | None = None,
                title: str | None = None) -> str | None:
    """Who a fragrance is sold to, shelf first and title as the override.

    This inverts the usual precedence, and the inversion is measured. Over
    672 distinct products on Schatze's two gendered shelves, exactly two
    carry the opposite marker in their titles -- and both are the shop's
    mistake, not ours: ``Pour Homme - edt`` by Versace sits on
    ``Fragrances / Women``. e-elixir shelves the same fragrance under
    Машки.

    So the shelf is right about 99.7 percent of the time and is the only
    signal present on every product, while an explicit ``Pour Homme`` is
    right every time it appears. Taking the title when it speaks costs
    nothing on the other 99.7 percent, because there the two agree.
    """
    flat_title = _fold(title)
    if flat_title:
        men, women = _TITLE_MEN.search(flat_title), _TITLE_WOMEN.search(flat_title)
        # Both, or neither, is no answer: "Pour Homme Pour Femme" is not a
        # product, but a title mentioning both is not evidence either way.
        if men and not women:
            return "men"
        if women and not men:
            return "women"

    flat_shelf = _fold(shelf)
    if flat_shelf:
        for gender, words in SHELF_GENDERS:
            if any(re.search(rf"(?<![a-z0-9]){w}(?![a-z0-9])", flat_shelf)
                   for w in words):
                return gender
    return None


# -----------------------------------------------------------------------------
# What is not a bottle of perfume
# -----------------------------------------------------------------------------

#: Shelf words naming a gift set. Both shops keep sets inside their fragrance
#: trees -- e-elixir has 86 Женски сетови and 75 Машки, Schatze a
#: /gift-sets shelf of 47 -- so finding one is not a reason to think the
#: crawl went somewhere it should not have.
_SET_SHELVES = ("setovi", "set", "gift set", "gift sets", "komplet")

#: A scented candle, which e-elixir shelves inside Мириси -- "миризлива
#: свеќа", four of them. It is sold by weight and has no bottle at all.
_CANDLE = re.compile(r"(?<![a-z0-9])(svekja|svekji|candle)(?![a-z0-9])")

#: Home fragrance: a diffuser, a room spray, a refill for one. Acqua
#: dell'Elba's sit in Мириси beside the perfumes -- "мирис за просторија",
#: 500ml refills among them. Nobody wears it, and a 500ml refill on the same
#: volume rail as a 50ml bottle would make the rail meaningless.
_ROOM = re.compile(r"(?<![a-z0-9])(miris za prostorija|room spray|"
                   r"diffuser|difuzer|keramichka plochka)(?![a-z0-9])")

#: A perfumed deodorant. Same brand, same fragrance family, different
#: article -- "Moschino I Love Love парфимиран деодорант за жени 50ml" is
#: not the 50ml bottle of I Love Love, and putting the two on one volume
#: rail would offer a shopper the wrong thing at the better price.
_DEODORANT = re.compile(r"(?<![a-z0-9])(deodorant|dezodorans|deo stik|"
                        r"deo stick|roll on)(?![a-z0-9])")

#: A set written into the title. The reliable tell, and the one that catches
#: sets the shop filed on an ordinary shelf: "212 Vip Black 100ml EDP +
#: Shower Gel 100ml", "Zen Eau de parfum 50ml + travel size 10ml".
_SET_IN_TITLE = re.compile(r"\+")


def is_single_bottle(title: str | None,
                     shelves: tuple[str, ...] | list[str] = (),
                     volume_labels: tuple[str, ...] | list[str] = ()) -> bool:
    """True when this is one bottle of one fragrance, and nothing else.

    Everything else is excluded from the vertical for now -- gift sets,
    scented candles, body mists. They all live inside both shops' fragrance
    shelves and none of them is a volume of the bottle beside it::

        is_single_bottle("Valentino Donna Eau de parfum", ["Женски мириси"])
            -> True
        is_single_bottle("Zen Eau de parfum 50ml + travel size 10ml")
            -> False, the plus sign
        is_single_bottle("Acqua Dell'Elba мирислива свеќа", volume_labels=["180g"])
            -> False, grams are not millilitres

    A set is not a smaller bottle, and letting one in would hand the volume
    rail a "50ml" that buys a different thing from the 50ml beside it.
    """
    flat = _fold(title)
    if not flat:
        return False
    if _SET_IN_TITLE.search(html.unescape(title or "")):
        return False
    if _CANDLE.search(flat) or _ROOM.search(flat) or _DEODORANT.search(flat):
        return False

    for shelf in shelves:
        flat_shelf = _fold(shelf)
        if any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])",
                         flat_shelf) for w in _SET_SHELVES):
            return False

    # A body mist is a different article at a different strength, and both
    # shops shelve them apart; e-elixir has 73.
    concentration, _ = read_concentration(title)
    if concentration == "MIST":
        return False

    # Grams, not millilitres: a candle, a soap, a solid. If every volume the
    # shop offers is a weight, this is not a bottle.
    if volume_labels:
        has_ml = any(re.search(r"\d\s*(?:ml|мл)(?![a-z0-9])", str(v), re.I)
                     for v in volume_labels)
        has_grams = any(re.search(r"\d\s*g(?![a-z0-9])", str(v), re.I)
                        for v in volume_labels)
        if has_grams and not has_ml:
            return False

    return True


def most_specific_shelf(names) -> str | None:
    """The one shelf worth recording out of the several a shop files under.

    WooCommerce returns a product's categories in no useful order --
    measured on e-elixir, the first is as likely to be the root Мириси as
    the leaf Машки Eau de toilette::

        ['Мириси', 'Женски Eau de parfum', 'Женски мириси', ...]
        ['Машки Eau de toilette', 'Машки мириси', 'Мириси', ...]

    Taking position 0 would record the root for one product and the leaf
    for the next, and `merchant_category_path` is meant to be the shop's
    most specific word for this article. So the choice is made on what the
    name says rather than where it sits: a shelf naming a strength says the
    most, one naming only a gender says less, the root says least.
    """
    names = [n for n in (names or []) if n]
    if not names:
        return None
    with_strength = [n for n in names if read_concentration(n)[0]]
    if with_strength:
        return with_strength[0]
    with_gender = [n for n in names if read_gender(n)]
    if with_gender:
        return with_gender[0]
    return names[0]


__all__ = ["CONCENTRATIONS", "NOT_CONCENTRATION", "SHELF_GENDERS",
           "read_concentration", "line_name", "read_gender",
           "is_single_bottle", "most_specific_shelf"]
