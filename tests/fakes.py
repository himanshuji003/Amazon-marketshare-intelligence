"""Fake Amazon: no network needed. Used by run_tests.py."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
time.sleep = lambda x: None  # no delays in tests

import app  # noqa: E402
import search_sov  # noqa: E402


def item(asin, title, ad=False, price=3000):
    cls = "AdHolder s-result-item" if ad else "s-result-item"
    spons = '<span class="puis-label-popover-default"><span>Sponsored</span></span>' if ad else ""
    return ('<div data-component-type="s-search-result" data-asin="%s" class="%s"><h2><span>%s</span></h2>%s'
            '<span class="a-price"><span class="a-offscreen">₹%s</span></span></div>') % (asin, cls, title, spons, format(price, ","))


def search_page(items):
    return "<html><body>" + "".join(items) + "</body></html>"


def product_page(title, byline, price, mrp, bought, bsr, asin, category="Mixer Grinders"):
    badge = "<span>%s bought in past month</span>" % bought if bought else ""
    return """<html><body>
<span id="productTitle"> %s </span><a id="bylineInfo">Visit the %s Store</a>
<div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">₹%s</span></span></div>
<span class="a-price a-text-price"><span class="a-offscreen">₹%s</span></span>
<div id="acrPopover"><span class="a-icon-alt">4.2 out of 5 stars</span></div><span id="acrCustomerReviewText">1,234 ratings</span>
<div id="availability"><span>In stock</span></div>
<div id="wayfinding-breadcrumbs_feature_div"><ul><li><a>Home &amp; Kitchen</a></li><li><a>%s</a></li></ul></div>
<img id="landingImage" src="https://m.media-amazon.com/images/I/%s._SX425_.jpg" data-a-dynamic-image='{"https://m.media-amazon.com/images/I/%s._SL1200_.jpg":[1200,1200]}'>
%s
<table id="productDetails_techSpec_section_1"><tr><th>Best Sellers Rank</th><td>#%d in Home &amp; Kitchen</td></tr></table>
</body></html>""" % (title, byline, format(price, ","), format(mrp, ","), category, asin, asin, badge, bsr)


def install(search_html, products, fail=()):
    """products: {asin: dict(title, byline, price, mrp, bought, bsr)}; page 2 of search 'fails'."""
    calls = {"search": [], "product": []}

    def fake_fetch_page(url, use_browser):
        calls["search"].append(url)
        return search_html if "page=1" in url else None

    def fake_get_html(url, use_browser):
        asin = url.rstrip("/").rsplit("/", 1)[1]
        calls["product"].append(asin)
        if asin in fail or asin not in products:
            return None
        return product_page(asin=asin, **products[asin])

    search_sov.fetch_page = fake_fetch_page
    app.get_html = fake_get_html
    return calls
