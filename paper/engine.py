"""Paper-trading engine for the intraday breakout watchlist (long breakouts, 15-minute candle closes).

    python -m paper.engine start      # 09:05  load today's watchlist from data/intraday/latest.json
    python -m paper.engine run        # every 15 min  process completed candles (safe to re-run)
    python -m paper.engine close      # 15:40  square off anything left, append ledger, update summary
    python -m paper.engine check      # smoke test on a new server
    python -m paper.engine replay --date 2026-11-26 [--watchlist data/intraday/history/2026-11-25.json]

Rules (see paper/config.py):
  entry  a completed 15-min candle closes above the scan's trigger, on >= the scan's 15-min volume trigger
         (opening candle: 3x the average candle), not more than 0.5 ATR above the trigger, reward >= 1R;
         fill = candle close + slippage; size = RISK_PER_TRADE / (entry - stop), capped by exposure.
  exit   stop if a candle trades at/below it (gap: at the open), target if it trades at/above it,
         stop wins if both happen in one candle; otherwise square off at the close of the 15:15 candle.
"""
import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from scanner import prices
from scanner.scan import IST

from . import config as C
from . import notify

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper"
DAYS = PAPER / "days"
REPLAYS = PAPER / "replays"
LEDGER = PAPER / "ledger.csv"
SUMMARY = PAPER / "summary.json"
WATCHLIST = ROOT / "data" / "intraday" / "latest.json"
LEDGER_COLS = ["date", "symbol", "name", "entry_time", "entry", "qty", "stop", "target", "exit_time",
               "exit", "reason", "gross", "charges", "net", "r"]
CANDLE = pd.Timedelta(minutes=15)


# ---------------------------------------------------------------- helpers
def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def mins(ts) -> int:
    return ts.hour * 60 + ts.minute


def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def inr(x) -> str:
    return f"₹{x:,.2f}"


def charges(buy_val: float, sell_val: float) -> float:
    brk = min(C.BROKERAGE_FLAT, C.BROKERAGE_PCT * buy_val) + min(C.BROKERAGE_FLAT, C.BROKERAGE_PCT * sell_val)
    txn = C.EXCHANGE_TXN * (buy_val + sell_val)
    sebi = C.SEBI_PER_CRORE / 1e7 * (buy_val + sell_val)
    total = brk + C.STT_SELL * sell_val + txn + sebi + C.STAMP_BUY * buy_val + C.GST * (brk + txn + sebi)
    return round(total, 2)


# ---------------------------------------------------------------- watchlist & state
def load_watchlist(path: Path, day: date) -> dict:
    doc = json.loads(Path(path).read_text())
    m = doc["meta"]
    sess = date.fromisoformat(m["session_date"])
    if sess >= day:
        raise SystemExit(f"watchlist is for session {sess}; it must be before {day}")
    if (day - sess).days > 6:
        raise SystemExit(f"watchlist is stale (session {sess}); the 02:43 GitHub job probably failed")
    items = []
    for r in doc["rows"]:
        if r.get("index") or r.get("group") not in C.GROUPS:
            continue
        if not all(r.get(k) for k in ("trigger", "stop", "target")):
            continue
        items.append(dict(symbol=r["symbol"], name=r["name"], ticker=r["ticker"], group=r["group"],
                          trigger=r["trigger"], stop=r["stop"], target=r["target"], atr=r.get("atr"),
                          v15_avg=r.get("v15_avg"), v15_trigger=r.get("v15_trigger"), prev_close=r["close"]))
    return dict(session=str(sess), items=items)


def new_state(day: date, wl: dict) -> dict:
    return dict(date=str(day), watchlist_session=wl["session"], capital=C.CAPITAL,
                rules=dict(risk_per_trade=C.RISK_PER_TRADE, max_open=C.MAX_OPEN, leverage=C.LEVERAGE),
                status="open", processed_until=None, watchlist=wl["items"],
                open={}, closed=[], skipped=[], events=[])


