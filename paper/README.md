# Paper trader

Trades the intraday breakout watchlist on paper, on 15-minute candle closes, from an Oracle Cloud server.

```
02:43  GitHub Action builds data/intraday/latest.json (trigger, stop, target, 15m volume trigger)
04:12  Claude sends the intraday PDF
09:05  server: git pull, load watchlist                      paper/run.sh start
09:30-15:15 every 15 min: process closed candles             paper/run.sh run
15:40  server: square off leftovers, ledger, summary, push   paper/run.sh close
```

Rules and sizes live in `paper/config.py`. Each day's full state (watchlist, trades, skipped
breakouts and why) is in `paper/days/<date>.json`; every closed trade is appended to `paper/ledger.csv`;
running totals are in `paper/summary.json`.

## Server setup (once)

On the Oracle Ubuntu server (`ssh -i <key> ubuntu@<ip>`):

```bash
# 1. a key the server uses to read and push to this repo
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C oracle-paper-trader
cat ~/.ssh/id_ed25519.pub
```
Add that line at https://github.com/klaw2001/india-breakout-scanner/settings/keys/new
(title "oracle", **tick "Allow write access"**). Then:

```bash
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # says "successfully authenticated"
git clone git@github.com:klaw2001/india-breakout-scanner.git
bash india-breakout-scanner/paper/setup_oracle.sh
```

The script sets the clock to IST, installs Python packages, adds three cron entries and runs a smoke test.

### Telegram alerts (optional)
1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. `nano ~/.paper.env` → fill `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` → `~/paper-venv/bin/python -m paper.engine check`.

## Keeping the free server
Oracle stops "idle" Always Free servers (CPU, network and memory all under 20% for 7 days), and this
one is idle most of the day. Upgrading the account to **Pay As You Go** stops that; the Always Free
resources stay free, so stay within 1 OCPU / 6 GB and a single server.

## Useful commands (on the server)
```bash
tail -f ~/paper-logs/$(date +%F).log           # today's activity
cd ~/india-breakout-scanner && ~/paper-venv/bin/python -m paper.engine check
crontab -l                                     # the schedule
```
Replay any of the last ~60 sessions without the server: GitHub → Actions → "Paper replay" → Run workflow.
