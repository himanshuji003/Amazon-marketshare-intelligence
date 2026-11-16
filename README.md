# Amazon.in Market Intelligence (personal / learning use only)

Two search modes, one output set: **dashboard.html + data.json + report.xlsx**

| Search | Input | What you get |
|---|---|---|
| 1. Keyword | `keywords.xlsx` / `.csv` / literal keywords | Top 10 organic products per keyword, market share (units / revenue), SOV / Ads SOV / Organic SOV |
| 2. Link | `products.txt` (one Amazon.in link per line) | Market share **only among the products you provided**, plus brand-level and product-level SOV / Ads SOV / Organic SOV |

## Desktop app
```powershell
python gui.py            # or double-click run_app.bat
```
Browse to `keywords.xlsx` / `products.txt`, **or** paste keywords / product links (one per line), then press **Start**. The mode (Keyword / Link) is detected automatically.
- Default output folder: `Documents\AmazonMarketIntel` (`dashboard.html`, `data.json`, `report.xlsx`, a timestamped copy under `runs\`, and `cache\`).
- **Stop** aborts the run. Settings are remembered between launches.
- Keywords pasted together with links are used for the SOV scan.

### Build a standalone .exe (optional, Windows)
```powershell
.\build_exe.ps1          # -> dist\AmazonMarketIntel.exe
```
Antivirus tools occasionally flag PyInstaller executables as false positives. `--browser` (Playwright) is not bundled into the .exe.

## Setup (one time, PowerShell)
```powershell
cd amazon-market-intel
uv pip install -r requirements.txt        # or: python -m pip install -r requirements.txt
# optional, for --browser when you hit a CAPTCHA:
uv pip install playwright ; python -m playwright install chromium
```

## Command line
### Example 1: keyword search
```powershell
python app.py keywords.xlsx
python app.py "mixer grinder" "wet grinder"
python app.py keywords.xlsx --brands "Prestige,Butterfly,Pigeon,Bajaj,Philips"
```
### Example 2: link search
```powershell
python app.py products.txt
python app.py products.txt --keywords keywords.xlsx          # your own keywords for the SOV scan (recommended)
python app.py products.txt --keywords "mixer grinder,juicer mixer grinder"
```
If `--keywords` is omitted, 1-5 generic keywords are derived from the product titles / categories and printed to the console.

Flags: `--top 10` `--pages 2` `--brands "A,B"` `--include-ads` `--browser` `--no-cache` `--out` `--data` `--xlsx` `--template` `--classic-ui` `--no-open`

## Link mode: what is scoped to your products
- **Market share (unit and revenue) is calculated only among the products you provided.** Competitors never enter the market-share denominator.
- Competitor listings from the keyword scan are used only as the **SOV denominator** (SOV is a share of all search slots, so it needs them). In the Excel report they appear as a single `Other brands (all competitors)` row.
- **SOV vs sales gap** in link mode compares like with like: a brand's share of listings among *your* brands minus its unit share.
- Excel sheets: `Market Share` (per product + TOTAL row), `Brand SOV`, `SOV`, `Product Details`.

## Metric definitions
- **Units** = parsed from the "bought in past month" badge: a bucketed lower-bound estimate over a rolling 30 days, not exact sales.
- **NIL** = no badge on the page. Excluded from unit / revenue share (never treated as zero) and listed in the summary.
- **Unit share** = product units / sum of units of the products with a badge. **Revenue share** = units x price / sum of the same, for products that also have a price.
- **SOV** = brand listings / all listings. **Ads SOV** = brand sponsored listings / all sponsored listings. **Organic SOV** = brand organic listings / all organic listings. **Weighted SOV** uses weight 1/position.
- **Product-level SOV** (link mode) counts listings by ASIN instead of by brand.
- **History**: each run appends today's snapshot (same date is replaced). Run on different days to see trends.

## Dashboard
`dashboard.html` embeds its data and opens with a double-click. You can also drag-and-drop any `data.json` onto it.

## Tests (no Amazon access needed, fake pages)
```powershell
python tests/run_tests.py          # both modes, hand-computed numbers, Excel scope checks
python tests/test_runner.py        # app engine: pasted links, Stop, errors
python tests/test_dashboard.py     # dashboard at 4 widths x light / dark (needs playwright)
python tests/test_gui.py           # GUI smoke test (needs a display)
```

## Files
`gui.py` desktop app | `runner.py` app engine | `app.py` CLI + pipelines | `links.py` link parsing | `keywords.py` keyword derivation | `search_sov.py` search scan + SOV | `amazon_scraper.py` product parser | `market_share.py` badge parsing + shares | `dashboard_template.html` UI | `tests/`

## Known limits
- If Amazon changes its HTML the selectors can break. On a CAPTCHA, wait a while or use `--browser`.
- The badge is a bucket estimate (10K+ means more than 10,000), not exact sales.
- In link mode SOV depends on the keywords scanned; auto-derived keywords can be weak, so pass `--keywords` when you can.
- Product cache lives in `cache/` for 12 hours; use `--no-cache` to bypass it.
