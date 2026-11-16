"""
Market share calculator (Amazon.in) - personal / learning use only.

Requires amazon_scraper.py in the same folder.

Run:
    python market_share.py "<url1>" "<url2>" "<url3>" "<url4>"
    python market_share.py --file urls.txt          # one link per line
    python market_share.py --file urls.txt --browser

Output: terminal table + market_share.csv
"""

import argparse
import csv
import json
import random
import re
import sys
import time
from collections import defaultdict

from bs4 import BeautifulSoup

from amazon_scraper import clean_url, fetch_playwright, fetch_requests, parse_product


def get_html(url, use_browser):
    html = fetch_playwright(url) if use_browser else fetch_requests(url)
    if not html and not use_browser:
        try:
            html = fetch_playwright(url)
        except ImportError:
            pass
    return html


def parse_bought(html):
    """'10K+ bought in past month' -> (10000, '10K+ bought in past month')"""
    page_text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    m = re.search(r"([\d,.]+)\s*([KkMm]?)\+?\s*bought in past month", page_text)
    if not m:
        return None, None
    num = float(m.group(1).replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(num * mult), m.group(0)


def get_bsr(details):
    raw = details.get("Best Sellers Rank")
    if not raw:
        return None
    m = re.search(r"#([\d,]+)", raw)
    return int(m.group(1).replace(",", "")) if m else None


def scrape(url, use_browser):
    url = clean_url(url)
    html = get_html(url, use_browser)
    if not html:
        print(f"[x] Fetch fail: {url}", file=sys.stderr)
        return None
    p = parse_product(html, url)
    units, bought_text = parse_bought(html)
    return {
        "asin": p["asin"],
        "brand": p["brand"] or "Unknown",
        "title": (p["title"] or "")[:60],
        "price": p["price"],
        "mrp": p["mrp"],
        "rating": p["rating"],
        "review_count": p["review_count"],
        "bought_text": bought_text,
        "units_last_month": units,
        "bsr": get_bsr(p["details"]),
        "url": url,
    }


def compute_shares(rows):
    """Unit share = units / sum(units) over products that show a 'bought' badge.
    Revenue share = units x price / sum(...) over products that also have a price.
    Products without a badge are NIL (None), never counted as zero."""
    with_units = [r for r in rows if r["units_last_month"]]
    with_rev = [r for r in with_units if r["price"]]
    total_units = sum(r["units_last_month"] for r in with_units)
    for r in rows:
        r["revenue"] = r["units_last_month"] * r["price"] if r in with_rev else None
    total_rev = sum(r["revenue"] for r in with_rev)
    for r in rows:
        r["unit_share_%"] = round(r["units_last_month"] / total_units * 100, 2) if r in with_units else None
        r["revenue_share_%"] = round(r["revenue"] / total_rev * 100, 2) if r in with_rev else None
    return total_units, total_rev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file", help="urls.txt (one link per line)")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--out", default="market_share.csv")
    ap.add_argument("--json", action="store_true", help="JSON only on stdout (for n8n)")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            urls += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not urls:
        ap.error("provide at least one product link")

    rows = []
    for i, u in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {u}", file=sys.stderr)
        r = scrape(u, args.browser)
        if r:
            rows.append(r)
        if i < len(urls):
            time.sleep(random.uniform(4, 8))

    if not rows:
        sys.exit("No product could be fetched.")

    total_units, total_rev = compute_shares(rows)
    rows.sort(key=lambda r: r["units_last_month"] or 0, reverse=True)

    if args.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(
            {"total_units": total_units, "total_revenue": total_rev, "products": rows},
            ensure_ascii=False,
        ))
        return

    print("\n" + "=" * 110)
    print(f"{'Brand':<14}{'Price':>9}{'Rating':>8}{'Reviews':>10}{'Bought/mo':>11}{'Unit %':>9}{'Rev %':>9}  Title")
    print("-" * 110)
    for r in rows:
        print(
            f"{r['brand'][:13]:<14}"
            f"{(r['price'] or 0):>9,.0f}"
            f"{(r['rating'] or 0):>8}"
            f"{(r['review_count'] or 0):>10,}"
            f"{(r['units_last_month'] if r['units_last_month'] is not None else 'N/A'):>11}"
            f"{(r['unit_share_%'] if r['unit_share_%'] is not None else 'N/A'):>9}"
            f"{(r['revenue_share_%'] if r['revenue_share_%'] is not None else 'N/A'):>9}"
            f"  {r['title']}"
        )
    print("=" * 110)
    print(f"Total units (est.): {total_units:,} | Total revenue (est.): Rs {total_rev:,.0f}")

    # brand-wise summary
    brand = defaultdict(lambda: [0, 0.0])
    for r in rows:
        if r["revenue"]:
            brand[r["brand"]][0] += r["units_last_month"]
            brand[r["brand"]][1] += r["revenue"]
    if brand:
        print("\nBrand-wise share:")
        for b, (u, rev) in sorted(brand.items(), key=lambda x: -x[1][1]):
            print(f"  {b:<16} units {u / total_units * 100:6.2f}%   revenue {rev / total_rev * 100:6.2f}%")

    missing = [r["asin"] for r in rows if not r["units_last_month"]]
    if missing:
        print(f"\n[!] No 'bought in past month' badge for these products (NIL, excluded from shares): {missing}")

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n[+] Saved: {args.out}")


if __name__ == "__main__":
    main()
