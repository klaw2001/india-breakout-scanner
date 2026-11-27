#!/usr/bin/env bash
# Cron wrapper for the paper trader.
#   usage: paper/run.sh auto | start | run | close
# "auto" is what cron calls every 15 minutes: it works out India time itself, so the server's own
# timezone never matters and is never changed.  Logs: ~/paper-logs/YYYY-MM-DD.log (IST date)
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
[ -f "$HOME/.paper.env" ] && { set -a; . "$HOME/.paper.env"; set +a; }
PY="${PAPER_PY:-$HOME/paper-venv/bin/python}"
export TZ_IST="IST-5:30"                     # POSIX form: works even without tzdata installed
TODAY=$(TZ=$TZ_IST date +%F)
mkdir -p "$HOME/paper-logs"
LOG="$HOME/paper-logs/$TODAY.log"

MODE="${1:-}"
if [ "$MODE" = "auto" ]; then
  HM=$((10#${PAPER_NOW_HM:-$(TZ=$TZ_IST date +%H%M)}))
  DOW=${PAPER_NOW_DOW:-$(TZ=$TZ_IST date +%u)}
  [ "$DOW" -gt 5 ] && exit 0
  if   [ "$HM" -ge 900 ]  && [ "$HM" -lt 915 ];  then MODE=start
  elif [ "$HM" -ge 915 ]  && [ "$HM" -le 1535 ]; then MODE=run
  elif [ "$HM" -ge 1540 ] && [ "$HM" -lt 1700 ]; then
    [ -f "$HOME/paper-logs/.closed-$TODAY" ] && exit 0
    MODE=close
  else
    exit 0
  fi
fi

exec 9>/tmp/paper-trader.lock
flock -w 600 9 || { echo "$(date '+%T') lock busy, skipping $MODE" >>"$LOG"; exit 0; }

push() {
  git add paper/days paper/ledger.csv paper/summary.json 2>/dev/null
  git diff --cached --quiet && return 0
  git commit -q -m "paper: $1 $TODAY"
  for i in 1 2 3 4; do git pull --rebase -q && git push -q && return 0; sleep 8; done
  echo "push failed"
}

{
  echo "=== $(TZ=$TZ_IST date '+%F %T') IST  $MODE"
  case "$MODE" in
    start) git pull --rebase -q || echo "git pull failed (using the copy on disk)"
           "$PY" -m paper.engine start ;;
    run)   sleep "${PAPER_RUN_DELAY:-50}"   # let Yahoo finish the candle that just closed
           "$PY" -m paper.engine run ;;
    close) "$PY" -m paper.engine close && touch "$HOME/paper-logs/.closed-$TODAY"; push close ;;
    *)     echo "usage: run.sh auto|start|run|close" ;;
  esac
} >>"$LOG" 2>&1