def state_file(day: date, replay=False) -> Path:
    return (REPLAYS if replay else DAYS) / f"{day}.json"


def save(st: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1, default=str))


# ---------------------------------------------------------------- candles
def fetch_candles(tickers, day: date, now=None, period="5d", log=None):
    frames = prices.download(tickers, period=period, interval="15m", batch=50, min_rows=1, log=log)
    out = {}
    for t, df in frames.items():
        d = df[df.index.normalize() == pd.Timestamp(day)]
        mm = d.index.hour * 60 + d.index.minute
        d = d[(mm >= hm("09:15")) & (mm < hm("15:30"))]
        if now is not None:
            d = d[d.index + CANDLE <= pd.Timestamp(now)]
        if len(d):
            out[t] = d
    return out


def bar_at(df, end):
    if df is None:
        return None
    start = end - CANDLE
    if start in df.index:
        return df.loc[start]
    return None


# ---------------------------------------------------------------- trading
def _event(st, ev, text, stamp):
    st["events"].append(dict(time=stamp, text=text))
    ev.append(text)


def _skip(st, w, stamp, reason):
    key = (w["symbol"], reason.split(":")[0])
    if any((s["symbol"], s["reason"].split(":")[0]) == key for s in st["skipped"]):
        return
    st["skipped"].append(dict(symbol=w["symbol"], time=stamp, reason=reason))


def _open(st, w, entry, qty, risk_ps, stamp, ev):
    st["open"][w["symbol"]] = dict(symbol=w["symbol"], name=w["name"], ticker=w["ticker"], entry_time=stamp,
                                   entry=round(entry, 2), qty=qty, stop=w["stop"], target=w["target"],
                                   trigger=w["trigger"], risk_ps=round(risk_ps, 2))
    _event(st, ev, f"🟢 BUY {w['symbol']} {qty} @ {inr(entry)} ({stamp} candle close) | "
                   f"stop {inr(w['stop'])} · target {inr(w['target'])} · risk {inr(risk_ps * qty)}", stamp)


def _close(st, sym, px, stamp, reason, ev):
    p = st["open"].pop(sym)
    px = round(px, 2)
    buy, sell = p["entry"] * p["qty"], px * p["qty"]
    gross = round(sell - buy, 2)
    ch = charges(buy, sell)
    t = dict(p, exit_time=stamp, exit=px, reason=reason, gross=gross, charges=ch, net=round(gross - ch, 2),
             r=round(gross / (p["risk_ps"] * p["qty"]), 2) if p["risk_ps"] else None)
    st["closed"].append(t)
    icon = {"target": "✅", "stop": "🔴"}.get(reason, "⏹")
    _event(st, ev, f"{icon} EXIT {sym} @ {inr(px)} ({reason}, {stamp}) | net {inr(t['net'])} · {t['r']}R", stamp)


