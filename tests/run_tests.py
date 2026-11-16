"""End-to-end tests for both modes on a fake Amazon. Run:  python tests/run_tests.py"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
from fakes import ROOT, app, item, search_page  # noqa: E402
import openpyxl  # noqa: E402

KEYS = ["meta", "products", "keywords", "history"]
PKEYS = {"asin", "brand", "title", "image", "price", "mrp", "rating", "review_count", "bought_text", "units", "bsr"}
approx = lambda a, b, t=0.011: abs(a - b) <= t


def workdir():
    d = Path(tempfile.mkdtemp(prefix="ami_"))
    shutil.copy(ROOT / "dashboard_template.html", d / "dashboard_template.html")
    os.chdir(d)
    return d


def check_schema(data):
    assert list(data) == KEYS or set(data) == set(KEYS), data.keys()
    assert {"scraped_at", "marketplace", "top_n"} <= set(data["meta"])
    for p in data["products"]:
        assert set(p) == PKEYS, set(p) ^ PKEYS
    for k in data["keywords"]:
        for l in k["listings"]:
            assert set(l) == {"position", "asin", "brand", "sponsored"}


def run(argv):
    app.main(argv + ["--no-open", "--no-cache"])


# ------------------------------------------------------------------ MODE A
def test_keyword_mode():
    d = workdir()
    brands = ["Prestige", "Butterfly", "Philips", "Bajaj", "Pigeon by Stovekraft", "Havells", "Longway", "Inalsa",
              "Prestige", "Butterfly", "Bajaj", "Philips", "Wonderchef", "Lifelong"]
    items, prods, n = [], {}, 0
    for i, b in enumerate(brands):
        n += 1
        asin = "ORG%07d" % n
        items.append(item(asin, "%s Mixer Grinder model %d" % (b, n)))
        prods[asin] = dict(title="%s Mixer Grinder model %d" % (b, n), byline=b.split(" by ")[0], price=1000 + 100 * n,
                           mrp=3000, bought=["1K+", "2K+", "5K+", "10K+", "500+", None][n % 6], bsr=100 + n)
        if i in (1, 4, 6):
            n += 1
            items.append(item("ADS%07d" % n, "%s Sponsored Mixer %d" % (brands[(i + 3) % len(brands)], n), ad=True))
    calls = fakes.install(search_page(items), prods, fail={"ORG0000004"})
    wb = openpyxl.Workbook(); ws = wb.active
    for r in (["keyword"], ["mixer grinder"], ["  "], ["juicer mixer"], ["Mixer Grinder"]):
        ws.append(r)
    wb.save("keywords.xlsx")
    run(["keywords.xlsx", "--brands", "Pigeon by Stovekraft,Prestige"])
    data = json.loads(Path("data.json").read_text(encoding="utf-8"))
    check_schema(data)
    assert [k["keyword"] for k in data["keywords"]] == ["mixer grinder", "juicer mixer"], "duplicate / blank / case-variant keywords were not cleaned"
    assert len(calls["search"]) == 4, calls["search"]          # 2 keywords x 2 pages
    ls = data["keywords"][0]["listings"]
    assert len(ls) == len(items) and sum(l["sponsored"] for l in ls) == 3
    html = Path("dashboard.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="data-inline" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(m.group(1))["products"], "data not embedded"
    wb = openpyxl.load_workbook("report.xlsx")
    assert wb.sheetnames == ["Top Products", "SOV", "Product Details"], wb.sheetnames
    rows = list(wb["Top Products"].iter_rows(values_only=True))
    mg = [r for r in rows[1:] if r[0] == "mixer grinder"]
    assert len(mg) == 10 and all(r[3] == "no" for r in mg), "top 10 must be organic only"
    share = sum(r[14] for r in mg if r[14] is not None)
    assert approx(share, 100, 0.2), share
    print("  keyword mode OK (top 10 organic, unit share sum=%.2f, schema ok)" % share)


# ------------------------------------------------------------------ MODE B
LINK_PRODUCTS = {
    "B08CFJBZRK": dict(title="Prestige Mixer Grinder 750W with 3 Jars", byline="Prestige", price=3000, mrp=5000, bought="10K+", bsr=11),
    "B0GWCRPGDB": dict(title="Longway Mixer Grinder 500W with 2 Jars", byline="Longway", price=2000, mrp=4000, bought="2K+", bsr=22),
    "B01GZSQJPA": dict(title="Pigeon Mixer Grinder 600W with 3 Jars", byline="Pigeon", price=1000, mrp=2000, bought="1K+", bsr=33),
    "B075JJ5NQC": dict(title="Butterfly Mixer Grinder 750W with 3 Jars", byline="Butterfly", price=4000, mrp=6000, bought=None, bsr=44),
}


def link_search():
    return search_page([
        item("B08CFJBZRK", "Prestige Mixer Grinder 750W"),
        item("B075JJ5NQC", "Butterfly Mixer Grinder 750W"),
        item("ADSPIGEON1", "Pigeon by Stovekraft Mixer Grinder", ad=True),
        item("B0GWCRPGDB", "Longway Mixer Grinder 500W"),
        item("ORGBAJAJ01", "Bajaj Mixer Grinder 500W"),
        item("ORGPREST02", "Prestige Iris Mixer Grinder"),
        item("ADSPREST03", "Prestige Sponsored Mixer", ad=True),
        item("ORGHAVEL01", "Havells Mixer Grinder"),
        item("B01GZSQJPA", "Pigeon by Stovekraft Mixer Grinder 600W"),
        item("ORGBAJAJ02", "Bajaj Mixer Grinder 750W"),
    ])


def write_links():
    Path("products.txt").write_text("﻿" + "\n".join([
        "# my products", "",
        "https://www.amazon.in/Prestige-IRIS-mixer-grinder-Black/dp/B08CFJBZRK/",
        "https://www.amazon.in/dp/B0GWCRPGDB?ref=sr_1_3&th=1",
        "  https://www.amazon.in/gp/product/B01GZSQJPA  ",
        "https://www.amazon.in/Butterfly-Jet-Elite-750-Watt/dp/B075JJ5NQC/ref=xyz",
        "https://www.amazon.in/dp/B08CFJBZRK",           # duplicate
        "this is not a link",                              # invalid
        "https://www.amazon.in/dp/B0FAILFAIL",             # fetch fails
    ]), encoding="utf-8")


def sov_of(data, brand):
    b = brand.casefold()
    ls = [l for k in data["keywords"] for l in k["listings"]]
    mine = [l for l in ls if l["brand"].casefold() == b or l["brand"].casefold().startswith(b + " ")]
    ads, org = [l for l in ls if l["sponsored"]], [l for l in ls if not l["sponsored"]]
    return (len(mine) / len(ls) * 100, sum(l["sponsored"] for l in mine) / len(ads) * 100,
            sum(not l["sponsored"] for l in mine) / len(org) * 100)


def test_link_mode(explicit_kw):
    d = workdir()
    calls = fakes.install(link_search(), LINK_PRODUCTS, fail={"B0FAILFAIL"})
    write_links()
    argv = ["products.txt"] + (["--keywords", "mixer grinder"] if explicit_kw else [])
    run(argv)
    data = json.loads(Path("data.json").read_text(encoding="utf-8"))
    check_schema(data)
    asins = {p["asin"] for p in data["products"]}
    assert asins == set(LINK_PRODUCTS), asins                      # dup removed, failed + invalid skipped
    assert calls["product"].count("B08CFJBZRK") == 1, "duplicate link fetched twice"
    kws = [k["keyword"] for k in data["keywords"]]
    if explicit_kw:
        assert kws == ["mixer grinder"], kws
    else:
        assert kws == ["mixer grinders"], kws                      # auto-derived & de-pluralised
    # market share (Butterfly has no badge -> NIL, excluded)
    units = {p["brand"]: p["units"] for p in data["products"]}
    assert units == {"Prestige": 10000, "Longway": 2000, "Pigeon": 1000, "Butterfly": None}, units
    tot = 13000
    assert approx(units["Prestige"] / tot * 100, 76.92) and approx(units["Pigeon"] / tot * 100, 7.69)
    rev = {p["brand"]: p["units"] * p["price"] for p in data["products"] if p["units"]}
    assert approx(rev["Prestige"] / sum(rev.values()) * 100, 85.71)
    # SOV (hand computed on the fake page: 10 listings, 2 ads, 8 organic)
    exp = {"Prestige": (30, 50, 25), "Butterfly": (10, 0, 12.5), "Longway": (10, 0, 12.5), "Pigeon": (20, 50, 12.5)}
    for b, e in exp.items():
        got = sov_of(data, b)
        assert all(approx(x, y) for x, y in zip(got, e)), (b, got, e)
    html = Path("dashboard.html").read_text(encoding="utf-8")
    assert '"B08CFJBZRK"' in re.search(r'<script id="data-inline"[^>]*>(.*?)</script>', html, re.S).group(1)
    wb = openpyxl.load_workbook("report.xlsx")
    assert wb.sheetnames == ["Market Share", "Brand SOV", "SOV", "Product Details"], wb.sheetnames
    # --- scope: market share only among the 4 provided products
    ms = list(wb["Market Share"].iter_rows(values_only=True))
    hdr, body = ms[0], ms[1:]
    col = {h: i for i, h in enumerate(hdr)}
    prod_rows = [r for r in body if r[0] in LINK_PRODUCTS]
    assert len(prod_rows) == 4 and not any(r[0] and r[0] not in LINK_PRODUCTS and r[0] != "TOTAL" and str(r[0]).startswith(("ORG", "ADS")) for r in body)
    by = {r[col["asin"]]: r for r in prod_rows}
    assert approx(by["B08CFJBZRK"][col["unit_share_%"]], 76.92) and approx(by["B0GWCRPGDB"][col["unit_share_%"]], 15.38)
    assert approx(by["B08CFJBZRK"][col["revenue_share_%"]], 85.71)
    assert by["B075JJ5NQC"][col["unit_share_%"]] == "NIL" and by["B075JJ5NQC"][col["est_units_30d"]] == "NIL"
    assert approx(sum(r[col["unit_share_%"]] for r in prod_rows if r[col["unit_share_%"]] != "NIL"), 100, 0.05)
    total = [r for r in body if r[0] == "TOTAL"][0]
    assert total[col["est_units_30d"]] == 13000, total
    # product-level SOV (by ASIN): B08CFJBZRK holds 1 of 10 listings, organic 1 of 8, best organic position 1
    assert approx(by["B08CFJBZRK"][col["product_sov_%"]], 10) and approx(by["B08CFJBZRK"][col["product_organic_sov_%"]], 12.5)
    assert by["B08CFJBZRK"][col["best_organic_position"]] == 1
    sov_rows = list(wb["SOV"].iter_rows(values_only=True))[1:]
    names = {r[1] for r in sov_rows}
    assert names == {"Prestige", "Longway", "Pigeon", "Butterfly", "Other brands (all competitors)"} or \
        {n for n in names if n != "Other brands (all competitors)"} <= {"Prestige", "Longway", "Pigeon", "Pigeon by Stovekraft", "Butterfly"}, names
    assert "Bajaj" not in names and "Havells" not in names, "competitors must not appear as separate rows"
    other = [r for r in sov_rows if r[1].startswith("Other brands")][0]
    assert other[2] == 3 and approx(other[5], 30), other                 # Bajaj x2 + Havells = 3 of 10
    assert data["meta"]["mode"] == "links" and "only among the 4" in data["meta"]["scope_note"], data["meta"]
    assert "only among the 4 product" in html
    # history: second run on the same day replaces rows, never duplicates
    n1 = len(data["history"])
    run(argv)
    data2 = json.loads(Path("data.json").read_text(encoding="utf-8"))
    assert len(data2["history"]) == n1, "same-date history duplicated"
    print("  link mode OK (%s keywords): scoped market share + SOV / Ads SOV / Organic SOV match hand-computed values" % ("explicit" if explicit_kw else "auto"))


def test_links_unit():
    from links import extract_asin, read_links
    d = workdir()
    Path("t.txt").write_text("https://amzn.in/d/xyz\nB08CFJBZRK\nhttps://www.amazon.in/gp/aw/d/B0GWCRPGDB?x=1\n", encoding="utf-8")
    got, bad = read_links("t.txt", expand=lambda u: "https://www.amazon.in/dp/B01GZSQJPA")
    assert got == ["B01GZSQJPA", "B08CFJBZRK", "B0GWCRPGDB"] and not bad, got
    assert extract_asin("https://www.amazon.in/x/dp/b08cfjbzrk/ref=a?th=1") == "B08CFJBZRK"
    print("  link parsing OK (short links, bare ASIN, mobile url, tracking params)")


def test_compute_shares_without_price():
    from market_share import compute_shares
    rows = [dict(units_last_month=1000, price=None), dict(units_last_month=3000, price=100), dict(units_last_month=None, price=50)]
    tu, tr = compute_shares(rows)
    assert tu == 4000 and approx(rows[0]["unit_share_%"], 25) and approx(rows[1]["unit_share_%"], 75) and rows[2]["unit_share_%"] is None
    assert rows[0]["revenue_share_%"] is None and approx(rows[1]["revenue_share_%"], 100)
    print("  unit share does not depend on price OK")


def test_no_input_exits():
    workdir()
    try:
        app.main(["--no-open"])
    except SystemExit as e:
        assert e.code not in (0, None)
        print("  empty input exits cleanly OK")
        return
    raise AssertionError("should exit")


if __name__ == "__main__":
    print("MODE A"); test_keyword_mode()
    print("MODE B"); test_links_unit(); test_compute_shares_without_price(); test_link_mode(True); test_link_mode(False); test_no_input_exits()
    print("\nALL TESTS PASSED")
