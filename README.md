# India breakout scanner

Three daily breakout scans for NSE, delivered as PDFs in the layout of the original "India Daily Breakout Scan".

| Scan | Universe | Timeframe | Data job (GitHub Action) | PDF (Claude scheduled task) |
|---|---|---|---|---|
| Intraday | F&O stocks + Nifty, Bank Nifty, Fin Nifty | daily levels, ATR trade plan, 15-min volume trigger, overnight US markets | 02:43 IST Mon–Fri | ~04:10 IST Mon–Fri |
| Swing | Nifty 500 + sector indices | daily | 18:47 IST Mon–Fri | ~19:40 IST Mon–Fri |
| Long term | all NSE stocks trading ₹5 Cr+ a day | weekly | 18:47 IST Fri | ~09:40 IST Sat |

**How it works**
1. `.github/workflows/scan.yml` runs `python -m scanner.scan`, which pulls price history from Yahoo Finance and the
   official NSE bhavcopy (closes, volume, delivery %), computes levels and writes `data/<scan>/latest.json`.
2. A Claude scheduled task follows `RUNBOOK.md`: checks freshness, looks up missing quarterly results
   (cached in `data/results_cache.json`), renders the PDF with `python -m report.render`, sends it and commits it to `reports/`.

**Tuning:** every threshold (bands, lookbacks, volume multiple, R-multiple, turnover cut-off) is in `scanner/config.py`.

**Run by hand:** Actions tab → "Breakout data" → Run workflow (choose scans), or locally:
```bash
pip install -r requirements-scan.txt -r requirements-report.txt
python -m scanner.scan --scans swing && python -m report.render --scan swing
```
Scanner output, not investment advice.
