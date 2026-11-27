#!/usr/bin/env bash
# One-time setup on the Oracle Ubuntu server. Run from inside the cloned repo:
#   bash paper/setup_oracle.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
echo "Repo: $REPO"

echo "1/5 Timezone -> Asia/Kolkata (cron times below are IST)"
sudo timedatectl set-timezone Asia/Kolkata

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 2000 ] && ! swapon --show | grep -q .; then
  echo "    small server (${MEM_MB} MB RAM): adding a 2 GB swapfile so pip installs don't run out of memory"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap -q /swapfile && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "2/5 System packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip git >/dev/null

echo "3/5 Python environment (~/paper-venv)"
python3 -m venv "$HOME/paper-venv"
"$HOME/paper-venv/bin/pip" install -q --upgrade pip
"$HOME/paper-venv/bin/pip" install -q -r "$REPO/requirements-scan.txt"

echo "4/5 Git identity, Telegram settings file, cron"
chmod +x "$REPO/paper/run.sh"
git -C "$REPO" config user.name "paper-trader (oracle)"
git -C "$REPO" config user.email "paper-trader@users.noreply.github.com"
git -C "$REPO" config pull.rebase true
[ -f "$HOME/.paper.env" ] || printf 'TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n' > "$HOME/.paper.env"
chmod 600 "$HOME/.paper.env"
( crontab -l 2>/dev/null | grep -v 'paper/run.sh' || true
  cat <<EOF
# India breakout paper trader (server clock is IST)
5 9 * * 1-5 $REPO/paper/run.sh start
0,15,30,45 9-15 * * 1-5 $REPO/paper/run.sh run
40 15 * * 1-5 $REPO/paper/run.sh close
EOF
) | crontab -
crontab -l | grep run.sh

echo "5/5 Smoke test"
cd "$REPO" && "$HOME/paper-venv/bin/python" -m paper.engine check || true
git -C "$REPO" push --dry-run -q && echo "git push: OK" || echo "git push: FAILED - add the deploy key with write access"
echo "Done. Logs will be in ~/paper-logs/. Optional: put your Telegram bot token and chat id in ~/.paper.env"
