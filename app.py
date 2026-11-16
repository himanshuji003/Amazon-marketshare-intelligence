"""
Amazon.in Market Intelligence (personal / learning use only)

Two search modes, one output set: data.json + dashboard.html + report.xlsx
  1. KEYWORD: keywords.xlsx / .csv / literal keywords -> top 10 organic products per keyword,
              market share (units / revenue) + SOV / Ads SOV / Organic SOV
  2. LINK   : products.txt (one Amazon.in link per line) -> market share computed ONLY among
              the products you provided + brand and product level SOV / Ads SOV / Organic SOV

Run:
    python app.py keywords.xlsx
    python app.py "mixer grinder" "wet grinder"
    python app.py products.txt
    python app.py products.txt --keywords keywords.xlsx      # your own keywords for the SOV scan
    python app.py --products products.txt --keywords "mixer grinder,juicer mixer"
Flags: --top --pages --brands --include-ads --browser --no-cache --out --data --xlsx --template --classic-ui --no-open
"""

import argparse
import csv
import html as htmllib
import json
import math
import random
import re
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from amazon_scraper import parse_product
from keywords import derive_keywords
from links import read_links
from market_share import compute_shares, get_bsr, get_html, parse_bought
from search_sov import analyze, scrape_keyword

CACHE_DIR = Path("cache")
CACHE_TTL = 12 * 3600  # 12 hours
COLORS = ["#4f8cff", "#ff7a59", "#2ecc9a", "#f5c542", "#b06cff", "#ff5c8a", "#3dd6d0", "#9aa5b1", "#e0e04a", "#7aa2ff"]


# ----------------------------------------------------------------------------
# Input
# ----------------------------------------------------------------------------
def read_keywords(path):
    path = str(path)
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f)]
    else:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
    if not rows:
        return []
    col, start = 0, 0
    for i, c in enumerate(rows[0]):
        if isinstance(c, str) and c.strip().lower() in ("keyword", "keywords", "search term", "search terms", "query"):
            col, start = i, 1
            break
    out = []
    for r in rows[start:]:
        if r and len(r) > col and r[col] not in (None, ""):
            v = str(r[col]).strip()
            if v:
                out.append(v)
    return out


# ----------------------------------------------------------------------------
# Scraping
# ----------------------------------------------------------------------------
def load_cache(asin):
    p = CACHE_DIR / (asin + ".json")
    if p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
    return None


def save_cache(asin, data):
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / (asin + ".json")).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def fallback_product(listing):
    return {
        "url": "https://www.amazon.in/dp/" + listing["asin"], "asin": listing["asin"],
        "title": listing["title"], "brand": listing["brand"], "price": listing["price"],
        "mrp": None, "discount": None, "currency": "INR", "rating": None, "review_count": None,
        "availability": None, "seller": None, "delivery": None, "categories": [], "bullets": [],
        "description": None, "images": [], "details": {}, "bought_text": None,
        "units_last_month": None, "bsr": None, "fetch_ok": False,
    }


def fetch_product(listing, use_browser, use_cache):
    asin = listing["asin"]
    if use_cache:
        c = load_cache(asin)
        if c:
            print("    {} (cache)".format(asin), file=sys.stderr)
            return c
    url = "https://www.amazon.in/dp/" + asin
    print("    {} ...".format(asin), file=sys.stderr)
    page = get_html(url, use_browser)
    time.sleep(random.uniform(4, 8))
    if not page:
        print("    [x] {} fetch fail".format(asin), file=sys.stderr)
        return fallback_product(listing)
    p = parse_product(page, url)
    units, bought_text = parse_bought(page)
    p["bought_text"] = bought_text
    p["units_last_month"] = units
    p["bsr"] = get_bsr(p["details"])
    p["brand"] = p["brand"] or listing["brand"] or "Unknown"
    p["title"] = p["title"] or listing["title"]
    p["fetch_ok"] = True
    if use_cache:
        save_cache(asin, p)
    return p


def pick_top(rows, n, include_ads):
    seen, out = set(), []
    for r in rows:
        if r["sponsored"] and not include_ads:
            continue
        if r["asin"] in seen:
            continue
        seen.add(r["asin"])
        out.append(r)
        if len(out) == n:
            break
    return out


def process_keyword(kw, args, known):
    print("\n[keyword] {}".format(kw), file=sys.stderr)
    rows = scrape_keyword(kw, args.pages, known, args.browser)
    sov = analyze(kw, rows)
    top = pick_top(rows, args.top, args.include_ads)
    if not top:
        print("[!] No listings found for '{}' (possible CAPTCHA / block)".format(kw), file=sys.stderr)
    products = []
    for i, l in enumerate(top, 1):
        p = dict(fetch_product(l, args.browser, not args.no_cache))
        p["rank"] = i
        p["search_position"] = l["position"]
        p["sponsored"] = l["sponsored"]
        p["keyword"] = kw
        p["brand"] = p.get("brand") or "Unknown"
        products.append(p)
    total_units, total_rev = compute_shares(products)
    return {"keyword": kw, "mode": "keywords", "sov": sov, "products": products, "total_units": total_units, "total_revenue": total_rev}


# ----------------------------------------------------------------------------
# MODE B: product links
# ----------------------------------------------------------------------------
def process_links(asins, kw_list, args, known):
    """Fetch given products -> shares among them -> SOV on keywords (given or auto-derived)."""
    print("\n[links] {} product(s)".format(len(asins)), file=sys.stderr)
    products, failed = [], []
    for i, asin in enumerate(asins, 1):
        stub = {"asin": asin, "title": "", "brand": "", "price": None}
        p = dict(fetch_product(stub, args.browser, not args.no_cache))
        if not p.get("fetch_ok"):
            failed.append(asin)
            continue
        p["rank"] = i
        p["sponsored"] = False
        products.append(p)
    if failed:
        print("[!] Fetch fail (skip): {}".format(", ".join(failed)), file=sys.stderr)
    if not products:
        return [], failed, []
    total_units, total_rev = compute_shares(products)
    kws = kw_list or derive_keywords(products)
    if not kws:
        print("[!] Could not derive search keywords. Pass --keywords, otherwise SOV cannot be computed", file=sys.stderr)
        return [], failed, []
    print("[links] SOV keywords: {}".format(", ".join(kws)), file=sys.stderr)
    brands = sorted({p["brand"] for p in products if p.get("brand")} | set(known))
    results = []
    for kw in kws:
        print("\n[keyword] {}".format(kw), file=sys.stderr)
        rows = scrape_keyword(kw, args.pages, brands, args.browser)
        sov = analyze(kw, rows)
        pos = {}
        for l in rows:
            pos.setdefault(l["asin"], l["position"])
        prods = []
        for p in products:
            q = dict(p)
            q["keyword"] = kw
            q["search_position"] = pos.get(p["asin"])
            prods.append(q)
        results.append({"keyword": kw, "mode": "links", "sov": sov, "products": prods, "total_units": total_units, "total_revenue": total_rev})
    return results, failed, kws


