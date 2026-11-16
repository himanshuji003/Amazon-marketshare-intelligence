"""
Amazon.in product scraper (personal / learning use only).

Install:
    pip install requests beautifulsoup4 lxml
    # optional (if plain requests get blocked):
    pip install playwright && playwright install chromium

Run:
    python amazon_scraper.py "https://www.amazon.in/dp/B0XXXXXXXX"
    python amazon_scraper.py "<url>" --browser        # uses Playwright
    python amazon_scraper.py "<url>" --out data.json  # save to a file
"""

import argparse
import json
import random
import re
import sys
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


def extract_asin(url: str):
    m = re.search(r"/(?:dp|gp/product|product-reviews)/([A-Z0-9]{10})", url)
    return m.group(1) if m else None


def clean_url(url: str):
    asin = extract_asin(url)
    return f"https://www.amazon.in/dp/{asin}" if asin else url


def is_blocked(html: str) -> bool:
    low = html.lower()
    return (
        "captcha" in low
        or "robot check" in low
        or "api-services-support@amazon.com" in low
        or "enter the characters you see below" in low
    )


def fetch_requests(url: str, retries: int = 3):
    session = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            time.sleep(random.uniform(1.5, 3.5))
            r = session.get(url, headers=build_headers(), timeout=20)
            if r.status_code == 200 and not is_blocked(r.text):
                return r.text
            print(f"[!] Attempt {attempt}: status={r.status_code}, blocked={is_blocked(r.text)}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[!] Attempt {attempt}: {e}", file=sys.stderr)
        time.sleep(attempt * 3)
    return None


def fetch_playwright(url: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="en-IN",
            viewport={"width": 1366, "height": 768},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(random.randint(2000, 4000))
        html = page.content()
        browser.close()
    return None if is_blocked(html) else html


def text(soup, selector):
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True) if el else None


def parse_price(s):
    if not s:
        return None
    m = re.sub(r"[^\d.]", "", s.replace(",", ""))
    try:
        return float(m) if m else None
    except ValueError:
        return None


def parse_images(soup, html):
    images = []
    main = soup.select_one("#landingImage, #imgBlkFront")
    if main and main.get("data-a-dynamic-image"):
        try:
            images += list(json.loads(main["data-a-dynamic-image"]).keys())
        except json.JSONDecodeError:
            pass
    hi = re.findall(r'"hiRes":"(https://[^"]+)"', html)
    images += hi
    if main and main.get("src"):
        images.append(main["src"])

    # same image ke multiple sizes me se sirf sabse bada rakho
    best = {}
    order = []
    for u in images:
        m = re.search(r"/I/([^._]+)", u)
        key = m.group(1) if m else u
        s = re.search(r"_S[LXY](\d+)_", u)
        size = int(s.group(1)) if s else 10_000  # no size marker = original
        if key not in best:
            order.append(key)
            best[key] = (size, u)
        elif size > best[key][0]:
            best[key] = (size, u)
    return [best[k][1] for k in order]


def parse_details(soup):
    details = {}
    # table layout (th/td)
    for row in soup.select(
        "#productDetails_techSpec_section_1 tr, #productDetails_techSpec_section_2 tr, "
        "#productDetails_detailBullets_sections1 tr, #prodDetails table tr"
    ):
        k, v = row.select_one("th"), row.select_one("td")
        if k and v:
            details[k.get_text(" ", strip=True)] = v.get_text(" ", strip=True)
    # "Product overview" block (td/td)
    for row in soup.select("#productOverview_feature_div tr"):
        tds = row.select("td")
        if len(tds) >= 2:
            details[tds[0].get_text(" ", strip=True)] = tds[1].get_text(" ", strip=True)
    # "About this item" style spec rows
    for row in soup.select("#productFactsDesktopExpander .a-fixed-left-grid, #productFactsDesktopExpander .product-facts-detail"):
        cols = row.select("span.a-color-base, span.a-color-secondary, span.a-text-bold")
        vals = row.select("span.a-color-base")
        if len(cols) >= 2:
            details[cols[0].get_text(strip=True)] = cols[-1].get_text(strip=True)
    for li in soup.select("#detailBullets_feature_div li"):
        parts = li.get_text(" ", strip=True).split(":", 1)
        if len(parts) == 2:
            key = re.sub(r"[\u200e\u200f\s]+", " ", parts[0]).strip()
            details[key] = re.sub(r"[\u200e\u200f]", "", parts[1]).strip()
    return details