def process(st: dict, candles: dict) -> list:
    """Walk every completed candle after processed_until. Idempotent."""
    ev = []
    if st["status"] != "open" or not candles:
        return ev
    wl = {w["ticker"]: w for w in st["watchlist"]}
    # Only walk up to the candle that most tickers already have (Yahoo posts bars a little unevenly).
    last_ends = sorted(df.index[-1] + CANDLE for df in candles.values())
    cutoff = last_ends[int(len(last_ends) * 0.2)] if len(last_ends) > 4 else last_ends[0]
    ends = sorted({ts + CANDLE for df in candles.values() for ts in df.index if ts + CANDLE <= cutoff})
    done = hm(st["processed_until"]) if st["processed_until"] else -1
    sq, first, last = hm(C.SQUARE_OFF), hm(C.FIRST_ENTRY), hm(C.LAST_ENTRY)
    traded = {t["symbol"] for t in st["closed"]} | set(st["open"])

    for end in ends:
        e = mins(end)
        if e <= done or e > sq:
            continue
        stamp = end.strftime("%H:%M")

        # 1) exits for positions opened on earlier candles
        for sym, p in list(st["open"].items()):
            if p["entry_time"] == stamp:
                continue
            b = bar_at(candles.get(p["ticker"]), end)
            if b is None:
                continue
            if b.Low <= p["stop"]:
                _close(st, sym, min(b.Open, p["stop"]) * (1 - C.SLIPPAGE), stamp, "stop", ev)
            elif b.High >= p["target"]:
                _close(st, sym, max(b.Open, p["target"]) * (1 - C.SLIPPAGE), stamp, "target", ev)
            elif e == sq:
                _close(st, sym, b.Close * (1 - C.SLIPPAGE), stamp, "square-off", ev)

        if e == sq:
            for sym, p in list(st["open"].items()):        # no 15:15 bar for this stock: last known close
                df = candles.get(p["ticker"])
                px = float(df[df.index + CANDLE <= end]["Close"].iloc[-1]) if df is not None else p["entry"]
                _close(st, sym, px * (1 - C.SLIPPAGE), stamp, "square-off", ev)
            st["processed_until"], st["status"] = stamp, "closed"
            break

        # 2) entries
        if first <= e <= last:
            cands = []
            for t, w in wl.items():
                if w["symbol"] in traded:
                    continue
                b = bar_at(candles.get(t), end)
                if b is None or b.Close <= w["trigger"]:
                    continue
                c, v = float(b.Close), float(b.Volume)
                reason = None
                if C.REQUIRE_VOLUME and w.get("v15_trigger"):
                    need = (w.get("v15_avg") or w["v15_trigger"]) * C.OPEN_CANDLE_VOL_MULT if e == first else w["v15_trigger"]
                    if v < need:
                        reason = f"volume: {v:,.0f} < {need:,.0f} needed"
                if not reason and w.get("atr") and c - w["trigger"] > C.MAX_CHASE_ATR * w["atr"]:
                    reason = f"chase: closed {c - w['trigger']:.2f} above trigger (> {C.MAX_CHASE_ATR} ATR)"
                entry = c * (1 + C.SLIPPAGE)
                risk_ps = entry - w["stop"]
                if not reason and risk_ps <= 0:
                    reason = "stop: stop above entry"
                if not reason and (w["target"] - entry) < C.MIN_RR * risk_ps:
                    reason = "reward: target less than 1R away"
                if reason:
                    _skip(st, w, stamp, reason)
                    continue
                strength = v / (w.get("v15_avg") or max(v, 1))
                cands.append((strength, t, w, entry, risk_ps))
            for _, t, w, entry, risk_ps in sorted(cands, key=lambda x: -x[0]):
                if len(st["open"]) >= C.MAX_OPEN or len(st["closed"]) + len(st["open"]) >= C.MAX_TRADES_PER_DAY:
                    _skip(st, w, stamp, "slots: max open positions / trades reached")
                    continue
                qty = math.floor(C.RISK_PER_TRADE / risk_ps)
                qty = min(qty, math.floor(C.CAPITAL * C.LEVERAGE * C.MAX_POSITION_SHARE / entry))
                if qty < 1:
                    _skip(st, w, stamp, "size: position rounds to zero shares")
                    continue
                _open(st, w, entry, qty, risk_ps, stamp, ev)
                traded.add(w["symbol"])
        st["processed_until"] = stamp
    return ev


def force_square_off(st, candles, ev):
    """End-of-day fallback when the 15:15 candle never arrived."""
    stamp = st["processed_until"] or "15:15"
    for sym, p in list(st["open"].items()):
        df = candles.get(p["ticker"])
        px = float(df["Close"].iloc[-1]) if df is not None and len(df) else p["entry"]
        _close(st, sym, px * (1 - C.SLIPPAGE), stamp, "square-off (late data)", ev)
    st["status"] = "closed"