def brand_match(tracked, listing_brand):
    t, l = (tracked or "").casefold(), (listing_brand or "").casefold()
    return bool(t) and (l == t or l.startswith(t + " ") or t.startswith(l + " "))


def product_sov(results):
    """Per-ASIN visibility across every scanned keyword.
    Returns {asin: {listings, ads, organic, sov_%, ads_sov_%, organic_sov_%, best_organic, keywords}}."""
    tot = ads_tot = org_tot = 0
    per = {}
    for r in results:
        for l in r["sov"]["listings"]:
            tot += 1
            ads_tot += 1 if l["sponsored"] else 0
            org_tot += 0 if l["sponsored"] else 1
            d = per.setdefault(l["asin"], {"listings": 0, "ads": 0, "organic": 0, "best_organic": None, "keywords": set()})
            d["listings"] += 1
            d["keywords"].add(r["keyword"])
            if l["sponsored"]:
                d["ads"] += 1
            else:
                d["organic"] += 1
                if d["best_organic"] is None or l["position"] < d["best_organic"]:
                    d["best_organic"] = l["position"]
    pct = lambda n, d: round(n / d * 100, 2) if d else 0.0
    out = {}
    for asin, d in per.items():
        out[asin] = {"listings": d["listings"], "ads": d["ads"], "organic": d["organic"], "best_organic": d["best_organic"],
                     "keywords": sorted(d["keywords"]), "sov_%": pct(d["listings"], tot),
                     "ads_sov_%": pct(d["ads"], ads_tot), "organic_sov_%": pct(d["organic"], org_tot)}
    return out


def link_scope(results):
    """Link mode: the provided products (deduped) + brand-level market share and SOV over the scanned keywords."""
    prods = []
    for p in results[0]["products"]:
        prods.append(p)
    tot = ads_tot = org_tot = 0
    for r in results:
        for l in r["sov"]["listings"]:
            tot += 1
            ads_tot += 1 if l["sponsored"] else 0
            org_tot += 0 if l["sponsored"] else 1
    all_l = [l for r in results for l in r["sov"]["listings"]]
    unit_total = sum(p["units_last_month"] for p in prods if p.get("units_last_month"))
    rev_total = sum(p["revenue"] for p in prods if p.get("revenue"))
    brands = []
    for b in sorted({p["brand"] for p in prods}):
        bp = [p for p in prods if p["brand"] == b]
        mine = [l for l in all_l if brand_match(b, l["brand"])]
        ads = sum(1 for l in mine if l["sponsored"])
        org = len(mine) - ads
        pct = lambda n, d: round(n / d * 100, 2) if d else 0.0
        known = [p for p in bp if p.get("units_last_month")]
        u_share = round(sum(p["unit_share_%"] or 0 for p in bp), 2) if known else None
        r_share = round(sum(p["revenue_share_%"] or 0 for p in bp), 2) if any(p.get("revenue") for p in bp) else None
        sov = pct(len(mine), tot)
        brands.append({"brand": b, "products": len(bp), "est_units": sum(p["units_last_month"] or 0 for p in bp) if known else None,
                       "unit_share_%": u_share, "revenue_share_%": r_share, "listings": len(mine), "ads": ads, "organic": org,
                       "sov_%": sov, "ads_sov_%": pct(ads, ads_tot), "organic_sov_%": pct(org, org_tot),
                       "sov_among_provided_%": None, "gap_pp": None})
    trk = sum(b["listings"] for b in brands)
    for b in brands:
        b["sov_among_provided_%"] = round(b["listings"] / trk * 100, 2) if trk else 0.0
        b["gap_pp"] = round(b["sov_among_provided_%"] - b["unit_share_%"], 2) if b["unit_share_%"] is not None else None
    return {"products": prods, "brands": brands, "unit_total": unit_total, "rev_total": rev_total,
            "totals": {"listings": tot, "ads": ads_tot, "organic": org_tot}}


def summary(results, failed):
    """Console report. Link mode: scoped to the provided products only."""
    if not results:
        return
    if results[0].get("mode") == "links":
        sc = link_scope(results)
        psov = product_sov(results)
        nil = [p for p in sc["products"] if not p.get("units_last_month")]
        print("\n=== SUMMARY (link mode) ===", file=sys.stderr)
        print("Scope: market share is calculated ONLY among the {} product(s) provided ({} failed to fetch).".format(
            len(sc["products"]), len(failed)), file=sys.stderr)
        print("SOV keywords: {} | scanned listings: {} (sponsored {}, organic {})".format(
            ", ".join(r["keyword"] for r in results), sc["totals"]["listings"], sc["totals"]["ads"], sc["totals"]["organic"]), file=sys.stderr)
        if nil:
            print("NIL (no 'bought in past month' badge, excluded from shares): {}".format(", ".join(p["asin"] for p in nil)), file=sys.stderr)
        f = lambda v: "NIL" if v is None else "{:.1f}".format(v)
        print("\nProduct-level market share and SOV", file=sys.stderr)
        print("{:<12}{:<18}{:>9}{:>10}{:>10}{:>8}{:>8}{:>8}".format("ASIN", "Brand", "Units", "Unit %", "Rev %", "SOV %", "Ads %", "Org %"), file=sys.stderr)
        for p in sc["products"]:
            d = psov.get(p["asin"], {})
            print("{:<12}{:<18}{:>9}{:>10}{:>10}{:>8}{:>8}{:>8}".format(
                p["asin"], (p.get("brand") or "")[:17], p.get("units_last_month") if p.get("units_last_month") else "NIL",
                f(p["unit_share_%"]), f(p["revenue_share_%"]), f(d.get("sov_%", 0.0)), f(d.get("ads_sov_%", 0.0)), f(d.get("organic_sov_%", 0.0))), file=sys.stderr)
        print("\nBrand-level market share and SOV", file=sys.stderr)
        print("{:<20}{:>10}{:>10}{:>8}{:>8}{:>8}{:>12}{:>10}".format("Brand", "Unit %", "Rev %", "SOV %", "Ads %", "Org %", "SOV/yours %", "Gap (pp)"), file=sys.stderr)
        for b in sc["brands"]:
            print("{:<20}{:>10}{:>10}{:>8}{:>8}{:>8}{:>12}{:>10}".format(b["brand"][:19], f(b["unit_share_%"]), f(b["revenue_share_%"]),
                  f(b["sov_%"]), f(b["ads_sov_%"]), f(b["organic_sov_%"]), f(b["sov_among_provided_%"]), f(b["gap_pp"])), file=sys.stderr)
        return
    seen, prods = set(), []
    for r in results:
        for p in r["products"]:
            if p["asin"] not in seen:
                seen.add(p["asin"])
                prods.append(p)
    nil = sum(1 for p in prods if not p.get("units_last_month"))
    print("\n=== SUMMARY (keyword mode) ===  products: {} | NIL (no badge): {} | keywords: {}".format(
        len(prods), nil, ", ".join(r["keyword"] for r in results)), file=sys.stderr)
    data = build_data(results)
    tot = sum(p["units"] or 0 for p in data["products"])
    ls = [l for k in data["keywords"] for l in k["listings"]]
    allc, orgc, adc = len(ls), sum(1 for l in ls if not l["sponsored"]), sum(1 for l in ls if l["sponsored"])
    print("{:<22}{:>10}{:>9}{:>9}{:>9}".format("Brand", "Unit %", "SOV %", "Ads %", "Org %"), file=sys.stderr)
    for b in sorted({p["brand"] for p in data["products"]}):
        bp = [p for p in data["products"] if p["brand"] == b]
        u = sum(p["units"] or 0 for p in bp)
        known_u = any(p["units"] for p in bp)
        mine = [l for l in ls if brand_match(b, l["brand"])]
        f = lambda n, d: "{:.1f}".format(n / d * 100) if d else "-"
        print("{:<22}{:>10}{:>9}{:>9}{:>9}".format(b[:21], f(u, tot) if known_u else "NIL", f(len(mine), allc),
              f(sum(1 for l in mine if l["sponsored"]), adc), f(sum(1 for l in mine if not l["sponsored"]), orgc)), file=sys.stderr)


