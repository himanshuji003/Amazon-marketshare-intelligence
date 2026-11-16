"""Runner (GUI engine) tests on fake Amazon. Run: python tests/test_runner.py"""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import run_tests as rt  # noqa: E402
import runner  # noqa: E402
runner.SLEEP_SCALE = 0


def opts(out, **kw):
    d = {"file": "", "text": "", "out_dir": str(out), "top": 10, "pages": 2, "brands": "", "browser": False,
         "no_cache": True, "include_ads": False}
    d.update(kw)
    return d


def test_classify():
    links, kws = runner.classify_text("# c\nhttps://www.amazon.in/dp/B08CFJBZRK\n\nmixer grinder, wet grinder\nB0GWCRPGDB\nheadphones\n")
    assert links == ["https://www.amazon.in/dp/B08CFJBZRK", "B0GWCRPGDB"], links
    assert kws == ["mixer grinder", "wet grinder", "headphones"], kws
    assert runner.detect_mode("", "mixer grinder") == "keyword"
    assert runner.detect_mode("x.txt", "") == "link"
    assert runner.detect_mode("", "https://amzn.in/d/abc") == "link"
    assert runner.detect_mode("", "") is None
    for bad in (("", ""), ("nofile.txt", "")):
        try:
            runner.resolve_inputs(bad[0], bad[1], tempfile.mkdtemp())
            raise AssertionError("should fail")
        except ValueError:
            pass
    print("  classify / detect / validation OK")


def test_paste_links_with_keywords():
    out = Path(tempfile.mkdtemp())
    fakes.install(rt.link_search(), rt.LINK_PRODUCTS, fail={"B0FAILFAIL"})
    logs = []
    text = ("https://www.amazon.in/Prestige-IRIS-mixer-grinder-Black/dp/B08CFJBZRK/\nhttps://www.amazon.in/dp/B0GWCRPGDB?ref=x\n"
            "https://www.amazon.in/dp/B01GZSQJPA\nhttps://www.amazon.in/dp/B075JJ5NQC\nhttps://www.amazon.in/dp/B0FAILFAIL\nmixer grinder\n")
    res = runner.run_job(opts(out, text=text), logs.append, threading.Event())
    assert res["mode"] == "link"
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert {p["asin"] for p in data["products"]} == set(rt.LINK_PRODUCTS)
    assert [k["keyword"] for k in data["keywords"]] == ["mixer grinder"]
    for b, e in {"Prestige": (30, 50, 25), "Pigeon": (20, 50, 12.5)}.items():
        assert all(rt.approx(x, y) for x, y in zip(rt.sov_of(data, b), e)), b
    assert (out / "dashboard.html").exists() and (out / "report.xlsx").exists()
    assert any((out / "runs").glob("*/dashboard.html")), "timestamped copy missing"
    assert any("SUMMARY" in l for l in logs) and any("Prestige" in l for l in logs), "log lines missing"
    print("  paste links + keyword -> link mode, numbers match, runs/ copy, log OK")


def test_keyword_file_run():
    out = Path(tempfile.mkdtemp())
    fakes.install(rt.link_search(), rt.LINK_PRODUCTS)
    import openpyxl
    f = out / "kw.xlsx"
    wb = openpyxl.Workbook(); wb.active.append(["keyword"]); wb.active.append(["mixer grinder"]); wb.save(f)
    res = runner.run_job(opts(out, file=str(f)), lambda l: None, threading.Event())
    assert res["mode"] == "keyword" and (out / "report.xlsx").exists()
    print("  keyword file run OK")


def test_error_and_cancel():
    out = Path(tempfile.mkdtemp())
    fakes.install(rt.link_search(), {}, fail=set())      # every product fetch fails
    try:
        runner.run_job(opts(out, text="https://www.amazon.in/dp/B08CFJBZRK"), lambda l: None, threading.Event())
        raise AssertionError("should fail")
    except RuntimeError as e:
        assert "result" in str(e).lower() or "fail" in str(e).lower(), e
    fakes.install(rt.link_search(), rt.LINK_PRODUCTS)
    ev = threading.Event()
    calls = []
    orig = fakes.app.get_html

    def stopping(url, b):
        calls.append(url)
        ev.set()                                         # user presses Stop during first fetch
        return orig(url, b)
    fakes.app.get_html = stopping
    try:
        runner.run_job(opts(out, text="https://www.amazon.in/dp/B08CFJBZRK\nhttps://www.amazon.in/dp/B0GWCRPGDB"), lambda l: None, ev)
        raise AssertionError("should cancel")
    except runner.Cancelled:
        assert len(calls) == 1, calls
    import time
    assert time.sleep.__name__ != "cancellable_sleep", "time.sleep not restored"
    print("  failure message + Stop (cancel) + sleep restored OK")


if __name__ == "__main__":
    test_classify(); test_paste_links_with_keywords(); test_keyword_file_run(); test_error_and_cancel()
    print("RUNNER TESTS PASSED")
