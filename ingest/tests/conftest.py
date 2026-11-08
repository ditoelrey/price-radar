"""Golden-file fixture loading.

Every fixture in ``tests/fixtures`` is a real response captured from a target
store during Phase 1 recon. The point of keeping them is CI: a parser can
never silently regress, because the suite re-parses the exact bytes the live
site served. When a store redesigns, re-capture the fixture and the diff in
test output tells you precisely what moved.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_bytes(name: str) -> bytes:
    """Read a fixture, transparently handling the gzipped HTML goldens."""
    direct = FIXTURES / name
    if direct.exists():
        return direct.read_bytes()
    packed = FIXTURES / f"{name}.gz"
    if packed.exists():
        return gzip.decompress(packed.read_bytes())
    raise FileNotFoundError(
        f"{name} not in {FIXTURES} (have: "
        f"{sorted(p.name for p in FIXTURES.iterdir())})")


def load_text(name: str) -> str:
    return load_bytes(name).decode("utf-8", "replace")


def load_json(name: str):
    return json.loads(load_text(name))


@pytest.fixture(scope="session")
def fixtures():
    return FIXTURES


# ---------------------------------------------------------------------------
# The two golden test cases, as supplied by the product owner and then
# verified live during recon. These are the acceptance criteria for matching.
# ---------------------------------------------------------------------------

#: Puma Caven 2.0 -- same manufacturer SKU on three stores.
TEST_CASE_A = {
    "mpn": "392290-02",
    "mpn_norm": "39229002",
    "brand": "Puma",
    "model": "Caven 2.0",
    "stores": {
        # merchant slug -> (fixture, url, price in whole MKD)
        "sportreality": ("sportreality_caven20.html",
                         "https://www.sportreality.mk/mk/patiki/51378-puma-caven-2-0",
                         2863),
        "sportvision": ("sportvision_caven20.html",
                        "https://www.sportvision.mk/mk/patiki/8550245-puma-caven-2-0",
                        2863),
        # Store API id 31527. Note: searching "caven" returns the Caven III
        # (404484-xx) and not this shoe, so the fixture is captured by SKU.
        "megasport": ("megasport_store_search_caven20.json",
                      "https://megasportonlineshop.com/p/patiki-puma-caven-2-0-2/",
                      3999),
    },
}

#: Adidas Stan Smith -- same manufacturer SKU on two stores, 67% price spread.
TEST_CASE_B = {
    "mpn": "M20325",
    "mpn_norm": "M20325",
    "brand": "Adidas",
    "model": "Stan Smith",
    "stores": {
        "buzz": ("buzz_stansmith.html",
                 "https://www.buzzsneakers.mk/mk/patiki/2011-adidas-patiki-stan-smith",
                 4072),
        "sportm": ("sportm_stansmith.html",
                   "https://www.sport-m.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
                   6799),
        "sizeer": ("sizeer_stansmith.html",
                   "https://sizeer.com.mk/ProductCatalog/ProductDetails?ProductID=M20325",
                   6799),
    },
}
