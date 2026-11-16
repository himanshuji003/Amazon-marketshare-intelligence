"""Product-link input (MODE B): products.txt -> list of unique ASINs."""
import re
import sys

import requests

ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product|product-reviews)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)
BARE_ASIN = re.compile(r"^[A-Z0-9]{10}$")
SHORT_HOSTS = ("amzn.in", "amzn.to", "a.co")


def extract_asin(url):
    m = ASIN_RE.search(url)
    return m.group(1).upper() if m else None


def expand_short(url, timeout=15):
    """amzn.in / amzn.to short link -> final amazon.in URL (best effort)."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"})
        return r.url
    except requests.RequestException:
        return url


def read_links(path, expand=expand_short):
    """Return (asins, invalid_lines). Skips blanks and '#' comments, dedupes by ASIN."""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    asins, invalid, seen = [], [], set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        asin = None
        if BARE_ASIN.match(line) and re.search(r"\d", line):
            asin = line.upper()
        else:
            if re.match(r"https?://(www\.)?(%s)/" % "|".join(re.escape(h) for h in SHORT_HOSTS), line, re.I):
                line = expand(line)
            asin = extract_asin(line)
        if not asin:
            invalid.append(raw.strip())
            continue
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
    for bad in invalid:
        print("[!] No ASIN found in this line, skipping: {}".format(bad[:90]), file=sys.stderr)
    return asins, invalid
