#!/usr/bin/env python3
"""
probe_mk_stores.py -- platform / endpoint / extraction recon for the MK sneaker
price-comparison project.

Pure stdlib, no pip install needed. Run from a Macedonian IP for results
identical to production.

    python -X utf8 probe_mk_stores.py                  # all stores
    python -X utf8 probe_mk_stores.py --store dsport   # one store
    python -X utf8 probe_mk_stores.py --json out.json  # machine-readable

Politeness: sequential, >=1.0s between requests to the same host, honest UA.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

UA = "MKPriceCompareBot/0.1 (recon; +mailto:you@example.mk)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 25
MIN_GAP = 1.0
_last_hit: dict[str, float] = defaultdict(float)

# ---------------------------------------------------------------- store table

STORES = {
    "sportreality": {
        "host": "www.sportreality.mk",
        "platform": "sportvision-group",
        "test_product": "/mk/patiki/51378-puma-caven-2-0",
        "probes": ["/robots.txt", "/sitemap.xml"],
    },
    "sportvision": {
        "host": "www.sportvision.mk",
        "platform": "sportvision-group",
        "test_product": "/mk/patiki/8550245-puma-caven-2-0",
        "probes": ["/robots.txt", "/sitemap.xml"],
    },
    "buzz": {
        "host": "www.buzzsneakers.mk",
        "platform": "sportvision-group",
        "test_product": "/mk/patiki/2011-adidas-patiki-stan-smith",
        "probes": ["/robots.txt", "/sitemap.xml"],
    },
    "dsport": {
        "host": "www.dsport.mk",
        "platform": "magento2",
        "test_product": "/adidas-pumpa-pump-cz9556",
        "probes": ["/robots.txt", "/media/sitemap/dsport.xml"],
    },
    "megasport": {
        "host": "megasportonlineshop.com",
        "platform": "woocommerce",
        "test_product": "/p/patiki-puma-caven-2-0-2/",
        "probes": ["/robots.txt",
                   "/wp-json/wc/store/products?per_page=1",
                   "/wp-json/wc/store/products/categories?per_page=5"],
    },
    "sizeer": {
        "host": "sizeer.com.mk",
        "platform": "aspnet-mvc-local",
        "test_product": "/",
        "probes": ["/robots.txt"],
    },
    "sportm": {
        "host": "www.sport-m.com.mk",
        "platform": "aspnet-mvc-local",
        "test_product": "/ProductCatalog/ProductDetails?ProductID=M20325",
        "probes": ["/robots.txt"],
    },
}

FINGERPRINTS = {
    "woocommerce": r"woocommerce|wp-json/wc",
    "wordpress": r"wp-content|wp-includes",
    # NB: a loose r"mage/" here matches "image/" and fires on every store.
    "magento2": r"x-magento-init|Magento_[A-Z]|/static/version\d",
    "shopify": r"cdn\.shopify|Shopify\.theme",
    "prestashop": r"prestashop",
    "nextjs": r"__NEXT_DATA__",
    "nuxt": r"__NUXT__|/_nuxt/",
    "aspnet": r"\.aspx|__VIEWSTATE|ASP\.NET",
    "jsonld": r"application/ld\+json",
    "datalayer": r"dataLayer",
    "gtag": r"gtag\(",
}

# ------------------------------------------------------------------- fetching


def fetch(url, data=None, headers=None, browser_ua=True):
    """Return (status, content_type, body). Never raises on HTTP errors."""
    host = urllib.parse.urlparse(url).netloc
    gap = MIN_GAP - (time.time() - _last_hit[host])
    if gap > 0:
        time.sleep(gap)

    hdrs = {
        "User-Agent": BROWSER_UA if browser_ua else UA,
        "Accept-Encoding": "gzip",
        "Accept-Language": "mk,en;q=0.8",
    }
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, r.headers.get("Content-Type", ""), raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            if e.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        except Exception:
            pass
        return e.code, e.headers.get("Content-Type", ""), raw
    except Exception as e:
        return 0, "ERROR {}: {}".format(type(e).__name__, e), b""
    finally:
        _last_hit[host] = time.time()


# ----------------------------------------------------------------- extractors


def extract_jsonld_product(html):
    """Tolerant JSON-LD Product extraction.

    buzzsneakers ships HTML comment markers inside its JSON-LD, so a strict
    json.loads fails there -- hence the regex rescue path.
    """
    out = {}
    blocks = re.findall(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I)
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            if node.get("@type") in ("Product", "ProductGroup"):
                offers = node.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                brand = node.get("brand")
                out = {
                    "name": node.get("name"),
                    "sku": node.get("sku") or node.get("mpn"),
                    "store_product_id": node.get("productID"),
                    "brand": brand.get("name") if isinstance(brand, dict) else brand,
                    "price": offers.get("price"),
                    "currency": offers.get("priceCurrency"),
                    "availability": offers.get("availability"),
                    "_source": "jsonld",
                }
    if not out:
        for key in ("sku", "mpn", "price", "priceCurrency"):
            m = re.search(r'"' + key + r'"\s*:\s*"([^"<>]{1,40})"', html)
            if m and "--" not in m.group(1):
                out[key] = m.group(1)
        if out:
            out["_source"] = "regex-rescue"
    return out


def extract_sportvision_sizes(html):
    """Sport Vision group: <li data-productsize-combid>, .disabled == sold out."""
    i = html.find("product-size-tabs-new")
    if i < 0:
        return []
    blk = re.sub(r">\s+<", "><", html[i:i + 12000])
    rows = []
    pattern = r'<li([^>]*?data-productsize-combid="(\d+)"[^>]*?)>(.*?)</li>'
    for attrs, combid, inner in re.findall(pattern, blk, re.S):
        eu = re.search(r'class="eur-size"[^>]*>([^<]*)', inner)
        cm = re.search(r'class="cm-size"[^>]*>([^<]*)', inner)
        rows.append({
            "variant_id": combid,
            "size_raw": eu.group(1).strip() if eu else None,
            "size_cm": (cm.group(1).strip() or None) if cm else None,
            "in_stock": "disabled" not in attrs,
        })
    return rows


def extract_product_codes(html):
    """Sport Vision group ships manufacturer codes as productCode in dataLayer."""
    pat = r'productCode["\']?\s*[:=]\s*["\']([A-Za-z0-9\-]{4,20})["\']'
    return sorted(set(re.findall(pat, html)))


# ------------------------------------------------------- platform deep probes


def probe_magento_graphql(host):
    query = ('{products(search:"patiki",pageSize:2){total_count items{sku name '
             'url_key stock_status price_range{minimum_price{final_price'
             '{value currency}}}}}}')
    st, ct, body = fetch("https://{}/graphql".format(host),
                         data=json.dumps({"query": query}).encode(),
                         headers={"Content-Type": "application/json"})
    res = {"status": st, "open": False}
    if st == 200:
        try:
            d = json.loads(body)["data"]["products"]
            res["open"] = True
            res["total_count"] = d["total_count"]
            res["sample"] = [
                {"sku": i["sku"], "name": i["name"],
                 "price": i["price_range"]["minimum_price"]["final_price"]}
                for i in d["items"][:2]
            ]
        except Exception as e:
            res["parse_error"] = str(e)
    return res


def probe_woo_store_api(host):
    st, ct, body = fetch(
        "https://{}/wp-json/wc/store/products?per_page=2".format(host))
    res = {"status": st, "open": st == 200}
    if st == 200:
        try:
            res["sample"] = [
                {"id": p["id"], "sku": p["sku"], "type": p["type"],
                 "price": p["prices"]["price"],
                 "currency": p["prices"]["currency_code"],
                 "minor_unit": p["prices"]["currency_minor_unit"]}
                for p in json.loads(body)[:2]
            ]
        except Exception as e:
            res["parse_error"] = str(e)
    return res


def probe_sportm_sizes(host, product_id):
    """POST-only MVC endpoint; returns per-size stock QUANTITY (Zaliha)."""
    referer = ("https://{}/ProductCatalog/ProductDetails?ProductID={}"
               .format(host, product_id))
    st, ct, body = fetch(
        "https://{}/ProductCatalog/GetVelicini/".format(host),
        data="ProductID={}".format(product_id).encode(),
        headers={"X-Requested-With": "XMLHttpRequest",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": referer})
    res = {"status": st, "open": st == 200}
    if st == 200:
        try:
            res["sizes"] = [
                {"uk": r.get("Velicina"), "eu": r.get("EvropskaVelicina"),
                 "qty": r.get("Zaliha")}
                for r in json.loads(body)
            ]
        except Exception as e:
            res["parse_error"] = str(e)
    return res


# ------------------------------------------------------------------ the runner


def run_store(key, cfg):
    host = cfg["host"]
    rep = {"host": host, "platform_expected": cfg["platform"]}
    print("\n" + "=" * 70)
    print("{}  ({})".format(key, host))
    print("=" * 70)

    st, ct, body = fetch("https://{}/".format(host))
    html = body.decode("utf-8", "replace")
    rep["home"] = {"status": st, "bytes": len(body)}
    rep["fingerprints"] = sorted(
        k for k, pat in FINGERPRINTS.items() if re.search(pat, html, re.I))
    print("  home            HTTP {}  {:,}B".format(st, len(body)))
    print("  fingerprints    {}".format(", ".join(rep["fingerprints"]) or "(none)"))

    rep["probes"] = {}
    for path in cfg["probes"]:
        st, ct, body = fetch("https://{}{}".format(host, path))
        ctype = ct.split(";")[0]
        rep["probes"][path] = {"status": st, "content_type": ctype, "bytes": len(body)}
        flag = "OK " if st == 200 else "   "
        print("  {}{:<5}{:<18}{:>8}B  {}".format(flag, st, ctype, len(body), path))

    plat = cfg["platform"]
    if plat == "magento2":
        rep["graphql"] = probe_magento_graphql(host)
        print("  graphql open    {}  total_count={}".format(
            rep["graphql"].get("open"), rep["graphql"].get("total_count")))
    elif plat == "woocommerce":
        rep["store_api"] = probe_woo_store_api(host)
        print("  store api open  {}".format(rep["store_api"].get("open")))
    elif plat == "aspnet-mvc-local" and "ProductID=" in cfg["test_product"]:
        pid = cfg["test_product"].split("ProductID=")[1]
        rep["sizes_api"] = probe_sportm_sizes(host, pid)
        sizes = rep["sizes_api"].get("sizes") or []
        instock = sum(1 for s in sizes if (s["qty"] or 0) > 0)
        print("  GetVelicini     open={}  sizes={}  in_stock={}".format(
            rep["sizes_api"].get("open"), len(sizes), instock))

    if cfg["test_product"] and cfg["test_product"] != "/":
        st, ct, body = fetch("https://{}{}".format(host, cfg["test_product"]))
        phtml = body.decode("utf-8", "replace")
        tp = {"url": cfg["test_product"], "status": st, "bytes": len(body)}
        rep["test_product"] = tp

        ld = extract_jsonld_product(phtml)
        if ld:
            tp["jsonld"] = ld
            print("  JSON-LD         sku={}  price={} {}  store_id={}  via={}".format(
                ld.get("sku"), ld.get("price"), ld.get("currency") or "",
                ld.get("store_product_id"), ld.get("_source")))

        codes = extract_product_codes(phtml)
        if codes:
            tp["product_codes_sample"] = codes[:5]
            print("  productCode[]   {}".format(", ".join(codes[:5])))

        if plat == "sportvision-group":
            sizes = extract_sportvision_sizes(phtml)
            tp["sizes"] = sizes
            instock = sum(1 for s in sizes if s["in_stock"])
            print("  sizes           {} total, {} in stock".format(len(sizes), instock))
            if sizes:
                marks = " ".join(
                    "{}{}".format(s["size_raw"], "+" if s["in_stock"] else "-")
                    for s in sizes[:12])
                print("                  {}".format(marks))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", action="append", choices=sorted(STORES),
                    help="probe only this store (repeatable)")
    ap.add_argument("--json", metavar="PATH", help="write machine-readable report")
    args = ap.parse_args()

    keys = args.store or sorted(STORES)
    report = {}
    for k in keys:
        try:
            report[k] = run_store(k, STORES[k])
        except Exception as e:
            report[k] = {"fatal": "{}: {}".format(type(e).__name__, e)}
            print("  FATAL {}".format(e))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("\nwrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