def parse_product(html: str, url: str):
    soup = BeautifulSoup(html, "lxml")

    price_txt = (
        text(soup, "#corePriceDisplay_desktop_feature_div span.a-price:not(.a-text-price) span.a-offscreen")
        or text(soup, "span.a-price:not(.a-text-price) span.a-offscreen")
        or text(soup, "#priceblock_ourprice")
        or text(soup, "#priceblock_dealprice")
    )
    mrp_txt = text(soup, "span.a-price.a-text-price span.a-offscreen") or text(soup, "#listPrice")
    rating_txt = text(soup, "#acrPopover span.a-icon-alt") or text(soup, "span[data-hook='rating-out-of-text']")
    reviews_txt = text(soup, "#acrCustomerReviewText")

    rating = None
    if rating_txt:
        m = re.search(r"([\d.]+)", rating_txt)
        rating = float(m.group(1)) if m else None

    review_count = None
    if reviews_txt:
        m = re.search(r"([\d,]+)", reviews_txt)
        review_count = int(m.group(1).replace(",", "")) if m else None

    brand = text(soup, "#bylineInfo")
    if brand:
        brand = re.sub(r"^(Visit the |Brand:\s*)|( Store)$", "", brand).strip()

    bullets = [
        unicodedata.normalize("NFKC", li.get_text(" ", strip=True))
        for li in soup.select("#feature-bullets li span.a-list-item")
        if li.get_text(strip=True)
    ]

    price, mrp = parse_price(price_txt), parse_price(mrp_txt)
    discount = text(soup, "span.savingsPercentage")
    if not discount and price and mrp and mrp > price:
        discount = f"-{round((mrp - price) / mrp * 100)}%"

    return {
        "url": url,
        "asin": extract_asin(url),
        "title": text(soup, "#productTitle"),
        "brand": brand,
        "price": price,
        "mrp": mrp,
        "discount": discount,
        "currency": "INR",
        "rating": rating,
        "review_count": review_count,
        "availability": text(soup, "#availability span"),
        "seller": text(soup, "#sellerProfileTriggerId") or text(soup, "#merchant-info"),
        "delivery": text(soup, "#mir-layout-DELIVERY_BLOCK span.a-text-bold"),
        "categories": [a.get_text(strip=True) for a in soup.select("#wayfinding-breadcrumbs_feature_div li a")],
        "bullets": bullets,
        "description": text(soup, "#productDescription"),
        "images": parse_images(soup, html),
        "details": parse_details(soup),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--browser", action="store_true", help="fetch with Playwright")
    ap.add_argument("--out", help="JSON file path")
    args = ap.parse_args()

    url = clean_url(args.url)
    html = fetch_playwright(url) if args.browser else fetch_requests(url)

    if not html and not args.browser:
        print("[*] requests blocked, trying Playwright...", file=sys.stderr)
        try:
            html = fetch_playwright(url)
        except ImportError:
            print("[x] Playwright is not installed: pip install playwright && playwright install chromium", file=sys.stderr)

    if not html:
        print("[x] Page could not be fetched (CAPTCHA / block). Wait a while and retry, or use a proxy.", file=sys.stderr)
        sys.exit(1)

    data = parse_product(html, url)
    output = json.dumps(data, indent=2, ensure_ascii=False)
    print(output)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[+] Saved: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
