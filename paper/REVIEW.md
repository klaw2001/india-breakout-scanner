# Runbook: daily paper-trading review (Claude scheduled task, ~16:12 IST, Mon–Fri)

The VPS closes the paper day at 15:45 IST and pushes `paper/days/<date>.json` (trades, skipped
breakouts, what-if outcomes). This run turns that into a short review and a dashboard. Keep it lean:
no code exploration, no installs (the review script is standard-library Python).

## 1. Get the data
```bash
cd <repo> && git pull -q
python3 -m paper.review          # prints the digest, writes paper/dashboard.html
```
- Output contains `NO_DAY_FILE` or `DAY_NOT_CLOSED` → the server did not report today's close.
  Check `data/intraday/status.json`: if today was an NSE holiday nothing is wrong, so stop silently.
  Otherwise send one message (SendUserMessage): "The paper trader didn't report today's close.
  On the VPS run: `tail -50 ~/paper-logs/$(TZ=IST-5:30 date +%F).log`" and stop.
- Digest says "No NSE session today" → send nothing and stop.

## 2. Write the review (SendUserMessage, at most ~180 words)
- **Headline:** net P&L after charges, number of trades, total R, equity.
- **2–4 observations, each tied to a number in the digest.** For example: which exits drove the day
  (targets, stops or square-offs); whether the filters helped or hurt today, using the skipped-breakout
  what-if table ("the volume filter skipped 9 signals that would have made +3.2R"); the best missed
  trade and worst avoided one; across-day patterns only once there are 5+ trading days.
- **Rule suggestions only with enough evidence:** at least 10 trading days and 30 trades, or at least
  20 skipped signals for a filter. Name the knob in `paper/config.py`, the current and proposed value,
  and the numbers behind it. Never edit `config.py`; the user decides.
- Plain language, no hype, no predictions. It is paper trading, not advice.

## 3. Send the dashboard
SendUserFile `paper/dashboard.html` with `display: render`, `status: proactive`, caption
"Paper trading dashboard, <date>".

## 4. Save
Write the review text to `paper/reviews/<YYYY-MM-DD>.md`, then:
```bash
git add paper/dashboard.html paper/reviews
git commit -q -m "paper review: $(date +%F)"
git pull --rebase -q && git push -q
```