# ---------------------------------------------------------------- ledger & summary
def append_ledger(st):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    exists = LEDGER.exists()
    have = set()
    if exists:
        with LEDGER.open() as f:
            have = {(r["date"], r["symbol"]) for r in csv.DictReader(f)}
    with LEDGER.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        if not exists:
            w.writeheader()
        for t in st["closed"]:
            if (st["date"], t["symbol"]) in have:
                continue
            w.writerow({k: (st["date"] if k == "date" else t.get(k)) for k in LEDGER_COLS})


def rebuild_summary():
    if not LEDGER.exists():
        return {}
    df = pd.read_csv(LEDGER)
    if df.empty:
        return {}
    daily = df.groupby("date").agg(trades=("net", "size"), net=("net", "sum"),
                                   wins=("net", lambda s: int((s > 0).sum()))).reset_index()
    daily["equity"] = C.CAPITAL + daily["net"].cumsum()
    peak = daily["equity"].cummax()
    dd = ((daily["equity"] - peak) / peak * 100).min()
    wins, losses = df[df.net > 0], df[df.net <= 0]
    s = dict(
        updated=now_ist().strftime("%Y-%m-%d %H:%M IST"), capital=C.CAPITAL,
        equity=round(float(daily["equity"].iloc[-1]), 2),
        net=round(float(df.net.sum()), 2), gross=round(float(df.gross.sum()), 2),
        charges=round(float(df.charges.sum()), 2),
        days=int(len(daily)), trades=int(len(df)), wins=int(len(wins)), losses=int(len(losses)),
        win_rate=round(len(wins) / len(df) * 100, 1),
        avg_r=round(float(df.r.mean()), 2),
        avg_win=round(float(wins.net.mean()), 2) if len(wins) else 0.0,
        avg_loss=round(float(losses.net.mean()), 2) if len(losses) else 0.0,
        profit_factor=round(float(wins.net.sum() / -losses.net.sum()), 2) if len(losses) and losses.net.sum() < 0 else None,
        max_drawdown_pct=round(float(dd), 2),
        by_reason=df.reason.value_counts().to_dict(),
        daily=daily.round(2).to_dict("records"),
    )
    SUMMARY.write_text(json.dumps(s, indent=1))
    return s


# ---------------------------------------------------------------- commands
def cmd_start(day, quiet=False):
    path = state_file(day)
    if path.exists():
        print(f"{day}: state already exists ({json.loads(path.read_text())['status']})")
        return json.loads(path.read_text())
    wl = load_watchlist(WATCHLIST, day)
    st = new_state(day, wl)
    save(st, path)
    msg = (f"📋 Paper trading {day}: {len(wl['items'])} stocks on the watchlist "
           f"(scan of {wl['session']}). Capital {inr(C.CAPITAL)}, risk {inr(C.RISK_PER_TRADE)}/trade, "
           f"max {C.MAX_OPEN} open.")
    print(msg)
    if not quiet:
        notify.send(msg)
    return st


def cmd_run(day):
    path = state_file(day)
    st = json.loads(path.read_text()) if path.exists() else cmd_start(day)
    if st["status"] != "open":
        print(f"{day}: day is {st['status']}")
        return st
    now = now_ist()
    log = []
    candles = fetch_candles([w["ticker"] for w in st["watchlist"]], day, now=now, log=log)
    if not candles:
        if now.hour * 60 + now.minute >= hm("10:30"):
            st["status"] = "no-session"
            notify.send(f"Paper trading {day}: no NSE candles by 10:30, treating it as a holiday.")
        print(f"{day}: no candles yet ({'; '.join(log[-2:])})")
        save(st, path)
        return st
    ev = process(st, candles)
    save(st, path)
    for e in ev:
        print(e)
        notify.send(e)
    print(f"{day}: processed to {st['processed_until']} | open {len(st['open'])} | closed {len(st['closed'])}")
    return st


