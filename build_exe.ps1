# Builds AmazonMarketIntel.exe (Windows PowerShell):  .\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) { uv pip install pyinstaller -r requirements.txt }
else { python -m pip install pyinstaller -r requirements.txt }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AmazonMarketIntel `
  --add-data "dashboard_template.html;." `
  --hidden-import app --hidden-import keywords --hidden-import links --hidden-import search_sov `
  --hidden-import amazon_scraper --hidden-import market_share --hidden-import lxml.etree --hidden-import lxml._elementpath `
  gui.py
Write-Host "`nDone -> dist\AmazonMarketIntel.exe (double-click)"
