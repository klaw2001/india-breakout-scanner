# Paper trader

Trades the intraday breakout watchlist on paper, on 15-minute candle closes, from any always-on Linux server.

```
02:43  GitHub Action builds data/intraday/latest.json (trigger, stop, target, 15m volume trigger)
04:12  Claude sends the intraday PDF
09:00  server: git pull, load watchlist                      run.sh auto -> start
09:15-15:30 every 15 min: process closed candles             run.sh auto -> run
15:45  server: square off leftovers, ledger, summary, push   run.sh auto -> close
```

Rules and sizes live in `paper/config.py`. Each day's full state (watchlist, trades, skipped
breakouts and why) is in `paper/days/<date>.json`; every closed trade is appended to `paper/ledger.csv`;
running totals are in `paper/summary.json`.

## Server setup (once)

Works on any always-on Linux server (your own VPS, Oracle, etc.). It does not change the server's
clock or timezone and adds a single line to your crontab; it works out India time itself.

```bash
# 1. a separate GitHub key just for this repo (leaves any existing ~/.ssh keys alone)
ssh-keygen -t ed25519 -N "" -f ~/.ssh/breakout_deploy -C breakout-paper-trader
cat >> ~/.ssh/config <<'CFG'
Host github-breakout
  HostName github.com
  User git
  IdentityFile ~/.ssh/breakout_deploy
  IdentitiesOnly yes
CFG
cat ~/.ssh/breakout_deploy.pub
```
Add that line at https://github.com/klaw2001/india-breakout-scanner/settings/keys/new
(title "paper-trader", **tick "Allow write access"**). Then:

```bash
ssh -o StrictHostKeyChecking=accept-new -T github-breakout    # "successfully authenticated"
git clone github-breakout:klaw2001/india-breakout-scanner.git ~/india-breakout-scanner
bash ~/india-breakout-scanner/paper/setup_server.sh
```

The script installs a Python environment in `~/paper-venv`, adds the cron line
`*/15 * * * * .../paper/run.sh auto`, and runs a smoke test (data feed, Telegram, git push).

### Telegram alerts (optional)
1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. `nano ~/.paper.env` → fill `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` → `~/paper-venv/bin/python -m paper.engine check`.

### If you use Oracle's free tier instead
Oracle stops "idle" Always Free servers (CPU, network and memory all under 20% for 7 days); upgrading
the account to Pay As You Go prevents that while the Always Free resources stay free.

## Useful commands (on the server)
```bash
tail -f ~/paper-logs/$(date +%F).log           # today's activity
cd ~/india-breakout-scanner && ~/paper-venv/bin/python -m paper.engine check
crontab -l                                     # the schedule (one line)
```
Replay any of the last ~60 sessions without the server: GitHub → Actions → "Paper replay" → Run workflow.
