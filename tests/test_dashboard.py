"""Browser check of dashboard_template.html (needs playwright + chromium).
Usage: python tests/test_dashboard.py [data.json ...]   (no args = built-in stress data)"""
import json
import random
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def stress():
    random.seed(7)
    names = ["BOAT", "boAt", "JBL", "Noise", "OnePlus", "Mivi", "Realme", "Sony", "Oppo", "Samsung", "Boult", "Ptron", "Zebronics",
             "Skullcandy", "Pigeon", "Pigeon by Stovekraft"] + ["Brand%d" % i for i in range(12)]
    prods = []
    for i in range(30):
        b = names[i % len(names)]
        prods.append({"asin": "B0STRESS%02d" % i, "brand": b, "title": "%s wireless earbuds %d" % (b, i),
                      "image": None if i % 3 else "https://invalid.example/x.jpg",
                      "price": None if i % 7 == 0 else 500 + i * 90, "mrp": None, "rating": None if i % 5 == 0 else 4.1,
                      "review_count": None if i % 5 == 0 else 100 * i, "bought_text": None,
                      "units_last_month": None if i % 4 == 0 else 1000 * (i % 6 + 1), "bsr": None if i % 6 == 0 else i * 10})
    kws = []
    for k in ("earbuds", "wireless earbuds under 1000", "bluetooth earbuds with mic", "tws"):
        ls = [{"position": j + 1, "asin": "X%d" % j if j % 3 else prods[j % 30]["asin"], "brand": random.choice(names),
               "sponsored": j % 5 == 0} for j in range(25)]
        kws.append({"keyword": k, "listings": ls})
    return {"meta": {"scraped_at": "2026-11-15T10:00:00+05:30", "marketplace": "amazon.in", "top_n": 25},
            "products": prods, "keywords": kws, "history": []}


def main(files):
    tmp = Path(tempfile.mkdtemp())
    if not files:
        (tmp / "stress.json").write_text(json.dumps(stress()), encoding="utf-8")
        files = [str(tmp / "stress.json")]
    bad = 0
    with sync_playwright() as p:
        br = p.chromium.launch()
        for f in files:
            for w in (390, 768, 1024, 1440):
                for theme in ("light", "dark"):
                    pg = br.new_page(viewport={"width": w, "height": 900})
                    errs = []
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.goto((ROOT / "dashboard_template.html").as_uri())
                    pg.set_input_files("#fileIn", f)
                    pg.evaluate("t => setTheme(t)", theme)
                    pg.wait_for_timeout(300)
                    r = pg.evaluate("""() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
                        txt: (document.body.innerText.match(/\\bnull\\b|undefined|NaN|Infinity/g) || []).length,
                        kpi: document.querySelectorAll('.kpi-card').length,
                        hm: (()=>{const h=document.querySelector('.hm-wrap');return h?h.scrollWidth>=h.clientWidth:true})()})""")
                    ok = not errs and r["sw"] <= r["cw"] and r["txt"] == 0 and r["kpi"] == 4
                    bad += not ok
                    print("%s %s %-5s %s" % ("OK " if ok else "BAD", Path(f).name, "%d/%s" % (w, theme), "" if ok else (errs, r)))
                    pg.close()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
