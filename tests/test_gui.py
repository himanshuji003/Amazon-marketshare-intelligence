"""GUI smoke test (needs a display; on Linux run under xvfb-run). Fake Amazon, no network."""
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import run_tests as rt  # noqa: E402
import gui  # noqa: E402
import runner  # noqa: E402
runner.SLEEP_SCALE = 0

SHOT = sys.argv[1] if len(sys.argv) > 1 else None
messagebox.askyesno = lambda *a, **k: False
messagebox.showwarning = lambda *a, **k: warns.append(a)
messagebox.showerror = lambda *a, **k: errs.append(a)
warns, errs = [], []
gui.SETTINGS = Path(tempfile.mkdtemp()) / "settings.json"


def pump(root, cond, timeout=60):
    t = time.time()
    while not cond() and time.time() - t < timeout:
        root.update()
        time.sleep(0.02)
    root.update()
    return cond()


def shot(root, path):
    if not path:
        return
    try:
        from PIL import ImageGrab
        root.update()
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    except Exception as e:  # noqa: BLE001
        print("screenshot skipped:", e)


def main():
    fakes.install(rt.link_search(), rt.LINK_PRODUCTS, fail={"B0FAILFAIL"})
    root = tk.Tk()
    app = gui.App(root)
    out = Path(tempfile.mkdtemp())
    app.out_var.set(str(out))
    app.nocache_var.set(True)
    # empty input -> warning, no run
    app.start()
    assert warns and not (app.worker and app.worker.is_alive()), "empty input should warn"
    # paste links + keyword
    app.text.insert("1.0", "https://www.amazon.in/dp/B08CFJBZRK\nhttps://www.amazon.in/dp/B0GWCRPGDB\nhttps://www.amazon.in/dp/B01GZSQJPA\nhttps://www.amazon.in/dp/B075JJ5NQC\nmixer grinder\n")
    root.update()
    assert "Link search" in app.mode_lbl.cget("text"), app.mode_lbl.cget("text")
    app.start()
    assert pump(root, lambda: app.result is not None or errs), errs
    assert not errs, errs
    assert str(app.status.get()).startswith("Completed"), app.status.get()
    assert (out / "dashboard.html").exists() and (out / "report.xlsx").exists() and (out / "data.json").exists()
    assert "Prestige" in app.log_box.get("1.0", "end")
    assert str(app.dash_btn.cget("state")) == "normal" and str(app.start_btn.cget("state")) == "normal"
    shot(root, SHOT)
    # keyword typed -> keyword mode label
    app.text.delete("1.0", "end"); app.text.insert("1.0", "mixer grinder"); root.update()
    assert "Keyword" in app.mode_lbl.cget("text")
    root.destroy()
    print("GUI TEST PASSED")


if __name__ == "__main__":
    main()
