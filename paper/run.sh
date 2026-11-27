#!/usr/bin/env bash
# Cron wrapper for the paper trader.   usage: paper/run.sh start|run|close
# Logs: ~/paper-logs/YYYY-MM-DD.log
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
[ -f "$HOME/.paper.env" ] && { set -a; . "$HOME/.paper.env"; set +a; }
PY="$HOME/paper-venv/bin/python"
mkdir -p "$HOME/paper-logs"
LOG="$HOME/paper-logs/$(date +%F).log"

exec 9>/tmp/paper-trader.lock
flock -w 600 9 || { echo "$(date '+%T') lock busy, skipping $1" >>"$LOG"; exit 0; }

push() {
  git add paper/days paper/ledger.csv paper/summary.json 2>/dev/null
  git diff --cached --quiet && return 0
  git commit -q -m "paper: $1 $(date '+%F %H:%M')"
  for i in 1 2 3 4; do git pull --rebase -q && git push -q && return 0; sleep 8; done
  echo "push failed"
}

{
  echo "=== $(date '+%F %T') $1"
  case "${1:-}" in
    start) git pull --rebase -q || echo "git pull failed (using the copy on disk)"
           "$PY" -m paper.engine start ;;
    run)   sleep 50   # let Yahoo finish the candle that just closed
           "$PY" -m paper.engine run ;;
    close) "$PY" -m paper.engine close; push close ;;
    *)     echo "usage: run.sh start|run|close" ;;
  esac
} >>"$LOG" 2>&1
