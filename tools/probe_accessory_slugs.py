#!/usr/bin/env python3
"""Confirm the Опрема facet slugs, and that the taxonomy can read them.

Two checks, not one, because they fail differently.

**Does the slug answer?** Recon gave the shops' Macedonian labels, not their
URLs, and a guessed slug 404s silently inside a facet walk -- the section is
simply never crawled and nothing says so.

**Can a rule read it?** This is the one that has already cost us twice. A slug
can answer perfectly and still be invisible to `mkagg.taxonomy`: Sport
Vision writes Шорц as ``sorc`` while the transliterator produces ``shorc``,
so ``/mk/sorc/`` held 835 offers that no rule matched. Checking it here costs
nothing and catches it before a single product is fetched, rather than after
a shop's worth of them.

Politeness is the project Fetcher's: one shared budget per merchant, robots
respected, every response archived like any other.

    python -X utf8 tools/probe_accessory_slugs.py
    python -X utf8 tools/probe_accessory_slugs.py --shop sportvision
    python -X utf8 tools/probe_accessory_slugs.py --dry-run   # classify only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest" / "src"))

from mkagg.fetch import (CircuitBreaker, Fetcher, FetcherConfig,  # noqa: E402
                         FetchJob, MemoryRateLimiter, Priority)
from mkagg.fetch.http import DEFAULT_USER_AGENT, HttpxTransport  # noqa: E402
from mkagg.taxonomy import classify  # noqa: E402

# -----------------------------------------------------------------------------
# Candidates
# -----------------------------------------------------------------------------
# Each entry is (Macedonian label, slug spellings to try). Two spellings
# wherever the label carries ш, ч or ж: the shops' own URLs drop the `h` the
# transliterator produces, which is the whole reason this script exists.

_SV_ACCESSORY = [
    ("Чорапи", ("chorapi", "corapi")),
    ("Качкети и капи", ("kachketi-i-kapi", "kacketi-i-kapi")),
    ("Ранец", ("ranec",)),
    ("Вреќа за тренинг", ("vreka-za-trening", "vrekja-za-trening")),
    ("Шише за вода", ("shishe-za-voda", "sise-za-voda")),
    ("Голмански ракавици", ("golmanski-rakavici",)),
    ("Наочари за пливање", ("naocari-za-plivanje", "naochari-za-plivanje")),
    ("Подлога", ("podloga",)),
    ("Опрема за пливање", ("oprema-za-plivanje",)),
    ("Ролери", ("roleri",)),
    ("Топка", ("topka", "topki")),
    ("Опрема (umbrella)", ("oprema",)),
]

_SR_ACCESSORY = [
    ("Качкет", ("kachket", "kacket")),
    ("Ранци", ("ranci",)),
    ("Торби", ("torbi",)),
    ("Торбица", ("torbica", "torbicka", "torbichka")),
    ("Ролери", ("roleri",)),
    ("Тротинет", ("trotinet", "trotineti")),
    ("Чорапи", ("chorapi", "corapi")),
    ("Топки", ("topki", "topka")),
    ("Цела опрема", ("oprema", "cela-oprema")),
]

_BUZZ_ACCESSORY = [
    ("Ранец", ("ranec",)),
    ("Качкети и капи", ("kachketi-i-kapi", "kacketi-i-kapi")),
    ("Торбица", ("torbica", "torbicka", "torbichka")),
    ("Торба", ("torba",)),
    ("Чорапи", ("chorapi", "corapi")),
    ("Опрема за чистење", ("oprema-za-chistenje", "oprema-za-cistenje")),
]

#: megasport's are full paths, read off its own navigation rather than
#: guessed -- it soft-404s, so guessing is unverifiable (see SOFT_404_PROBE).
#: Its slugs carry the gender a second time, the habit its apparel plan
#: already records, and `torbi-ranci-i-parichnici` is one facet for bags,
#: backpacks and wallets together.
_MEGA_ACCESSORY = [
    ("Чорапи мажи", ("mazhi/oprema-mazhi/chorapi-oprema-mazhi",)),
    ("Кациги мажи", ("mazhi/oprema-mazhi/kacigi-oprema-mazhi",)),
    ("Капи мажи", ("mazhi/oprema-mazhi/kapi",)),
    ("Наочари мажи", ("mazhi/oprema-mazhi/naochari",)),
    ("Ракавици мажи", ("mazhi/oprema-mazhi/rakavici-oprema-mazhi",)),
    ("Ски бандана мажи", ("mazhi/oprema-mazhi/ski-bandana",)),
    ("Торби/ранци/паричници", ("mazhi/oprema-mazhi/torbi-ranci-i-parichnici",)),
    ("Опрема мажи (umbrella)", ("mazhi/oprema-mazhi",)),
    ("Кациги жени", ("zheni/oprema-zheni/kacigi-oprema-zheni",)),
    ("Ракавици жени", ("zheni/oprema-zheni/rakavici-oprema-zheni",)),
    ("Ски бандана жени", ("zheni/oprema-zheni/ski-bandana-oprema-zheni",)),
    ("Торбици жени", ("zheni/oprema-zheni/torbici",)),
    ("Опрема жени (umbrella)", ("zheni/oprema-zheni",)),
    ("Кациги деца", ("deca/oprema-deca/kacigi-oprema-deca",)),
    ("Ракавици деца", ("deca/oprema-deca/rakavici",)),
    ("Ранец деца", ("deca/oprema-deca/ranec",)),
    ("Опрема деца (umbrella)", ("deca/oprema-deca",)),
    ("Наочари за скијање", ("ski-oprema/naochari-za-skijane",)),
]

#: A slug no shop could have. Fetched first, per shop, because an existence
#: check is worthless against a site that answers 200 for everything.
#:
#: megasport does exactly that: a nonsense slug under `oprema-mazhi` returns
#: 200 with the same 54 products as every real category, so the first run of
#: this probe read as "every spelling confirmed" and told us nothing. Any
#: slug whose products match the nonsense slug's is reported unconfirmed,
#: whatever its status line says.
SOFT_404_PROBE = "zzzz-nonsense-slug-probe"

#: The aspnet shops carry numeric subgroup codes rather than words, so there
#: is no spelling to get wrong. What is unconfirmed is the group: Grupa=03 is
#: verified on Sport-M's standalone Опрема (Segment=06) and assumed for the
#: gendered Додатоци.
_ASPNET = {
    "sportm": [("Опрема (standalone)", "/ProductCatalog?Segment=06&Grupa=03"),
               ("Додатоци мажи", "/ProductCatalog?Segment=03&Grupa=03"),
               ("Додатоци жени", "/ProductCatalog?Segment=04&Grupa=03"),
               ("Додатоци деца", "/ProductCatalog?Segment=05&Grupa=03")],
    "sizeer": [("Додатоци мажи", "/ProductCatalog?Segment=51&Grupa=03"),
               ("Додатоци жени", "/ProductCatalog?Segment=52&Grupa=03"),
               ("Додатоци деца", "/ProductCatalog?Segment=53&Grupa=03")],
}

SHOPS = {
    "sportvision": {
        "base": "https://www.sportvision.mk",
        "pattern": "/mk/{slug}/maski+unisex/vozrasni",
        "labels": _SV_ACCESSORY,
        "product": re.compile(r'/mk/[a-z0-9-]+/\d+-'),
    },
    "sportreality": {
        "base": "https://www.sportreality.mk",
        "pattern": "/mk/{slug}/maski+unisex/vozrasni",
        "labels": _SR_ACCESSORY,
        "product": re.compile(r'/mk/[a-z0-9-]+/\d+-'),
    },
    "buzz": {
        "base": "https://www.buzzsneakers.mk",
        "pattern": "/mk/{slug}/za-mazi+unisex/za-vozrasni",
        "labels": _BUZZ_ACCESSORY,
        "product": re.compile(r'/mk/[a-z0-9-]+/\d+-'),
    },
    "megasport": {
        "base": "https://megasportonlineshop.com",
        "pattern": "/kategorija/{slug}/",
        "labels": _MEGA_ACCESSORY,
        "product": re.compile(r'/p/[a-z0-9%-]+/'),
        "soft_404": "mazhi/oprema-mazhi/" + SOFT_404_PROBE,
    },
}


def build_fetcher(rps: float) -> Fetcher:
    return Fetcher(
        HttpxTransport(),
        limiter=MemoryRateLimiter(rps=rps, capacity=max(2.0, rps * 2),
                                  reserve=1.0),
        breaker=CircuitBreaker(),
        config=FetcherConfig(user_agent=DEFAULT_USER_AGENT,
                             respect_robots=True))


#: Labels that are meant to resolve to the parent. Everything else landing
#: there is a miss.
_UMBRELLA = ("umbrella", "Цела")


def readable(url: str) -> str | None:
    """What the taxonomy makes of this URL on its own.

    The title is deliberately empty: a facet page has no product title, and
    what is being asked is whether the *section* is legible.
    """
    return classify(None, url=url)


def missed(label: str, rule: str | None) -> bool:
    """Whether this section is one no rule really reads.

    Two failures, not one. A rule matching *nothing* is the loud case. The
    quiet one is a named facet resolving to `accessories`, the parent -- it
    looks like an answer and means "equipment, kind unspecified", so thirty
    women's bags would sit in the catch-all with nothing to say they had
    ever been labelled. megasport's `torbici` did exactly that.
    """
    if any(word in label for word in _UMBRELLA):
        return False
    return rule is None or rule == "accessories"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", action="append")
    ap.add_argument("--rps", type=float, default=0.7)
    ap.add_argument("--dry-run", action="store_true",
                    help="classify the candidate URLs, fetch nothing")
    args = ap.parse_args()

    wanted = set(args.shop) if args.shop else set(SHOPS) | set(_ASPNET)
    fetcher = None if args.dry_run else build_fetcher(args.rps)
    unreadable: list[tuple[str, str, str]] = []
    confirmed = 0
    requests = 0

    for slug, shop in SHOPS.items():
        if slug not in wanted:
            continue
        print(f"\n=== {slug} " + "=" * (62 - len(slug)))
        # What a slug that cannot exist returns. Anything matching it later
        # is a soft 404 wearing a 200.
        junk: frozenset[str] = frozenset()
        if fetcher is not None and shop.get("soft_404"):
            probe_url = shop["base"] + shop["pattern"].format(
                slug=shop["soft_404"])
            probe = fetcher.fetch(FetchJob(
                merchant_slug=slug, url=probe_url, kind="catalog_list",
                priority=Priority.COLD))
            requests += 1
            if probe.ok and probe.body:
                junk = frozenset(shop["product"].findall(
                    probe.body.decode("utf-8", "replace")))
            print(f"  soft-404 probe: HTTP {probe.status}, {len(junk)} items"
                  f" -- anything matching it below is not a real slug")

        print(f"{'label':24s} {'candidate':34s} {'HTTP':>5s} {'items':>6s}  rule")
        for label, spellings in shop["labels"]:
            for spelling in spellings:
                path = shop["pattern"].format(slug=spelling)
                url = shop["base"] + path
                rule = readable(url)
                status, items = "-", "-"
                if fetcher is not None:
                    result = fetcher.fetch(FetchJob(
                        merchant_slug=slug, url=url, kind="catalog_list",
                        priority=Priority.COLD))
                    requests += 1
                    status = str(result.status)
                    found: frozenset[str] = frozenset()
                    if result.ok and result.body:
                        text = result.body.decode("utf-8", "replace")
                        found = frozenset(shop["product"].findall(text))
                        items = str(len(found))
                    if junk and found == junk:
                        status, items = "soft", "404"
                    elif result.status == 200:
                        confirmed += 1
                        if missed(label, rule):
                            unreadable.append((slug, label, spelling))
                elif missed(label, rule):
                    unreadable.append((slug, label, spelling))
                print(f"{label[:23]:24s} {spelling[:33]:34s} {status:>5s} "
                      f"{items:>6s}  {rule or '-- NOTHING --'}")

    for slug, entries in _ASPNET.items():
        if slug not in wanted:
            continue
        print(f"\n=== {slug} (numeric subgroups; confirming Grupa=03) "
              + "=" * max(0, 20 - len(slug)))
        base = ("https://www.sport-m.com.mk" if slug == "sportm"
                else "https://sizeer.com.mk")
        for label, path in entries:
            status, items = "-", "-"
            if fetcher is not None:
                result = fetcher.fetch(FetchJob(
                    merchant_slug=slug, url=base + path, kind="catalog_list",
                    priority=Priority.COLD))
                requests += 1
                status = str(result.status)
                if result.ok and result.body:
                    text = result.body.decode("utf-8", "replace")
                    items = str(len(set(re.findall(
                        r"ProductDetails\?ProductID=([^&\"']+)", text))))
            print(f"{label[:23]:24s} {path[:40]:42s} {status:>5s} {items:>6s}")

    print(f"\nrequests={requests}  slugs_answering={confirmed}")
    if unreadable:
        print("\n=== answering, but NO RULE READS THE SECTION ===")
        print("Nothing matched, or it fell through to the parent catch-all.")
        print("These are the ones that cost us 835 shorts offers last time.")
        for shop_slug, label, spelling in unreadable:
            print(f"   {shop_slug:14s} {label:26s} {spelling}")
    else:
        print("\nEvery confirmed slug maps to a leaf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
