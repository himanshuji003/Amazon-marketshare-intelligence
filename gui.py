"""Amazon.in Market Intelligence: desktop app (Tkinter). Run: python gui.py"""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import runner

SETTINGS = Path.home() / ".amazon_market_intel.json"
MODE_TEXT = {"keyword": "Mode: Keyword search (top 10 organic products per keyword)",
             "link": "Mode: Link search (market share only among the products you provided)", None: "Mode: -"}


class App:
    def __init__(self, root):
        self.root = root
        root.title("Amazon.in Market Intelligence")
        root.geometry("860x760")
        root.minsize(760, 640)
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.result = None
        cfg = self.load_cfg()

        style = ttk.Style()
        for t in ("vista", "clam"):
            if t in style.theme_names():
                style.theme_use(t)
                break
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#555")
        style.configure("Mode.TLabel", foreground="#1a5fb4", font=("Segoe UI", 10, "bold"))

        pad = {"padx": 12, "pady": 4}
        ttk.Label(root, text="Amazon.in Market Intelligence", style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(root, text="Market share + SOV / Ads SOV / Organic SOV, from keywords or product links", style="Sub.TLabel").pack(anchor="w", padx=12)

        # ---- input
        f = ttk.LabelFrame(root, text="1. Input")
        f.pack(fill="x", **pad)
        row = ttk.Frame(f); row.pack(fill="x", padx=8, pady=(8, 2))
        self.file_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.file_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self.browse_input).pack(side="left", padx=(6, 0))
        ttk.Label(f, text="File: keywords.xlsx / .csv (keyword search)   or   products.txt (one Amazon.in link per line)", style="Sub.TLabel").pack(anchor="w", padx=8)
        ttk.Label(f, text="Or paste here (one keyword or product link per line). Keywords pasted together with links are used for the SOV scan:", style="Sub.TLabel").pack(anchor="w", padx=8, pady=(6, 0))
        self.text = tk.Text(f, height=5, wrap="word", font=("Consolas", 10))
        self.text.pack(fill="x", padx=8, pady=(2, 4))
        self.text.bind("<<Modified>>", self.on_input_change)
        self.mode_lbl = ttk.Label(f, text=MODE_TEXT[None], style="Mode.TLabel")
        self.mode_lbl.pack(anchor="w", padx=8, pady=(0, 6))
        self.file_var.trace_add("write", lambda *a: self.update_mode())

        # ---- options
        o = ttk.LabelFrame(root, text="2. Options")
        o.pack(fill="x", **pad)
        r1 = ttk.Frame(o); r1.pack(fill="x", padx=8, pady=6)
        self.top_var = tk.IntVar(value=cfg.get("top", 10))
        self.pages_var = tk.IntVar(value=cfg.get("pages", 2))
        ttk.Label(r1, text="Top products").pack(side="left")
        ttk.Spinbox(r1, from_=1, to=30, width=4, textvariable=self.top_var).pack(side="left", padx=(4, 14))
        ttk.Label(r1, text="Search pages").pack(side="left")
        ttk.Spinbox(r1, from_=1, to=5, width=4, textvariable=self.pages_var).pack(side="left", padx=(4, 14))
        ttk.Label(r1, text="Brands (optional, comma-separated)").pack(side="left")
        self.brands_var = tk.StringVar(value=cfg.get("brands", ""))
        ttk.Entry(r1, textvariable=self.brands_var, width=30).pack(side="left", padx=4, fill="x", expand=True)
        r2 = ttk.Frame(o); r2.pack(fill="x", padx=8, pady=(0, 6))
        self.browser_var = tk.BooleanVar(value=cfg.get("browser", False))
        self.nocache_var = tk.BooleanVar(value=cfg.get("no_cache", False))
        self.ads_var = tk.BooleanVar(value=cfg.get("include_ads", False))
        ttk.Checkbutton(r2, text="Use browser (Playwright, for CAPTCHA)", variable=self.browser_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(r2, text="Ignore cache (fetch fresh data)", variable=self.nocache_var).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(r2, text="Include sponsored in top N", variable=self.ads_var).pack(side="left")
        r3 = ttk.Frame(o); r3.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(r3, text="Output folder").pack(side="left")
        self.out_var = tk.StringVar(value=cfg.get("out_dir", str(runner.default_output_dir())))
        ttk.Entry(r3, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r3, text="Browse...", command=self.browse_out).pack(side="left")

        # ---- run
        b = ttk.Frame(root); b.pack(fill="x", **pad)
        self.start_btn = ttk.Button(b, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(b, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.dash_btn = ttk.Button(b, text="Open dashboard", command=lambda: self.open("dashboard"), state="disabled")
        self.dash_btn.pack(side="left", padx=(24, 6))
        self.xls_btn = ttk.Button(b, text="Open Excel report", command=lambda: self.open("excel"), state="disabled")
        self.xls_btn.pack(side="left", padx=6)
        self.fold_btn = ttk.Button(b, text="Open output folder", command=lambda: self.open("folder"))
        self.fold_btn.pack(side="left", padx=6)
        self.prog = ttk.Progressbar(root, mode="indeterminate")
        self.prog.pack(fill="x", padx=12)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, style="Sub.TLabel").pack(anchor="w", padx=12, pady=(2, 0))

        lf = ttk.LabelFrame(root, text="Log")
        lf.pack(fill="both", expand=True, **pad)
        self.log_box = scrolledtext.ScrolledText(lf, height=12, state="disabled", font=("Consolas", 9), wrap="none")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---------------- settings
    def load_cfg(self):
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_cfg(self):
        try:
            SETTINGS.write_text(json.dumps({
                "out_dir": self.out_var.get(), "top": self.top_var.get(), "pages": self.pages_var.get(),
                "brands": self.brands_var.get(), "browser": self.browser_var.get(),
                "no_cache": self.nocache_var.get(), "include_ads": self.ads_var.get()}), encoding="utf-8")
        except Exception:
            pass

    # ---------------- input
    def browse_input(self):
        p = filedialog.askopenfilename(title="Select a keywords or product-links file", filetypes=[
            ("Keywords / links", "*.xlsx *.xlsm *.csv *.txt"), ("All files", "*.*")])
        if p:
            self.file_var.set(p)

    def browse_out(self):
        p = filedialog.askdirectory(title="Select the output folder")
        if p:
            self.out_var.set(p)

    def on_input_change(self, _e=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.update_mode()

    def update_mode(self):
        self.mode_lbl.config(text=MODE_TEXT[runner.detect_mode(self.file_var.get().strip(), self.text.get("1.0", "end"))])

    # ---------------- run
    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            opts = {"file": self.file_var.get().strip(), "text": self.text.get("1.0", "end"), "out_dir": self.out_var.get().strip(),
                    "top": self.top_var.get(), "pages": self.pages_var.get(), "brands": self.brands_var.get(),
                    "browser": self.browser_var.get(), "no_cache": self.nocache_var.get(), "include_ads": self.ads_var.get()}
            runner.resolve_inputs(opts["file"], opts["text"], Path(opts["out_dir"]) / "inputs")
        except (ValueError, tk.TclError) as e:
            messagebox.showwarning("Input", str(e))
            return
        if not opts["out_dir"]:
            messagebox.showwarning("Output", "Select an output folder.")
            return
        self.save_cfg()
        self.cancel.clear()
        self.result = None
        self.log_box.config(state="normal"); self.log_box.delete("1.0", "end"); self.log_box.config(state="disabled")
        for bt in (self.dash_btn, self.xls_btn):
            bt.config(state="disabled")
        self.start_btn.config(state="disabled"); self.stop_btn.config(state="normal")
        self.prog.start(12)
        self.status.set("Running... (requests are deliberately throttled to avoid blocks)")
        self.worker = threading.Thread(target=self.work, args=(opts,), daemon=True)
        self.worker.start()

    def work(self, opts):
        try:
            res = runner.run_job(opts, lambda line: self.q.put(("log", line)), self.cancel)
            self.q.put(("done", res))
        except runner.Cancelled:
            self.q.put(("cancelled", None))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def stop(self):
        self.cancel.set()
        self.status.set("Stopping...")
        self.stop_btn.config(state="disabled")

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.append_log(val)
                else:
                    self.finish(kind, val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def append_log(self, line):
        self.log_box.config(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")
        if line.strip():
            self.status.set(line.strip()[:110])

    def finish(self, kind, val):
        self.prog.stop()
        self.start_btn.config(state="normal"); self.stop_btn.config(state="disabled")
        if kind == "done":
            self.result = val
            self.dash_btn.config(state="normal"); self.xls_btn.config(state="normal")
            self.status.set("Completed. Dashboard: {}".format(val["dashboard"]))
            if messagebox.askyesno("Completed", "Done.\n\nOpen the dashboard now?"):
                self.open("dashboard")
        elif kind == "cancelled":
            self.status.set("Stopped. Anything saved before stopping is in the output folder.")
        else:
            self.status.set("Error")
            messagebox.showerror("Error", val)

    def open(self, what):
        try:
            if what == "folder":
                p = Path(self.out_var.get())
                p.mkdir(parents=True, exist_ok=True)
            else:
                p = (self.result or {}).get(what) or Path(self.out_var.get()) / ("dashboard.html" if what == "dashboard" else "report.xlsx")
            runner.open_path(p)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Open", str(e))

    def on_close(self):
        if self.worker and self.worker.is_alive() and not messagebox.askyesno("Exit", "A run is in progress. Exit anyway?"):
            return
        self.cancel.set()
        self.save_cfg()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
