"""Reading an apparel size label.

Footwear had it easy: every shop writes a number, `normalize_size` turns it
into an EU size, and a bound throws out the ones that cannot be. Apparel has
no such luck. Measured across the six shops by fetching real products through
the adapters::

    sportvision   S M L XL 2XL 3XL        7-8г. 9-10г. 11-12г. 14-15г.
    sportreality  S..3XL, and SM MD LG    12-13г. AND 6Y 8Y 10Y AND 4 5 6 7 AND 128
    buzz          S..2XL                  7-8г. .. 14-15г.
    megasport     S M L XL                7
    sport-m       S M L XL XXL            12-18 мес. 1-2 год. 2-3 год.
    sizeer        XL ..                   same as sport-m

Four systems, one shop using four of them at once, and two spellings of the
same letter size inside a single shop. So this module answers one question --
*what is this label written in* -- and leaves the label itself untouched for
the storefront to show.

Two rules it keeps:

**A number alone is not a size.** "38" is a women's dress size on an apparel
product and a shoe size on a footwear one, and nothing in the label can tell
them apart. 148 apparel variants reached the database claiming EU shoe sizes
before V18 because a bound was asked to do a job only context can do. Hence
the `apparel` and `kids` flags: callers pass what the facet told them, and
what nothing tells us stays ``numeric``.

**Never convert here.** Heights and ages are recorded as the shop stated
them. The age a height corresponds to lives in ``kids_size_chart``, learned
from the two shops that publish both, and is applied when a filter is
answered -- not written onto a variant as though the shop had said it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import _NO_SIZE, normalize_size, translit_mk

#: Canonical letter sizes, smallest first. The order is the ladder a
#: storefront sorts and filters by, so it lives with the vocabulary.
ALPHA_LADDER = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL")

#: Every spelling seen on the six shops, mapped to one of the above.
#:
#: "2XL" becomes "XXL" and "XXXL" becomes "3XL", which looks inconsistent
#: until you try the alternatives: doubling all the way up gives "XXXXXL",
#: and numbering all the way down gives "2XL" next to "XL" with no "1XL" to
#: match it. Retail splits at the same place, and so do these shops --
#: sport-m writes XXL where sportvision writes 2XL, and both write 3XL.
_ALPHA = {
    "xxs": "XXS", "2xs": "XXS",
    "xs": "XS", "x-s": "XS", "extra small": "XS",
    "s": "S", "sm": "S", "sml": "S", "small": "S",
    "m": "M", "md": "M", "med": "M", "medium": "M",
    "l": "L", "lg": "L", "lrg": "L", "large": "L",
    "xl": "XL", "x-l": "XL", "1xl": "XL", "extra large": "XL",
    "xxl": "XXL", "2xl": "XXL", "x-xl": "XXL",
    "xxxl": "3XL", "3xl": "3XL",
    "xxxxl": "4XL", "4xl": "4XL",
    "xxxxxl": "5XL", "5xl": "5XL",
}

#: Body heights these shops actually use run 80 to 200 cm. No EU shoe size
#: reaches 80, so a number in this band is never ambiguous -- which is why
#: height needs no context flag and a bare "38" does.
_HEIGHT_MIN, _HEIGHT_MAX = 80, 200

#: A bare number on a kids' apparel product, in years. megasport writes "7"
#: and means seven years old. Bounded at 16 because that is where these
#: shops' children's departments stop.
_KIDS_YEARS_MAX = 16

_MONTH_RANGE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,3})\s*mes\.?$")
_YEAR_RANGE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})\s*(?:god|g|y|yr|yrs|year|years)\.?$")
_YEAR_ONE = re.compile(r"^(\d{1,2})\s*(?:god|g|y|yr|yrs|year|years)\.?$")
_MONTH_ONE = re.compile(r"^(\d{1,3})\s*mes\.?$")
_NUMBER = re.compile(r"^(\d{1,3})(?:[.,](\d))?$")
_NUM_RANGE = re.compile(r"^(\d{2,3})\s*-\s*(\d{2,3})$")


@dataclass(frozen=True)
class SizeReading:
    """What one label turned out to be written in.

    ``system`` is None only when there was no label at all. Everything else,
    including the honest ``numeric``, is a reading.
    """
    system: str | None = None
    alpha: str | None = None
    #: The upper letter when the label names a *span* of two sizes, as
    #: "M/L" does. None for an ordinary single letter, where `alpha` is the
    #: whole answer -- so a reader that ignores this field still gets the
    #: smaller end rather than nothing.
    alpha_max: str | None = None
    height_cm: int | None = None
    age_min_months: int | None = None
    age_max_months: int | None = None

    @property
    def is_empty(self) -> bool:
        return self.system is None


def _flatten(label: str) -> str:
    """Lower-case, transliterate, and squeeze whitespace.

    Transliterating first is what lets one set of patterns read "12-18 мес."
    and "12-18 mes." alike, the same approach `taxonomy` takes to category
    words.
    """
    return " ".join(translit_mk(label or "").lower().split())


def _alpha_span(flat: str) -> tuple[str, str] | None:
    """Read "M/L" as the span M..L, and refuse every lookalike.

    One separator, on purpose. These shops write a slash for two different
    things and a dash for a third::

        M/L   L/XL   XS/S   2XS/XS     a span of two sizes
        L/S   M/S    XL/S   S/S        a size and a *length* -- Short
        L-T   2XL-T  4XL-T             a size and a length -- Tall
        S A-C XS A-C                   a bra band and a cup range

    Only the first group is a span, and what separates it from the second is
    not the punctuation but the ladder: a span climbs it. "L/S" is Large in
    a short leg, and reading it as L..S asks for a range that runs backwards.
    "S/S" is Small-Short and would collapse to a span of one. Both are
    rejected by requiring the right-hand size to rank strictly above the
    left.

    Dashes are left out entirely. "XS-S" climbs the ladder and is still
    XS-Short, sitting in a run of S-S, M-S, L-S and XL-S that no rule about
    order can tell apart from it.
    """
    if "/" not in flat:
        return None
    head, _, tail = flat.partition("/")
    lo = _ALPHA.get(head.strip().replace(" ", ""))
    hi = _ALPHA.get(tail.strip().replace(" ", ""))
    if not lo or not hi:
        return None
    if ALPHA_LADDER.index(lo) >= ALPHA_LADDER.index(hi):
        return None
    return lo, hi


def read_size(label: str | None, *, apparel: bool = False,
              kids: bool = False) -> SizeReading:
    """Read one size label.

    ::

        read_size("2XL")                      -> alpha XXL
        read_size("SM")                       -> alpha S
        read_size("12-18 мес.")               -> age 12..18 months
        read_size("7-8г.")                    -> age 84..96 months
        read_size("6Y")                       -> age 72..84 months
        read_size("140")                      -> height 140
        read_size("42")                       -> eu_shoe 42
        read_size("42", apparel=True)         -> numeric
        read_size("7", apparel=True, kids=True) -> age 84..96 months
        read_size("BEZ VELICINA")             -> one_size

    ``apparel`` and ``kids`` come from the facet a product was discovered
    through. Without them a bare number cannot be placed, and this returns
    ``numeric`` rather than guessing -- the same refusal `normalize_size`
    makes when a number falls outside EU 16-60.
    """
    if label is None:
        return SizeReading()
    flat = _flatten(label)
    if not flat:
        return SizeReading()

    if flat in _NO_SIZE or flat.rstrip(".") in _NO_SIZE:
        return SizeReading(system="one_size")

    alpha = _ALPHA.get(flat.replace(" ", "")) or _ALPHA.get(flat)
    if alpha:
        return SizeReading(system="alpha", alpha=alpha)

    span = _alpha_span(flat)
    if span:
        return SizeReading(system="alpha", alpha=span[0], alpha_max=span[1])

    m = _MONTH_RANGE.match(flat)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo < hi:
            return SizeReading(system="age", age_min_months=lo,
                               age_max_months=hi)

    m = _MONTH_ONE.match(flat)
    if m:
        months = int(m.group(1))
        return SizeReading(system="age", age_min_months=months,
                           age_max_months=months + 1)

    m = _YEAR_RANGE.match(flat)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo < hi:
            return SizeReading(system="age", age_min_months=lo * 12,
                               age_max_months=hi * 12)

    m = _YEAR_ONE.match(flat)
    if m:
        years = int(m.group(1))
        return SizeReading(system="age", age_min_months=years * 12,
                           age_max_months=(years + 1) * 12)

    # "110-116": a height band. The lower bound is what the shop guarantees,
    # the same reading `_parse_size_label` gives a footwear range.
    m = _NUM_RANGE.match(flat)
    if m:
        lo = int(m.group(1))
        if _HEIGHT_MIN <= lo <= _HEIGHT_MAX:
            return SizeReading(system="height", height_cm=lo)

    m = _NUMBER.match(flat)
    if m and m.group(2) is None:
        value = int(m.group(1))
        if _HEIGHT_MIN <= value <= _HEIGHT_MAX:
            return SizeReading(system="height", height_cm=value)
        if apparel and kids and 1 <= value <= _KIDS_YEARS_MAX:
            return SizeReading(system="age", age_min_months=value * 12,
                               age_max_months=(value + 1) * 12)

    if not apparel:
        eu = normalize_size(label)
        if eu is not None:
            return SizeReading(system="eu_shoe")

    return SizeReading(system="numeric")


def read_pair(primary: str | None, secondary: str | None, *,
              apparel: bool = False, kids: bool = False) -> SizeReading:
    """Read a shop that states two labels for one size.

    sport-m and sizeer do, in the same record::

        {"Velicina": "86", "EvropskaVelicina": "12-18 мес."}

    On footwear those fields are the UK and EU sizes. On apparel they are the
    height and the age -- the same two columns meaning different things per
    vertical, which is why both are read and the richer answer wins rather
    than the field name deciding.

    The adapter used to keep ``EvropskaVelicina`` and drop the other, which
    on apparel threw away the height half of a mapping these two shops are
    alone in publishing.
    """
    first = read_size(primary, apparel=apparel, kids=kids)
    second = read_size(secondary, apparel=apparel, kids=kids)

    # Both sides read: merge, because they describe one size. An age and a
    # height together is exactly the pair kids_size_chart is built from.
    if first.system == "age" and second.system == "height":
        return SizeReading(system="age", height_cm=second.height_cm,
                           age_min_months=first.age_min_months,
                           age_max_months=first.age_max_months)
    if first.system == "height" and second.system == "age":
        return SizeReading(system="age", height_cm=first.height_cm,
                           age_min_months=second.age_min_months,
                           age_max_months=second.age_max_months)
    if first.is_empty or first.system == "numeric":
        return second if not second.is_empty else first
    return first