# ----------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------
def E(s):
    return htmllib.escape("" if s is None else str(s), quote=True)


def num(n):
    if n is None:
        return "-"
    s = str(int(round(n)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return head + "," + tail


def inr(n):
    return "-" if n is None else "Rs " + num(n)


def pct(n):
    return "-" if n is None else "{}%".format(n)


def disc_value(p):
    if p.get("mrp") and p.get("price") and p["mrp"] > p["price"]:
        return round((p["mrp"] - p["price"]) / p["mrp"] * 100)
    return None


def td(text, v=None, cls=""):
    return '<td{} data-v="{}">{}</td>'.format(' class="{}"'.format(cls) if cls else "", E(v if v is not None else ""), text)


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    nu = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    return nu / math.sqrt(dx * dy) if dx and dy else 0.0


# ----------------------------------------------------------------------------
# HTML pieces
# ----------------------------------------------------------------------------
def label_products(products):
    valid = [p for p in products if p.get("units_last_month") and p.get("price")]
    cnt, seen = {}, {}
    for p in valid:
        k = p["brand"].casefold()
        cnt[k] = cnt.get(k, 0) + 1
    for p in products:
        p["label"] = p["brand"]
        p["color"] = "#6b7686"
    for i, p in enumerate(valid):
        k = p["brand"].casefold()
        seen[k] = seen.get(k, 0) + 1
        p["label"] = p["brand"] + (" #{}".format(seen[k]) if cnt[k] > 1 else "")
        p["color"] = COLORS[i % len(COLORS)]
    return valid


def donut(valid):
    acc, stops = 0.0, []
    for p in valid:
        s = acc
        acc += p["unit_share_%"]
        stops.append("{} {:.2f}% {:.2f}%".format(p["color"], s, acc))
    legend = "".join(
        '<div class="lg"><span class="dot" style="background:{}"></span>{}<b>{}%</b></div>'.format(
            p["color"], E(p["label"]), p["unit_share_%"]) for p in valid)
    return ('<div class="donutwrap"><div class="donut" style="background:conic-gradient({})"></div>'
            '<div class="legend">{}</div></div>').format(",".join(stops), legend)


def bars(valid):
    mx = max(max(p["unit_share_%"], p["revenue_share_%"]) for p in valid) or 1
    out = ['<div class="key"><span><i style="background:#4f8cff"></i>Units</span>'
           '<span><i style="background:#2ecc9a"></i>Revenue</span></div>']
    for p in valid:
        out.append(
            '<div class="brow"><div class="bl">{}</div><div class="bt">'
            '<div class="bar u" style="width:{:.1f}%"><span>{}%</span></div>'
            '<div class="bar r" style="width:{:.1f}%"><span>{}%</span></div></div></div>'.format(
                E(p["label"]), p["unit_share_%"] / mx * 100, p["unit_share_%"],
                p["revenue_share_%"] / mx * 100, p["revenue_share_%"]))
    return "".join(out)


def scatter(valid):
    W, H, L, R, T, B = 560, 320, 60, 20, 20, 44
    maxp = max(p["price"] for p in valid) * 1.15
    maxu = max(p["units_last_month"] for p in valid) * 1.15
    maxr = max((p.get("review_count") or 0) for p in valid) or 1

    def sx(v):
        return L + v / maxp * (W - L - R)

    def sy(v):
        return H - B - v / maxu * (H - T - B)

    s = ['<svg viewBox="0 0 {} {}" width="100%" role="img" aria-label="Price vs units">'.format(W, H)]
    s.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#3a4252"/>'.format(L, H - B, W - R, H - B))
    s.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#3a4252"/>'.format(L, T, L, H - B))
    for f in (0, 0.5, 1):
        s.append('<text x="{:.1f}" y="{}" fill="#8b95a5" font-size="11" text-anchor="middle">{}</text>'.format(sx(maxp * f), H - B + 16, num(maxp * f)))
        s.append('<text x="{}" y="{:.1f}" fill="#8b95a5" font-size="11" text-anchor="end">{}</text>'.format(L - 8, sy(maxu * f) + 4, num(maxu * f)))
    s.append('<text x="{}" y="{}" fill="#8b95a5" font-size="11" text-anchor="middle">Price (Rs)</text>'.format((L + W - R) / 2, H - 6))
    s.append('<text x="14" y="{0}" fill="#8b95a5" font-size="11" text-anchor="middle" transform="rotate(-90 14 {0})">Units / month</text>'.format(H / 2))
    for p in valid:
        r = 8 + 18 * math.sqrt((p.get("review_count") or 0) / maxr)
        s.append('<circle cx="{:.1f}" cy="{:.1f}" r="{:.1f}" fill="{c}" fill-opacity="0.75" stroke="{c}"><title>{t}</title></circle>'.format(
            sx(p["price"]), sy(p["units_last_month"]), r, c=p["color"],
            t=E("{} | {} | {} units | {} reviews".format(p["label"], inr(p["price"]), num(p["units_last_month"]), num(p.get("review_count") or 0)))))
        s.append('<text x="{:.1f}" y="{:.1f}" fill="#d5dbe6" font-size="11">{}</text>'.format(sx(p["price"]) + r + 4, sy(p["units_last_month"]) + 4, E(p["label"])))
    s.append("</svg>")
    return "".join(s)


def canon_brand(brand, sov_keys):
    """The brand on the product page and the brand inferred from a search-result title can differ
    ("Pigeon" vs "Pigeon by Stovekraft"); map them with a prefix match."""
    k = brand.casefold()
    if k in sov_keys:
        return k
    for s in sov_keys:
        if s.startswith(k + " ") or k.startswith(s + " "):
            return s
    return k


def brand_share(valid, sov_keys=()):
    d = {}
    for p in valid:
        b = d.setdefault(canon_brand(p["brand"], sov_keys), {"unit": 0.0, "rev": 0.0})
        b["unit"] += p["unit_share_%"]
        b["rev"] += p["revenue_share_%"]
    return {k: {"unit": round(v["unit"], 2), "rev": round(v["rev"], 2)} for k, v in d.items()}


def insights(valid, sov, bshare):
    ins = []
    by_units = sorted(valid, key=lambda p: -p["units_last_month"])
    by_rev = sorted(valid, key=lambda p: -p["revenue"])
    by_price = sorted(valid, key=lambda p: p["price"])
    lead, rev_lead = by_units[0], by_rev[0]
    ins.append("<b>{}</b> has the #1 unit share in the top 10 ({}%).".format(E(lead["label"]), lead["unit_share_%"]))
    if rev_lead is not lead:
        ins.append("<b>{}</b> leads on revenue share ({}%): higher price point compensates for fewer units.".format(E(rev_lead["label"]), rev_lead["revenue_share_%"]))
    else:
        ins.append("<b>{}</b> also leads on revenue share ({}%): ahead on both volume and value.".format(E(lead["label"]), lead["revenue_share_%"]))
    cheap, pricey = by_price[0], by_price[-1]
    if cheap is not pricey:
        ins.append("Lowest price: <b>{}</b> ({}, {}% of units); highest price: <b>{}</b> ({}, {}% of units).".format(
            E(cheap["label"]), inr(cheap["price"]), cheap["unit_share_%"], E(pricey["label"]), inr(pricey["price"]), pricey["unit_share_%"]))
    if len(valid) >= 3:
        r = pearson([p["price"] for p in valid], [p["units_last_month"] for p in valid])
        if r < -0.4:
            ins.append("Units fall as price rises (corr {:.2f}): demand looks price-sensitive.".format(r))
        elif r > 0.4:
            ins.append("Higher-priced products also sell more (corr {:.2f}): a brand / quality premium is working.".format(r))
        else:
            ins.append("No clear price-to-units relationship (corr {:.2f}): brand, reviews or listing quality likely matter more.".format(r))
    rated = sorted([p for p in valid if p.get("rating")], key=lambda p: -p["rating"])
    if len(rated) > 1 and rated[0] is not lead:
        ins.append("<b>{}</b> has the highest rating ({}) but only {}% unit share: rating alone does not drive sales.".format(
            E(rated[0]["label"]), rated[0]["rating"], rated[0]["unit_share_%"]))
    mom = sorted([(p, p["units_last_month"] / p["review_count"]) for p in valid if p.get("review_count")], key=lambda x: -x[1])
    if len(mom) > 1:
        ins.append("Momentum (monthly units / total reviews): <b>{}</b> is highest ({:.2f}), suggesting a rising or newer listing; <b>{}</b> is lowest ({:.2f}), suggesting a mature, slowing listing.".format(
            E(mom[0][0]["label"]), mom[0][1], E(mom[-1][0]["label"]), mom[-1][1]))
    # SOV vs sales gap
    sb = {b["brand"].casefold(): b for b in sov.get("brands", [])}
    gaps = []
    for k, v in bshare.items():
        if k in sb:
            gaps.append((sb[k]["sov_%"] - v["unit"], sb[k], v))
    if len(gaps) >= 2:
        gaps.sort(key=lambda x: -x[0])
        g = gaps[0]
        if g[0] >= 5:
            ins.append("<b>{}</b>: SOV {}% but unit share {}%: high visibility, low conversion (check listing quality, price, reviews).".format(E(g[1]["brand"]), g[1]["sov_%"], g[2]["unit"]))
        g = gaps[-1]
        if g[0] <= -5:
            ins.append("<b>{}</b>: SOV only {}% but unit share {}%: under-exposed relative to sales, room to grow visibility.".format(E(g[1]["brand"]), g[1]["sov_%"], g[2]["unit"]))
    ads_only = sorted([b for b in sov.get("brands", []) if b["ads"] > 0 and b["organic"] == 0], key=lambda b: -b["ads"])
    if ads_only:
        ins.append("Ad-only brands (0 organic listings): <b>{}</b>.".format(", ".join(E(b["brand"]) for b in ads_only[:4])))
    disc = sorted([(p, disc_value(p)) for p in valid if disc_value(p)], key=lambda x: -x[1])
    avg_price = sum(p["revenue"] for p in valid) / sum(p["units_last_month"] for p in valid)
    if disc:
        ins.append("Deepest discount: <b>{}</b> ({}% off MRP). Weighted average selling price: {}.".format(E(disc[0][0]["label"]), disc[0][1], inr(avg_price)))
    return "".join("<li>{}</li>".format(i) for i in ins)


def sov_table(sov, bshare):
    if not sov["total"]:
        return '<p class="warn">No search results were returned (possible CAPTCHA / block).</p>'
    head = ('<div class="sovsum">Scanned listings: <b>{}</b> &nbsp;|&nbsp; Sponsored: <b>{}</b> &nbsp;|&nbsp; Organic: <b>{}</b> &nbsp;|&nbsp; Ad load: <b>{}%</b></div>'
            ).format(sov["total"], sov["sponsored"], sov["organic"], sov["ad_load_%"])
    rows = []
    for b in sov["brands"][:12]:
        bs = bshare.get(b["brand"].casefold())
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
            '<td><div class="mini"><i style="width:{}%"></i></div>{}%</td><td><div class="mini a"><i style="width:{}%"></i></div>{}%</td>'
            '<td><div class="mini o"><i style="width:{}%"></i></div>{}%</td><td>{}%</td><td>{}</td><td>{}</td></tr>'.format(
                E(b["brand"]), b["listings"], b["ads"], b["organic"],
                min(b["sov_%"], 100), b["sov_%"], min(b["ads_sov_%"], 100), b["ads_sov_%"],
                min(b["organic_sov_%"], 100), b["organic_sov_%"], b["weighted_sov_%"],
                pct(bs["unit"]) if bs else "-", pct(bs["rev"]) if bs else "-"))
    return (head + '<div class="tw"><table><thead><tr><th>Brand</th><th>Listings</th><th>Ads</th><th>Organic</th><th>SOV</th><th>Ads SOV</th>'
            '<th>Organic SOV</th><th>Weighted SOV</th><th>Unit share (top 10)</th><th>Rev share (top 10)</th></tr></thead><tbody>' + "".join(rows) +
            "</tbody></table></div>")


def products_table(products):
    heads = ["#", "", "Brand", "Title", "Price", "MRP", "Disc.", "Rating", "Reviews", "Bought/mo", "Unit %", "Rev %", "BSR", "Seller"]
    out = ['<div class="tw"><table class="sortable"><thead><tr>' + "".join("<th>{}</th>".format(h) for h in heads) + "</tr></thead><tbody>"]
    for p in products:
        img = (p.get("images") or [None])[0]
        badges = ""
        if p.get("sponsored"):
            badges += ' <span class="badge ad">AD</span>'
        if not p.get("fetch_ok"):
            badges += ' <span class="badge bad">data fetch fail</span>'
        d = disc_value(p)
        cells = [
            td(p["rank"], p["rank"]),
            td('<img class="th" loading="lazy" src="{}" alt="">'.format(E(img)) if img else "", ""),
            td('<span class="dot" style="background:{}"></span>{}'.format(p["color"], E(p["brand"])), p["brand"]),
            td('<a href="{}" target="_blank" rel="noopener">{}</a>{}'.format(E(p["url"]), E((p.get("title") or "")[:110]), badges), p.get("title") or "", "t"),
            td(inr(p.get("price")), p.get("price") or -1),
            td(inr(p.get("mrp")), p.get("mrp") or -1),
            td("-{}%".format(d) if d else "-", d if d else -1),
            td(p.get("rating") or "-", p.get("rating") or -1),
            td(num(p.get("review_count")), p.get("review_count") or -1),
            td(num(p.get("units_last_month")) if p.get("units_last_month") else "-", p.get("units_last_month") or -1),
            td("<b>{}</b>".format(pct(p.get("unit_share_%"))), p.get("unit_share_%") if p.get("unit_share_%") is not None else -1),
            td("<b>{}</b>".format(pct(p.get("revenue_share_%"))), p.get("revenue_share_%") if p.get("revenue_share_%") is not None else -1),
            td("#" + num(p["bsr"]) if p.get("bsr") else "-", p.get("bsr") or -1),
            td(E(p.get("seller") or "-"), p.get("seller") or ""),
        ]
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def details_blocks(products):
    out = []
    for p in products:
        imgs = "".join('<img loading="lazy" src="{}" alt="">'.format(E(u)) for u in (p.get("images") or [])[:8])
        facts = [("Price", inr(p.get("price"))), ("MRP", inr(p.get("mrp"))), ("Rating", "{} ({} reviews)".format(p.get("rating") or "-", num(p.get("review_count")))),
                 ("Bought in past month", p.get("bought_text") or "-"), ("Best Sellers Rank", "#" + num(p["bsr"]) if p.get("bsr") else "-"),
                 ("Availability", p.get("availability") or "-"), ("Seller", p.get("seller") or "-"), ("Delivery", p.get("delivery") or "-"),
                 ("Category", " > ".join(p.get("categories") or []) or "-"), ("ASIN", p["asin"]),
                 ("Search position", p.get("search_position"))]
        facts_html = "".join("<tr><th>{}</th><td>{}</td></tr>".format(E(k), E(v)) for k, v in facts)
        bullets = "".join("<li>{}</li>".format(E(b)) for b in (p.get("bullets") or [])) or "<li>-</li>"
        spec = "".join("<tr><th>{}</th><td>{}</td></tr>".format(E(k), E(v)) for k, v in (p.get("details") or {}).items()) or "<tr><td>-</td></tr>"
        out.append(
            '<details class="pd"><summary><b>#{}</b> {} <span class="mut">{} | {} | {}/mo</span></summary><div class="pdb">'
            '<div class="imgs">{}</div><div class="cols"><div><h3>Key facts</h3><table class="spec">{}</table><h3>About this item</h3><ul>{}</ul></div>'
            '<div><h3>Specifications</h3><table class="spec">{}</table></div></div></div></details>'.format(
                p["rank"], E((p.get("title") or "")[:100]), E(p["brand"]), inr(p.get("price")), num(p.get("units_last_month")) if p.get("units_last_month") else "-",
                imgs, facts_html, bullets, spec))
    return "".join(out)


def panel(res, idx):
    kw, P, sov = res["keyword"], res["products"], res["sov"]
    valid = label_products(P)
    bshare = brand_share(valid, {b["brand"].casefold() for b in sov.get("brands", [])})
    on = " on" if idx == 0 else ""
    if not P:
        return '<section class="panel{}" id="k{}"><p class="warn">No products found for this keyword. Possible CAPTCHA / block: retry with the --browser flag.</p></section>'.format(on, idx)
    rated = [p["rating"] for p in P if p.get("rating")]
    fetched = sum(1 for p in P if p.get("fetch_ok"))
    kpis = [("Products", "{} ({} fetched)".format(len(P), fetched)),
            ("Units / month (est.)", num(res["total_units"]) if valid else "-"),
            ("Revenue / month (est.)", inr(res["total_revenue"]) if valid else "-"),
            ("Avg price", inr(res["total_revenue"] / res["total_units"]) if valid else "-"),
            ("Avg rating", "{:.2f}".format(sum(rated) / len(rated)) if rated else "-"),
            ("Ad load (search)", pct(sov["ad_load_%"]) if sov["total"] else "-")]
    kpi_html = "".join('<div class="card kpi"><div class="k">{}</div><div class="v">{}</div></div>'.format(k, E(v)) for k, v in kpis)
    if valid:
        charts = ('<div class="grid"><div class="card"><h2>Unit share (top 10)</h2>{}</div><div class="card"><h2>Unit share vs Revenue share</h2>{}</div></div>'
                  '<div class="grid"><div class="card"><h2>Price vs units (bubble = reviews)</h2>{}</div><div class="card"><h2>Insights</h2><ul>{}</ul></div></div>').format(
            donut(valid), bars(valid), scatter(valid), insights(valid, sov, bshare))
    else:
        charts = '<div class="card"><p class="warn">No product has a "bought in past month" badge or a price, so market share and charts could not be computed.</p></div>'
    return ('<section class="panel{on}" id="k{idx}"><div class="kpis">{kpi}</div>{charts}'
            '<div class="card"><h2>Share of Voice (search results)</h2>{sov}</div>'
            '<div class="card"><h2>Top {n} products</h2>{table}</div>'
            '<div class="card"><h2>Product details</h2>{det}</div></section>').format(
        on=on, idx=idx, kpi=kpi_html, charts=charts, sov=sov_table(sov, bshare), n=len(P), table=products_table(P), det=details_blocks(P))


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon.in Keyword Dashboard</title><style>
:root{--bg:#0f131a;--card:#171d27;--line:#262e3b;--tx:#e6ebf3;--mut:#8b95a5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;padding:24px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin-bottom:16px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.tab{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:999px;padding:7px 16px;cursor:pointer;font:inherit}
.tab.on{background:#4f8cff;border-color:#4f8cff;color:#0b0f15;font-weight:600}
.panel{display:none}.panel.on{display:block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.kpis .card{margin-bottom:0}.kpi .v{font-size:20px;font-weight:700}.kpi .k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}.grid .card{margin-bottom:0}.grid{margin-bottom:16px}
h2{font-size:14px;margin:0 0 12px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}h3{font-size:13px;margin:14px 0 6px}
.donutwrap{display:flex;gap:20px;align-items:center;flex-wrap:wrap}
.donut{width:170px;height:170px;border-radius:50%;position:relative;flex:none}
.donut:after{content:"";position:absolute;inset:34px;background:var(--card);border-radius:50%}
.legend{flex:1;min-width:150px}.lg{display:flex;align-items:center;gap:8px;margin:4px 0}.lg b{margin-left:auto;padding-left:16px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}.lg .dot{margin:0}
.brow{display:flex;align-items:center;gap:10px;margin:10px 0}.bl{width:110px;font-size:13px}.bt{flex:1}
.bar{height:16px;border-radius:4px;margin:2px 0;min-width:34px;display:flex;align-items:center;justify-content:flex-end;padding-right:6px;font-size:11px;color:#0b0f15;font-weight:600}
.bar.u{background:#4f8cff}.bar.r{background:#2ecc9a}
.key{display:flex;gap:16px;color:var(--mut);font-size:12px;margin-bottom:4px}.key i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
ul{margin:0;padding-left:18px}li{margin:7px 0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--mut);font-weight:600;font-size:12px;white-space:nowrap}.sortable th{cursor:pointer}.sortable th:hover{color:var(--tx)}
td.t{min-width:260px;max-width:340px}td.t a{color:var(--tx);text-decoration:none}td.t a:hover{text-decoration:underline}.tw{overflow-x:auto}
td:not(.t){white-space:nowrap}img.th{width:44px;height:44px;object-fit:contain;background:#fff;border-radius:6px}
.badge{font-size:10px;padding:1px 6px;border-radius:4px;margin-left:6px}.badge.ad{background:#f5c542;color:#0b0f15}.badge.bad{background:#ff5c8a;color:#0b0f15}
.sovsum{margin-bottom:10px;color:var(--mut)}.sovsum b{color:var(--tx)}
.mini{display:inline-block;width:60px;height:8px;background:#232b38;border-radius:4px;margin-right:8px;vertical-align:middle;overflow:hidden}
.mini i{display:block;height:100%;background:#4f8cff}.mini.a i{background:#f5c542}.mini.o i{background:#2ecc9a}
details.pd{border:1px solid var(--line);border-radius:10px;margin:8px 0;background:#131923}
details.pd summary{cursor:pointer;padding:10px 14px}.mut{color:var(--mut);margin-left:8px;font-size:12px}
.pdb{padding:4px 14px 14px}.imgs{display:flex;gap:8px;overflow-x:auto;margin-bottom:8px}.imgs img{height:90px;background:#fff;border-radius:6px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}
table.spec th{width:38%;white-space:normal;font-weight:600;color:var(--mut)}table.spec td{white-space:normal}
.note{color:var(--mut);font-size:12px;margin-top:14px}.warn{color:#f5c542}
</style></head><body>
<h1>Amazon.in Keyword Dashboard</h1>
<div class="sub">%%META%%</div>
<div class="tabs">%%TABS%%</div>
%%PANELS%%
<p class="note">Note: Amazon does not publish exact sales. "Bought in past month" is a bucketed lower-bound estimate (e.g. 1K+, 10K+), so units and revenue are estimates. Revenue = est. units x current price.
Market share is calculated only among the products shown. SOV is based on the scanned search-result listings (sponsored + organic) and can vary by pincode and time.</p>
<script>
document.querySelectorAll('.tab').forEach(function(b){b.addEventListener('click',function(){
document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
document.querySelectorAll('.panel').forEach(function(x){x.classList.remove('on')});
b.classList.add('on');document.getElementById(b.dataset.t).classList.add('on');});});
document.querySelectorAll('table.sortable').forEach(function(t){t.querySelectorAll('th').forEach(function(th,i){th.addEventListener('click',function(){
var tb=t.tBodies[0],rows=Array.prototype.slice.call(tb.rows),asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
rows.sort(function(a,b){var x=a.cells[i].dataset.v,y=b.cells[i].dataset.v,nx=parseFloat(x),ny=parseFloat(y);
var r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?r:-r;});
rows.forEach(function(r){tb.appendChild(r)});});});});
</script></body></html>"""


def build_html(results):
    tabs = "".join('<button class="tab{}" data-t="k{}">{}</button>'.format(" on" if i == 0 else "", i, E(r["keyword"])) for i, r in enumerate(results))
    panels = "".join(panel(r, i) for i, r in enumerate(results))
    meta = "{} keyword(s) | generated {}".format(len(results), datetime.now().strftime("%d %b %Y, %I:%M %p"))
    return TEMPLATE.replace("%%META%%", meta).replace("%%TABS%%", tabs).replace("%%PANELS%%", panels)


# ----------------------------------------------------------------------------
# Excel output
# ----------------------------------------------------------------------------
def _style_sheets(sheets):
    from openpyxl.styles import Font, PatternFill
    for sheet in sheets:
        for c in sheet[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2F3B52")
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:60])
            sheet.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)


def write_excel_links(results, path):
    """Link mode workbook: Market Share (provided products only), Brand SOV, SOV (tracked brands + 'Other brands'), Product Details."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    sc = link_scope(results)
    psov = product_sov(results)
    nil = lambda v: "NIL" if v is None else v
    wb = Workbook()
    ws = wb.active
    ws.title = "Market Share"
    ws.append(["asin", "brand", "title", "price", "mrp", "rating", "review_count", "bought_text", "est_units_30d", "unit_share_%",
               "revenue_share_%", "bsr", "product_sov_%", "product_ads_sov_%", "product_organic_sov_%", "best_organic_position",
               "listed_in_keywords", "url"])
    for p in sc["products"]:
        d = psov.get(p["asin"], {})
        ws.append([p["asin"], p["brand"], p["title"], p.get("price"), p.get("mrp"), p.get("rating"), p.get("review_count"),
                   p.get("bought_text"), p.get("units_last_month") or "NIL", nil(p["unit_share_%"]), nil(p["revenue_share_%"]), p.get("bsr"),
                   d.get("sov_%", 0.0), d.get("ads_sov_%", 0.0), d.get("organic_sov_%", 0.0), d.get("best_organic"),
                   ", ".join(d.get("keywords", [])), "https://www.amazon.in/dp/" + p["asin"]])
    ws.append([])
    ws.append(["TOTAL", "", "{} products provided".format(len(sc["products"])), "", "", "", "", "", sc["unit_total"],
               100.0 if sc["unit_total"] else "NIL", 100.0 if sc["rev_total"] else "NIL"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append([])
    ws.append(["Scope: market share is calculated only among the products provided. Competitor listings from the keyword scan are used only as the SOV denominator."])
    ws.append(["NIL = no 'bought in past month' badge on the product page; excluded from unit / revenue share (not treated as zero)."])
    ws.append(["est_units_30d is a lower-bound bucket estimate over a rolling 30 days. Revenue share = est. units x current price."])
    ws2 = wb.create_sheet("Brand SOV")
    ws2.append(["brand", "products_provided", "est_units_30d", "unit_share_%", "revenue_share_%", "listings", "ads", "organic",
                "sov_%", "ads_sov_%", "organic_sov_%", "sov_among_provided_%", "gap_pp (sov_among_provided - unit_share)"])
    for b in sc["brands"]:
        ws2.append([b["brand"], b["products"], nil(b["est_units"]), nil(b["unit_share_%"]), nil(b["revenue_share_%"]), b["listings"], b["ads"],
                    b["organic"], b["sov_%"], b["ads_sov_%"], b["organic_sov_%"], b["sov_among_provided_%"], nil(b["gap_pp"])])
    ws3 = wb.create_sheet("SOV")
    ws3.append(["keyword", "brand", "listings", "ads", "organic", "sov_%", "ads_sov_%", "organic_sov_%", "weighted_sov_%"])
    tracked = [b["brand"] for b in sc["brands"]]
    for r in results:
        rest = {"listings": 0, "ads": 0, "organic": 0, "sov_%": 0.0, "ads_sov_%": 0.0, "organic_sov_%": 0.0, "weighted_sov_%": 0.0}
        for b in r["sov"]["brands"]:
            if any(brand_match(t, b["brand"]) for t in tracked):
                ws3.append([r["keyword"]] + [b[c] for c in ["brand", "listings", "ads", "organic", "sov_%", "ads_sov_%", "organic_sov_%", "weighted_sov_%"]])
            else:
                for k in rest:
                    rest[k] = round(rest[k] + b[k], 2)
        ws3.append([r["keyword"], "Other brands (all competitors)"] + [rest[c] for c in ["listings", "ads", "organic", "sov_%", "ads_sov_%", "organic_sov_%", "weighted_sov_%"]])
    ws4 = wb.create_sheet("Product Details")
    ws4.append(["asin", "spec", "value"])
    for p in sc["products"]:
        for k, v in (p.get("details") or {}).items():
            ws4.append([p["asin"], k, v])
    _style_sheets((ws, ws2, ws3, ws4))
    wb.save(path)


def write_excel(results, path):
    if results and results[0].get("mode") == "links":
        return write_excel_links(results, path)
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Top Products"
    cols = ["keyword", "rank", "search_position", "sponsored", "asin", "brand", "title", "price", "mrp", "discount", "rating", "review_count",
            "bought_text", "units_last_month", "unit_share_%", "revenue_share_%", "bsr", "availability", "seller", "delivery",
            "categories", "bullets", "main_image", "url", "fetch_ok"]
    ws.append(cols)
    for r in results:
        for p in r["products"]:
            row = []
            for c in cols:
                v = p.get(c)
                if c == "categories":
                    v = " > ".join(v or [])
                elif c == "bullets":
                    v = "\n".join(v or [])
                elif c == "main_image":
                    v = (p.get("images") or [None])[0]
                elif c == "sponsored" or c == "fetch_ok":
                    v = "yes" if v else "no"
                row.append(v)
            ws.append(row)
    ws2 = wb.create_sheet("SOV")
    sov_cols = ["keyword", "brand", "listings", "ads", "organic", "sov_%", "ads_sov_%", "organic_sov_%", "weighted_sov_%"]
    ws2.append(sov_cols)
    for r in results:
        for b in r["sov"]["brands"]:
            ws2.append([r["keyword"]] + [b[c] for c in sov_cols[1:]])
    ws3 = wb.create_sheet("Product Details")
    ws3.append(["keyword", "asin", "spec", "value"])
    for r in results:
        for p in r["products"]:
            for k, v in (p.get("details") or {}).items():
                ws3.append([r["keyword"], p["asin"], k, v])
    for sheet in (ws, ws2, ws3):
        for c in sheet[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2F3B52")
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:60])
            sheet.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=(c.column_letter in ("G", "V")))
    wb.save(path)


# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# data.json + modern dashboard (dashboard_template.html)
# ----------------------------------------------------------------------------
def build_data(results, old_history=None):
    prods, seen = [], set()
    for res in results:
        for p in res["products"]:
            if p["asin"] in seen:
                continue
            seen.add(p["asin"])
            prods.append({
                "asin": p["asin"], "brand": p.get("brand") or "Unknown", "title": p.get("title") or p["asin"],
                "image": (p.get("images") or [None])[0], "price": p.get("price"), "mrp": p.get("mrp"),
                "rating": p.get("rating"), "review_count": p.get("review_count"),
                "bought_text": p.get("bought_text"), "units": p.get("units_last_month"), "bsr": p.get("bsr"),
            })
    kws = []
    for res in results:
        ls = [{"position": l["position"], "asin": l["asin"], "brand": l.get("brand") or "Unknown",
               "sponsored": bool(l["sponsored"])} for l in res["sov"]["listings"]]
        kws.append({"keyword": res["keyword"], "listings": ls})
    top_n = max([l["position"] for k in kws for l in k["listings"]] or [0])
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    # history: aaj ka snapshot (brand-wise units + all-SOV), purani dates same rahengi
    bu, tot = {}, 0
    for p in prods:
        if p["units"]:
            bu[p["brand"]] = bu.get(p["brand"], 0) + p["units"]
    allc = {}
    for k in kws:
        for l in k["listings"]:
            allc[l["brand"]] = allc.get(l["brand"], 0) + 1
    tot = sum(allc.values()) or 1
    hist = [h for h in (old_history or []) if h.get("date") != today]
    for b in sorted({p["brand"] for p in prods}):
        n = sum(v for k, v in allc.items() if k.casefold() == b.casefold() or k.casefold().startswith(b.casefold() + " "))
        hist.append({"date": today, "brand": b, "units": bu.get(b, 0), "sov": round(n / tot, 4)})
    mode = results[0].get("mode", "keywords") if results else "keywords"
    meta = {"scraped_at": now.isoformat(timespec="seconds"), "marketplace": "amazon.in", "top_n": top_n, "mode": mode}
    if mode == "links":
        meta["scope_note"] = ("Market share is calculated only among the {} product(s) you provided. "
                              "Other brands in the keyword scan are used only as the SOV denominator.").format(len(prods))
    return {"meta": meta,
            "products": prods, "keywords": kws, "history": hist}


def write_modern(results, args):
    if not any(r["products"] for r in results):
        return False
    old = []
    try:
        old = json.loads(Path(args.data).read_text(encoding="utf-8")).get("history", [])
    except Exception:
        pass
    data = build_data(results, old)
    Path(args.data).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tpl = Path(args.template)
    if not tpl.exists():
        tpl = Path(__file__).with_name(args.template)
    if not tpl.exists():
        print("[!] {} not found: only data.json was written".format(args.template), file=sys.stderr)
        return False
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028")
    page = re.sub(r'(<script id="data-inline" type="application/json">)(.*?)(</script>)',
                  lambda m: m.group(1) + blob + m.group(3), tpl.read_text(encoding="utf-8"), count=1, flags=re.S)
    Path(args.out).write_text(page, encoding="utf-8")
    return True


def parse_kw_arg(val):
    """--keywords: a file (.xlsx/.csv) or a comma-separated list."""
    if not val:
        return []
    if val.lower().endswith((".xlsx", ".xlsm", ".csv")) and Path(val).exists():
        return read_keywords(val)
    return [k.strip() for k in val.split(",") if k.strip()]


def dedupe(items):
    seen = set()
    return [k for k in items if not (k.casefold() in seen or seen.add(k.casefold()))]


def save_outputs(results, args):
    if args.classic_ui or not write_modern(results, args):
        Path(args.out).write_text(build_html(results), encoding="utf-8")
    write_excel(results, args.xlsx)
    print("[+] Saved: {}, {}, {}".format(args.out, args.data, args.xlsx), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Amazon.in market share + SOV (from keywords or product links)")
    ap.add_argument("inputs", nargs="*", help="keywords.xlsx / .csv / literal keywords  OR  products.txt (product links)")
    ap.add_argument("--products", help="products.txt: one Amazon.in product link per line (link mode)")
    ap.add_argument("--keywords", help="link mode: keywords for the SOV scan, a file or comma-separated list (auto-derived from titles if omitted)")
    ap.add_argument("--top", type=int, default=10, help="number of top products per keyword (default 10)")
    ap.add_argument("--pages", type=int, default=2, help="search result pages to scan per keyword (default 2)")
    ap.add_argument("--brands", default="", help="comma-separated brand list (helps with multi-word brand names)")
    ap.add_argument("--include-ads", action="store_true", help="also count sponsored listings in the top N")
    ap.add_argument("--browser", action="store_true", help="fetch pages with Playwright (browser)")
    ap.add_argument("--no-cache", action="store_true", help="ignore the 12h product cache")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--data", default="data.json", help="dashboard JSON data (history accumulates here)")
    ap.add_argument("--template", default="dashboard_template.html")
    ap.add_argument("--classic-ui", action="store_true", help="legacy single-file dashboard")
    ap.add_argument("--xlsx", default="report.xlsx")
    ap.add_argument("--no-open", action="store_true", help="do not open the dashboard in the browser")
    args = ap.parse_args(argv)

    link_files, keywords = ([args.products] if args.products else []), []
    for item in args.inputs:
        low = item.lower()
        if low.endswith(".txt"):
            if not Path(item).exists():
                sys.exit("File not found: {}".format(item))
            link_files.append(item)
        elif low.endswith((".xlsx", ".xlsm", ".csv")) and Path(item).exists():
            keywords += read_keywords(item)
        else:
            keywords.append(item)
    known = [b.strip() for b in args.brands.split(",") if b.strip()]

    if link_files:  # ---- MODE B: links ----
        asins, invalid = [], []
        for lf in link_files:
            if not Path(lf).exists():
                sys.exit("File not found: {}".format(lf))
            a, bad = read_links(lf)
            asins += a
            invalid += bad
        asins = list(dict.fromkeys(asins))
        if not asins:
            sys.exit("No valid Amazon.in product link found in the products file.")
        kw_list = dedupe(parse_kw_arg(args.keywords) + keywords)
        print("MODE B (links): {} product(s){}".format(len(asins), ", {} invalid line(s)".format(len(invalid)) if invalid else ""), file=sys.stderr)
        results, failed, _ = process_links(asins, kw_list, args, known)
        if not results:
            sys.exit("No results produced (product fetch failed or no keywords). If you hit a CAPTCHA, retry with --browser.")
        save_outputs(results, args)
        summary(results, failed)
    else:  # ---- MODE A: keywords ----
        keywords = dedupe(keywords + parse_kw_arg(args.keywords))
        if not keywords:
            sys.exit("No keyword or product link provided. Example: python app.py keywords.xlsx  |  python app.py products.txt")
        print("MODE A (keywords): {} keyword(s): {}".format(len(keywords), ", ".join(keywords)), file=sys.stderr)
        results = []
        for kw in keywords:
            results.append(process_keyword(kw, args, known))
            save_outputs(results, args)
        summary(results, [])

    if not args.no_open:
        webbrowser.open(Path(args.out).resolve().as_uri())


if __name__ == "__main__":
    main()
