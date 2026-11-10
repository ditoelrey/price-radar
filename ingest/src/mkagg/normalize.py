"""Normalisation primitives.

Every value in this module exists because recon found a real inconsistency on
the 7 target stores. The docstrings name the store that forced each rule, so
nobody later "simplifies" them away.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# -----------------------------------------------------------------------------
# SKU / manufacturer part numbers
# -----------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# Nike-style code: 6 alphanumerics, dash, 3-digit colourway (DH2987-001).
_NIKE_STYLE = re.compile(r"^([A-Z]{2}\d{4})(\d{3})$")
# Puma-style code: 6 digits, dash, 2-digit colourway (392290-02).
_PUMA_STYLE = re.compile(r"^(\d{6})(\d{2})$")


def normalize_sku(raw: str | None) -> str | None:
    """Uppercase and strip every non-alphanumeric character.

    The same article arrives spelled three ways across stores::

        "dh2987-001"  ->  "DH2987001"
        "DH2987 001"  ->  "DH2987001"
        "392290-02"   ->  "39229002"

    Returns None for empty input or for input with no alphanumerics at all.
    """
    if not raw:
        return None
    out = _NON_ALNUM.sub("", raw.strip().upper())
    return out or None


def sku_base(raw: str | None) -> str | None:
    """Strip the colourway suffix, yielding the model-level code.

    ``DH2987-001`` and ``DH2987-100`` are the same silhouette in two colours.
    Exact matching uses :func:`normalize_sku`; this is for "same model, other
    colour" grouping and for the fuzzy fallback's blocking key.

    Returns None when the code does not look like a known style pattern, so a
    caller can tell "no base" apart from "base == full".
    """
    norm = normalize_sku(raw)
    if not norm:
        return None
    for pattern in (_NIKE_STYLE, _PUMA_STYLE):
        m = pattern.match(norm)
        if m:
            return m.group(1)
    return None


# -----------------------------------------------------------------------------
# Sizes
# -----------------------------------------------------------------------------

# Unicode vulgar fractions. sport-m.com.mk and sizeer.com.mk return EU sizes
# as "41<U+2153>" / "42<U+2154>" from /ProductCatalog/GetVelicini/, so a plain
# float() on the label raises and a plain regex for digits silently drops the
# fraction -- which would collapse 42 1/3 and 42 2/3 onto the same size.
_VULGAR_FRACTIONS = {
    "¼": Decimal("0.25"),    # 1/4
    "½": Decimal("0.5"),     # 1/2
    "¾": Decimal("0.75"),    # 3/4
    "⅐": Decimal("1") / 7,
    "⅑": Decimal("1") / 9,
    "⅒": Decimal("0.1"),
    "⅓": Decimal("1") / 3,   # 1/3
    "⅔": Decimal("2") / 3,   # 2/3
    "⅕": Decimal("0.2"),
    "⅖": Decimal("0.4"),
    "⅗": Decimal("0.6"),
    "⅘": Decimal("0.8"),
    "⅙": Decimal("1") / 6,
    "⅚": Decimal("5") / 6,
    "⅛": Decimal("0.125"),
    "⅜": Decimal("0.375"),
    "⅝": Decimal("0.625"),
    "⅞": Decimal("0.875"),
}

# Labels that mean "this article has no size".
_NO_SIZE = {
    "bez velicina", "bez veličina", "bez golemina",
    "one size", "onesize", "uni", "universal", "u", "no size", "-",
}

_ASCII_FRACTION = re.compile(r"^(\d{1,2})\s+(\d)\s*/\s*(\d)$")
# dsport's Magento swatch labels, e.g. "41-1/3", "42-2/3": a dash where the
# other stores put a space. Must be tried before _DASH_DECIMAL.
_DASH_FRACTION = re.compile(r"^(\d{1,2})-(\d)\s*/\s*(\d)$")
_DASH_DECIMAL = re.compile(r"^(\d{1,2})-(\d)$")
_RANGE = re.compile(r"^(\d{1,2})\s*[-/]\s*(\d{2})$")
# NFKC output for a vulgar fraction: "41<U+2153>" becomes "411<U+2044>3".
_SLASH_FRACTION = re.compile(r"^(\d{1,2})(\d)⁄(\d)$")


def normalize_size(raw: str | None) -> Decimal | None:
    """Return a numeric EU size, or None when the label carries no size.

    Formats proven to occur on the target stores:

    ==================  ==========  ==================================
    label               result      store
    ==================  ==========  ==================================
    ``"35,5"``          35.5        sportvision.mk (comma decimal)
    ``"35.5"``          35.5        sportvision.mk (dot, same page!)
    ``"44 2/3"``        44.667      buzzsneakers.mk (ASCII fraction)
    ``"41⅓"``      41.333      sport-m / sizeer (Unicode fraction)
    ``"37-5"``          37.5        megasport (dash as decimal point)
    ``"BEZ VELICINA"``  None        dsport.mk (one-size article)
    ``"41-42"``         41.0        range -> take the lower bound
    ==================  ==========  ==================================
    """
    if raw is None:
        return None
    # NFC, never NFKC: NFKC *decomposes* the vulgar fractions this function
    # exists to read, turning "41⅓" into "411⁄3" and destroying the
    # value before we can see it.
    s = unicodedata.normalize("NFC", str(raw)).strip()
    if not s or s.lower() in _NO_SIZE:
        return None

    # Drop a leading size-system prefix: "EU 42", "UK 8.5".
    s = re.sub(r"^(?:eu|uk|us|eur)\s*", "", s, flags=re.I).strip()

    # Already-decomposed form, in case an upstream layer ran NFKC on it:
    # "411<U+2044>3" is 41 + 1/3.
    m = _SLASH_FRACTION.match(s)
    if m:
        whole, num, den = m.groups()
        if den == "0":
            return None
        return (Decimal(whole) + Decimal(num) / Decimal(den)).quantize(Decimal("0.001"))

    # Unicode vulgar fraction glued to an integer: "41<U+2153>".
    for glyph, value in _VULGAR_FRACTIONS.items():
        if glyph in s:
            whole = s.replace(glyph, "").strip() or "0"
            try:
                return (Decimal(whole) + value).quantize(Decimal("0.001"))
            except InvalidOperation:
                return None

    # ASCII fraction, space- or dash-separated: "44 2/3" (buzz), "41-1/3"
    # (dsport Magento swatch labels).
    m = _ASCII_FRACTION.match(s) or _DASH_FRACTION.match(s)
    if m:
        whole, num, den = m.groups()
        if den == "0":
            return None
        return (Decimal(whole) + Decimal(num) / Decimal(den)).quantize(Decimal("0.001"))

    # Range such as "41-42": take the lower bound, which is what the shop
    # actually guarantees. Checked before the dash-decimal rule.
    m = _RANGE.match(s)
    if m:
        return Decimal(m.group(1)).quantize(Decimal("0.001"))

    # Dash used as a decimal point: megasport variation values ("37-5").
    m = _DASH_DECIMAL.match(s)
    if m:
        return Decimal(f"{m.group(1)}.{m.group(2)}").quantize(Decimal("0.001"))

    # Plain number with either separator.
    s = s.replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.001"))
    except InvalidOperation:
        return None


# -----------------------------------------------------------------------------
# Money
# -----------------------------------------------------------------------------

#: The numeric run inside a displayed price. Extracting it is safer than
#: stripping unwanted characters: the MKD suffix "ден." ends in a dot, which a
#: strip-based clean leaves dangling on the number ("6.799,00.").
_PRICE_RUN = re.compile(r"\d[\d., \s]*\d|\d")


def parse_price_minor(raw: str | float | int | None, minor_unit: int = 0) -> int | None:
    """Parse a displayed price into integer minor units.

    Integers only -- float money breaks the "lowest price" sort as soon as
    4499.9999 appears. ``minor_unit`` comes from ``currency.minor_unit``
    (0 for MKD as these shops configure it, 2 for EUR).

    Separator handling, which differs per source on the same product:

    ===================  =============  ======================================
    input                result (MKD)   source
    ===================  =============  ======================================
    ``"6.799,00 ден."``  6799           sport-m HTML (EU: dot thousands)
    ``"2.266,00"``       2266           sport-m HTML
    ``"2863.00"``        2863           sportvision JSON-LD (US: dot decimal)
    ``"3199"``           3199           megasport Store API (bare integer)
    ``8599.0``           8599           already numeric
    ===================  =============  ======================================
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        dec = Decimal(str(raw))
    else:
        run = _PRICE_RUN.search(str(raw))
        if not run:
            return None
        # Drop spaces used as thousands separators ("1 234,00").
        s = re.sub(r"[ \s]", "", run.group(0))
        if not s:
            return None

        has_dot, has_comma = "." in s, "," in s
        if has_dot and has_comma:
            # Whichever separator comes last is the decimal point.
            dec_sep = "," if s.rindex(",") > s.rindex(".") else "."
            thou_sep = "." if dec_sep == "," else ","
            s = s.replace(thou_sep, "").replace(dec_sep, ".")
        elif has_comma:
            # 2 digits after a lone comma is a decimal, otherwise thousands.
            s = s.replace(",", "." if len(s.rsplit(",", 1)[1]) == 2 else "")
        elif has_dot:
            # Exactly 3 digits after a lone dot is a thousands separator
            # ("6.799"); 1-2 digits is a decimal point ("2863.00").
            if len(s.rsplit(".", 1)[1]) == 3:
                s = s.replace(".", "")
        try:
            dec = Decimal(s)
        except InvalidOperation:
            return None

    scaled = dec * (10 ** minor_unit)
    return int(scaled.to_integral_value(rounding="ROUND_HALF_UP"))


