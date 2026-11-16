"""
Amazon.in Share of Voice (SOV) calculator - personal / learning use only.

Requires amazon_scraper.py in the same folder.

Run:
    python search_sov.py "mixer grinder"
    python search_sov.py "mixer grinder" "juicer mixer grinder" --pages 3
    python search_sov.py "mixer grinder" --brands "Prestige,Butterfly,Pigeon,Bajaj,Philips"
    python search_sov.py "mixer grinder" --browser     # fetch with Playwright
    python search_sov.py "mixer grinder" --json        # JSON only (for n8n)

Definitions (brand level, based on search-result slots):
    SOV          = brand listings / all listings
    Ads SOV      = brand sponsored listings / all sponsored listings
    Organic SOV  = brand organic listings / all organic listings
    Weighted SOV = position-weighted (weight = 1/position), so higher slots count more

Output: terminal table + sov_<keyword>.csv + sov_<keyword>_listings.csv
"""

import argparse
import csv
import json
import random
import re
import sys
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from amazon_scraper import fetch_playwright, fetch_requests, parse_price


def fetch_page(url, use_browser):
    html = fetch_playwright(url) if use_browser else fetch_requests(url)
    if not html and not use_browser:
        try:
            html = fetch_playwright(url)
        except ImportError:
            pass
    return html


def is_sponsored(item):
    if "AdHolder" in " ".join(item.get("class", [])):
        return True
    if item.select_one(".puis-sponsored-label-text, .s-sponsored-label-info-icon"):
        return True
    for s in item.select("span"):
        if s.get_text(strip=True).lower() == "sponsored":
            return True
    for a in item.select("a[href]"):
        if "/sspa/" in a["href"]:
            return True
    return False


def get_brand(title, known):
    low = title.lower()
    best = None
    for b in known:
        m = re.search(r"(?<![a-z0-9])" + re.escape(b.lower()) + r"(?![a-z0-9])", low)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), b)
    if best:
        return best[1]
    first = re.split(r"[\s|,\-:()]+", title.strip())[0] if title.strip() else ""
    if not first:
        return "Unknown"
    return first.title() if first.islower() else first


def parse_results(html, page, start_pos, known):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    pos = start_pos
    for item in soup.select('div[data-component-type="s-search-result"]'):
        asin = (item.get("data-asin") or "").strip()
        if not asin:
            continue
        h2 = item.select_one("h2")
        title = ""
        if h2:
            title = h2.get("aria-label") or h2.get_text(" ", strip=True)
        if not title:
            continue
        pos += 1
        price_el = item.select_one("span.a-price:not(.a-text-price) span.a-offscreen")
        rows.append({
            "position": pos,
            "page": page,
            "asin": asin,
            "sponsored": is_sponsored(item),
            "brand": get_brand(title, known),
            "title": title[:90],
            "price": parse_price(price_el.get_text(strip=True)) if price_el else None,
        })
    return rows


def scrape_keyword(kw, pages, known, use_browser):
    rows = []
    for p in range(1, pages + 1):
        url = f"https://www.amazon.in/s?k={quote_plus(kw)}&page={p}"
        print(f"[{kw}] page {p}/{pages}", file=sys.stderr)
        html = fetch_page(url, use_browser)
        if not html:
            print(f"[x] Page {p} could not be fetched (block / CAPTCHA), continuing", file=sys.stderr)
        else:
            got = parse_results(html, p, len(rows), known)
            if not got:
                print(f"[!] Page {p} returned no results (end of results or the HTML layout changed)", file=sys.stderr)
            rows += got
        if p < pages:
            time.sleep(random.uniform(4, 8))
    return rows


def analyze(kw, rows):
    ads = [r for r in rows if r["sponsored"]]
    org = [r for r in rows if not r["sponsored"]]
    out = {"keyword": kw, "total": len(rows), "sponsored": len(ads), "organic": len(org),
           "ad_load_%": round(len(ads) / len(rows) * 100, 2) if rows else 0.0,
           "brands": [], "listings": rows}
    if not rows:
        return out
    w_all = sum(1 / r["position"] for r in rows)
    agg = {}
    for r in rows:
        b = agg.setdefault(r["brand"].casefold(), {"brand": r["brand"], "listings": 0, "ads": 0, "organic": 0, "w": 0.0})
        b["listings"] += 1
        b["w"] += 1 / r["position"]
        b["ads" if r["sponsored"] else "organic"] += 1
    for b in agg.values():
        out["brands"].append({
            "brand": b["brand"],
            "listings": b["listings"],
            "ads": b["ads"],
            "organic": b["organic"],
            "sov_%": round(b["listings"] / len(rows) * 100, 2),
            "ads_sov_%": round(b["ads"] / len(ads) * 100, 2) if ads else 0.0,
            "organic_sov_%": round(b["organic"] / len(org) * 100, 2) if org else 0.0,
            "weighted_sov_%": round(b["w"] / w_all * 100, 2),
        })
    out["brands"].sort(key=lambda x: (-x["sov_%"], -x["listings"], x["brand"]))
    return out


def slug(kw):
    return re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_") or "keyword"


def print_report(res, top):
    print("\n" + "=" * 100)
    print(f"Keyword: {res['keyword']}")
    print(f"Listings: {res['total']} | Sponsored: {res['sponsored']} | Organic: {res['organic']} | Ad load: {res['ad_load_%']}%")
    print("-" * 100)
    if not res["brands"]:
        print("[!] No listings found. Possible CAPTCHA / block: retry with --browser.")
        return
    print(f"{'Brand':<20}{'Total':>7}{'Ads':>6}{'Org':>6}{'SOV %':>9}{'Ads SOV %':>11}{'Organic SOV %':>15}{'Weighted %':>12}")
    for b in res["brands"][:top]:
        print(f"{b['brand'][:19]:<20}{b['listings']:>7}{b['ads']:>6}{b['organic']:>6}"
              f"{b['sov_%']:>9}{b['ads_sov_%']:>11}{b['organic_sov_%']:>15}{b['weighted_sov_%']:>12}")
    if len(res["brands"]) > top:
        print(f"... and {len(res['brands']) - top} more brands (full list is in the CSV)")
    if res["sponsored"] == 0:
        print("\n[!] No sponsored listing detected: either this keyword has no ads or Amazon changed its HTML.")
    print("=" * 100)


def save_csv(res):
    s = slug(res["keyword"])
    if res["brands"]:
        with open(f"sov_{s}.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(res["brands"][0].keys()))
            w.writeheader()
            w.writerows(res["brands"])
    if res["listings"]:
        with open(f"sov_{s}_listings.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(res["listings"][0].keys()))
            w.writeheader()
            w.writerows(res["listings"])
    print(f"[+] Saved: sov_{s}.csv, sov_{s}_listings.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--pages", type=int, default=3, help="kitne search pages (default 3)")
    ap.add_argument("--brands", default="", help="comma-separated brand list (helps with multi-word brand names)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--json", action="store_true", help="stdout pe sirf JSON")
    args = ap.parse_args()

    known = [b.strip() for b in args.brands.split(",") if b.strip()]
    results = []
    for i, kw in enumerate(args.keywords):
        results.append(analyze(kw, scrape_keyword(kw, args.pages, known, args.browser)))
        if i < len(args.keywords) - 1:
            time.sleep(random.uniform(4, 8))

    if args.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"keywords": results}, ensure_ascii=False))
        return

    for res in results:
        print_report(res, args.top)
        save_csv(res)


if __name__ == "__main__":
    main()
