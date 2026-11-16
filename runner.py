"""Engine behind the desktop app (tkinter-free, testable): input resolution, job run, cancel, logging."""
import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


SLEEP_SCALE = 1.0  # tests set this to 0 to skip the anti-block delays


class Cancelled(Exception):
    pass


def resource_dir():
    """Source folder, or the bundle folder inside a PyInstaller .exe."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def default_output_dir():
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "AmazonMarketIntel"


LINK_RE = re.compile(r"(amazon\.[a-z.]+/|amzn\.(in|to)/|a\.co/)", re.I)


def is_link_line(s):
    return bool(LINK_RE.search(s)) or (bool(re.fullmatch(r"[A-Za-z0-9]{10}", s)) and bool(re.search(r"\d", s)) and s.upper() == s)


def classify_text(text):
    """Pasted text -> (links, keywords). Lines: '#' comments/blank ignored; non-link lines split on commas."""
    links, kws = [], []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if is_link_line(s):
            links.append(s)
        else:
            kws += [k.strip() for k in s.split(",") if k.strip()]
    return links, kws


def resolve_inputs(file_path, text, work_dir):
    """Return (argv_inputs, mode) mode = 'link' | 'keyword'. Raises ValueError (user-facing message) on bad input."""
    inputs, link_files, kw_items = [], [], []
    if file_path:
        fp = Path(file_path)
        if not fp.exists():
            raise ValueError("File not found: {}".format(file_path))
        ext = fp.suffix.lower()
        if ext == ".txt":
            link_files.append(str(fp))
        elif ext in (".xlsx", ".xlsm", ".csv"):
            kw_items.append(str(fp))
        else:
            raise ValueError("Unsupported file type. Use .xlsx / .csv (keywords) or .txt (product links).")
    links, kws = classify_text(text)
    if links:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        pf = work_dir / "pasted_links.txt"
        pf.write_text("\n".join(links), encoding="utf-8")
        link_files.append(str(pf))
    kw_items += kws
    if not link_files and not kw_items:
        raise ValueError("Select a file, or paste keywords / product links first.")
    return link_files + kw_items, ("link" if link_files else "keyword")


def detect_mode(file_path, text):
    return _quick_mode(file_path, text)


def _quick_mode(file_path, text):
    links, kws = classify_text(text)
    if (file_path and str(file_path).lower().endswith(".txt")) or links:
        return "link"
    if (file_path and str(file_path).lower().endswith((".xlsx", ".xlsm", ".csv"))) or kws:
        return "keyword"
    return None


class LogWriter:
    def __init__(self, cb):
        self.cb, self.buf = cb, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.cb(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.cb(self.buf)
            self.buf = ""


def open_path(p):
    p = str(p)
    if sys.platform.startswith("win"):
        os.startfile(p)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def run_job(opts, log, cancel):
    """opts: file, text, out_dir, top, pages, brands, browser, no_cache, include_ads.
    log(line) callback, cancel = threading.Event. Returns dict of output paths. Raises RuntimeError / Cancelled."""
    import app  # lazy: GUI fast start

    out = Path(opts["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    inputs, mode = resolve_inputs(opts.get("file"), opts.get("text"), out / "inputs")
    argv = list(inputs) + [
        "--top", str(int(opts.get("top", 10))), "--pages", str(int(opts.get("pages", 2))),
        "--out", str(out / "dashboard.html"), "--data", str(out / "data.json"), "--xlsx", str(out / "report.xlsx"),
        "--template", str(resource_dir() / "dashboard_template.html"), "--no-open",
    ]
    if opts.get("brands", "").strip():
        argv += ["--brands", opts["brands"].strip()]
    for flag, key in (("--browser", "browser"), ("--no-cache", "no_cache"), ("--include-ads", "include_ads")):
        if opts.get(key):
            argv.append(flag)

    real_sleep = time.sleep

    def cancellable_sleep(s):
        if cancel.is_set():
            raise Cancelled()
        end = time.monotonic() + max(0, s * SLEEP_SCALE)
        while True:
            if cancel.is_set():
                raise Cancelled()
            left = end - time.monotonic()
            if left <= 0:
                return
            real_sleep(min(0.2, left))

    old_cache = app.CACHE_DIR
    app.CACHE_DIR = out / "cache"
    time.sleep = cancellable_sleep
    writer = LogWriter(log)
    try:
        with contextlib.redirect_stderr(writer):
            try:
                app.main(argv)
            except SystemExit as e:
                if e.code not in (0, None):
                    raise RuntimeError(str(e.code))
        writer.flush()
    finally:
        time.sleep = real_sleep
        app.CACHE_DIR = old_cache
    if cancel.is_set():
        raise Cancelled()
    run_dir = out / "runs" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.html", "report.xlsx"):
        if (out / name).exists():
            shutil.copy2(out / name, run_dir / name)
    return {"mode": mode, "dashboard": out / "dashboard.html", "excel": out / "report.xlsx",
            "data": out / "data.json", "folder": out, "run_dir": run_dir}