# -----------------------------------------------------------------------------
# Text, for the fuzzy fallback matcher
# -----------------------------------------------------------------------------

# Category nouns and gender markers the stores prepend to every title. Left in
# place they dominate the similarity score and make unrelated shoes look alike.
_NOISE_WORDS = [
    # Macedonian (Cyrillic)
    "патики", "патика", "обувки", "обувка", "кондури", "папучи", "чизми",
    "копачки", "машки", "женски", "детски", "унисекс", "за", "мажи", "жени",
    # Macedonian / Serbian (Latin)
    "patiki", "patika", "obuvki", "konduri", "papuci", "cizme", "kopacki",
    "muski", "zenski", "deciji", "unisex", "za", "mazhi", "zheni", "muske",
    # English
    "shoes", "sneakers", "trainers", "mens", "men", "womens", "women",
    "kids", "junior", "unisex", "low", "lowtop", "low-top", "shoe",
]
_NOISE_RE = re.compile(r"\b(?:%s)\b" % "|".join(sorted(_NOISE_WORDS, key=len, reverse=True)), re.I)

_CYR_TO_LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "ѕ": "dz", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj",
    "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "ќ": "kj", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
    "џ": "dj", "ш": "sh",
})


def translit_mk(text: str) -> str:
    """Macedonian Cyrillic -> Latin, so "Најк" and "Nike" can be compared.

    Also needed by the search indexer: MK users type brand names in both
    scripts, often in the same session.
    """
    return (text or "").lower().translate(_CYR_TO_LAT)


def clean_model_name(title: str, brand: str | None = None) -> str:
    """Reduce a shop title to the comparable model name.

    ``"Патики Puma Caven 2.0 за мажи"`` -> ``"caven 2.0"``

    Used only for the fuzzy fallback. SKU matching needs none of this, which
    is why recon finding "every MK store exposes the MPN" matters so much.
    """
    s = translit_mk(title or "")
    if brand:
        for token in {brand, translit_mk(brand)}:
            if token:
                s = re.sub(re.escape(token.lower()), " ", s, flags=re.I)
    s = _NOISE_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9.\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slugify(text: str) -> str:
    """URL slug from a possibly-Cyrillic product name."""
    s = translit_mk(text or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    return s.strip("-") or "product"