def day_report(st) -> str:
    net = sum(t["net"] for t in st["closed"])
    wins = sum(1 for t in st["closed"] if t["net"] > 0)
    lines = [f"📊 Paper trading {st['date']}: {len(st['closed'])} trades, {wins} winners, net {inr(net)}"]
    for t in st["closed"]:
        lines.append(f"  {t['symbol']}: {t['entry_time']} {inr(t['entry'])} → {t['exit_time']} {inr(t['exit'])} "
                     f"{t['reason']} {inr(t['net'])} ({t['r']}R)")
    return "\n".join(lines)


def cmd_close(day):
    path = state_file(day)
    if not path.exists():
        print(f"{day}: no state (no watchlist loaded today)")
        return None
    st = json.loads(path.read_text())
    ev = []
    if st["status"] == "open":
        candles = fetch_candles([w["ticker"] for w in st["watchlist"]], day, now=now_ist())
        ev += process(st, candles)
        if st["status"] == "open":
            force_square_off(st, candles, ev)
    save(st, path)
    append_ledger(st)
    s = rebuild_summary()
    rep = day_report(st)
    if s:
        rep += (f"\nTotal since start: {s['trades']} trades over {s['days']} days, win rate {s['win_rate']}%, "
                f"net {inr(s['net'])}, equity {inr(s['equity'])}")
    print(rep)
    notify.send(rep)
    return st


def cmd_replay(day, watchlist=None):
    if watchlist is None:
        hist = sorted((ROOT / "data" / "intraday" / "history").glob("*.json"))
        prior = [p for p in hist if p.stem < str(day)]
        if not prior:
            raise SystemExit("no earlier intraday watchlist in data/intraday/history")
        watchlist = prior[-1]
    wl = load_watchlist(Path(watchlist), day)
    st = new_state(day, wl)
    age = (date.today() - day).days
    candles = fetch_candles([w["ticker"] for w in wl["items"]], day, now=None,
                            period="5d" if age < 4 else ("1mo" if age < 25 else "60d"))
    if not candles:
        raise SystemExit(f"no 15-minute candles for {day}")
    process(st, candles)
    if st["status"] == "open":
        force_square_off(st, candles, [])
    st["replay"] = dict(watchlist=str(watchlist), candles_for=len(candles))
    save(st, state_file(day, replay=True))
    print(day_report(st))
    print(f"\nwatchlist {wl['session']}: {len(wl['items'])} stocks, candles for {len(candles)}; "
          f"skipped {len(st['skipped'])}: " + "; ".join(f"{s['symbol']} {s['reason']}" for s in st["skipped"][:12]))
    return st


def cmd_check():
    ok = True
    try:
        doc = json.loads(WATCHLIST.read_text())
        print(f"watchlist: session {doc['meta']['session_date']}, {len(doc['rows'])} rows  OK")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"watchlist: FAILED {e}")
    frames = prices.download(["RELIANCE.NS", "HDFCBANK.NS", "INFY.NS"], period="5d", interval="15m", min_rows=1)
    if frames:
        last = max(df.index[-1] for df in frames.values())
        print(f"yahoo 15m: {len(frames)}/3 tickers, latest candle {last}  OK")
    else:
        ok = False
        print("yahoo 15m: FAILED (no data)")
    print("telegram: " + ("sent test message  OK" if notify.send("✅ Paper trader connected.") else "not configured (optional)"))
    print(f"clock: {now_ist():%Y-%m-%d %H:%M} IST")
    sys.exit(0 if ok else 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "run", "close", "check", "replay"])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    ap.add_argument("--watchlist")
    a = ap.parse_args(argv)
    day = date.fromisoformat(a.date) if a.date else now_ist().date()
    if a.cmd in ("start", "run", "close") and day.weekday() >= 5:
        print(f"{day} is a weekend")
        return
    {"start": lambda: cmd_start(day), "run": lambda: cmd_run(day), "close": lambda: cmd_close(day),
     "check": cmd_check, "replay": lambda: cmd_replay(day, a.watchlist)}[a.cmd]()


if __name__ == "__main__":
    main()
