#!/usr/bin/env bash
# One-time setup on any always-on Linux server (your VPS, Oracle, anything).
# Run from inside the cloned repo:   bash paper/setup_server.sh
# It does NOT change the server's clock or timezone, and only adds one line to *your* crontab.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
need() { command -v "$1" >/dev/null 2>&1; }
echo "Repo: $REPO"

echo "1/5 Python 3.10+, venv, git"
if ! need git || ! python3 -c "import ensurepip" 2>/dev/null; then
  if need apt-get; then sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip git >/dev/null
  elif need dnf; then sudo dnf install -y -q python3 python3-pip git
  elif need yum; then sudo yum install -y -q python3 python3-pip git
  else echo "Install python3 (3.10+), its venv module and git, then run this again."; exit 1; fi
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python $(python3 -V) is too old; 3.10 or newer is needed."; exit 1; }
need crontab || { echo "cron is not installed (e.g. sudo apt-get install -y cron)"; exit 1; }

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 1500 ] && ! swapon --show 2>/dev/null | grep -q . && sudo -n true 2>/dev/null; then
  echo "    ${MEM_MB} MB RAM: adding a 2 GB swapfile so the package install doesn't run out of memory"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap -q /swapfile && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "2/5 Python environment (~/paper-venv)"
python3 -m venv "$HOME/paper-venv"
"$HOME/paper-venv/bin/pip" install -q --upgrade pip
"$HOME/paper-venv/bin/pip" install -q -r "$REPO/requirements-scan.txt"

echo "3/5 Repo settings and Telegram file"
chmod +x "$REPO/paper/run.sh"
git -C "$REPO" config user.name "paper-trader"
git -C "$REPO" config user.email "paper-trader@users.noreply.github.com"
git -C "$REPO" config pull.rebase true
[ -f "$HOME/.paper.env" ] || printf 'TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n' > "$HOME/.paper.env"
chmod 600 "$HOME/.paper.env"

echo "4/5 Cron (every 15 min; the script itself decides what to do in India time)"
( crontab -l 2>/dev/null | grep -v 'paper/run.sh' || true
  echo "*/15 * * * * $REPO/paper/run.sh auto   # India breakout paper trader"
) | crontab -
crontab -l | grep 'paper/run.sh'

echo "5/5 Smoke test"
cd "$REPO" && "$HOME/paper-venv/bin/python" -m paper.engine check || true
git -C "$REPO" push --dry-run -q 2>/dev/null && echo "git push: OK" || echo "git push: FAILED - the deploy key needs write access"
echo "Server clock: $(date '+%F %T %Z')  |  India time: $(TZ=IST-5:30 date '+%F %T')"
echo "Done. Logs go to ~/paper-logs/. Optional Telegram alerts: fill in ~/.paper.env"
