# Runbook: scheduled Claude run

Each scheduled task passes one scan name: `intraday`, `swing` or `longterm`. Call it SCAN below.
The price data is produced by the GitHub Action (`.github/workflows/scan.yml`); this run adds
quarterly-result verdicts, renders the PDF and delivers it. Keep the run lean: no extra
exploration, no re-reading of code unless a step fails.

## 1. Set up
```bash
cd <repo> && git pull -q
pip install --break-system-packages -q -r requirements-report.txt
```

## 2. Check the data is fresh
```bash
python -m report.status --scan SCAN
```
- `fresh` → continue.
- `stale`, `failed` or `missing` → start the data job and wait for it:
  ```bash
  gh workflow run scan.yml -R klaw2001/india-breakout-scanner -f scans=SCAN
  # poll every 60 s, at most 30 min, until the newest run is completed:
  gh run list -R klaw2001/india-breakout-scanner --workflow scan.yml -L 1 --json status,conclusion,createdAt
  git pull -q && python -m report.status --scan SCAN
  ```
  If still not `fresh`, send the user one short message (SendUserMessage) with the status
  `message` and a link to https://github.com/klaw2001/india-breakout-scanner/actions, then stop.
- `holiday` → send one line ("No NSE session on <expected_session>, so no new SCAN scan") and stop.

## 3. Fill missing quarterly results (max 15 lookups per run)
```bash
python -m report.results todo --scan SCAN --limit 15
```
For each item, run one WebSearch (standard mode), e.g.
`<name> <expected_quarter> results consolidated net profit revenue YoY`.
Prefer company filings, exchange announcements, Moneycontrol, Economic Times, Business Standard, Livemint.
Use consolidated figures; for banks, revenue may be total income or NII (say which).
Verdict rule: **Good** = PAT up 15% or more YoY, or back to profit. **Bad** = PAT down YoY, a loss,
or a wider loss. **In-line** = anything between. Save each one:
```bash
python -m report.results set SYMBOL --quarter "Q2 FY27" --verdict Good \
  --text "Rev ₹347 Cr +24%, PAT ₹68 Cr +26% YoY"
```
Text style: under 110 characters, ₹ and Cr, signed % changes, "YoY" at the end.
If the search does not show that quarter's numbers, save `--verdict NA --text "result not found"`
(it is retried after 14 days). Never guess numbers.

## 4. Render and check
```bash
python -m report.render --scan SCAN          # prints the PDF path
pdfinfo <path> | grep Pages
python -m report.status --scan SCAN --summary
```

## 5. Deliver
SendUserFile with the PDF, `status: proactive`, and the `--summary` line as the caption.

## 6. Save
```bash
git add data/results_cache.json reports/
git commit -q -m "report: SCAN $(date +%F)"
git pull --rebase -q && git push -q
```

If any step errors, fix only what blocks delivery; if delivery is impossible, send the user one
message saying what failed.
