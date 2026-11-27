"""Run one or more breakout scans and write data/<scan>/latest.json.

    python -m scanner.scan --scans intraday,swing,longterm
"""
import argparse
import json
import math
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import prices, universe
from .config import GLOBAL_TICKERS, SCANS
from .levels import atr, breakout, invalidation, resample, tf_status, vol_ratio

ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
LISTED = ("above", "on", "near1", "near2")


def r2(x):
    if x is None:
        return None
    try:
        if math.isnan(x):
            return None
    except TypeError:
        return x
    return round(float(x), 2)


def group_of(diff, cfg):
    b1, b2 = cfg["bands"]
    if abs(diff) <= cfg["on_tol"]:
        return "on"
    if diff > 0:
        return "above" if diff <= cfg["max_ext"] else "extended"
    if diff >= -b1:
        return "near1"
    if diff >= -b2:
        return "near2"
    return "far"


def analyse(df, cfg, is_index):
    weekly_primary = cfg["timeframe"] == "W"
    bars = resample(df, "W-FRI") if weekly_primary else df
    r = breakout(bars, cfg["pivot"], cfg["lookback"], cfg["recent"], cfg["on_tol"])
    if r is None:
        return None
    g = group_of(r["diff"], cfg)
    rec = dict(close=r2(r["close"]), level=r2(r["level"]), diff=r2(r["diff"]), group=g,
               days=r["days"], kind=r["kind"], level_date=r["level_date"])
    if g not in LISTED:
        return rec

    level = r["level"]
    a = atr(df, 14)
    rec["atr"] = r2(a)
    inv = invalidation(bars, level, cfg["inv_pivot"], cfg["lookback"])
    rec["inv"] = r2(inv)
    if "atr_stop" in cfg:                         # intraday: ATR-based trade plan off the trigger
        pdh = float(df["High"].iloc[-1])
        trigger = max(level, pdh) if g == "above" else level
        rec["trigger"] = r2(trigger)
        rec["pdh"] = r2(pdh)
        rec["stop"] = r2(trigger - cfg["atr_stop"] * a)
        rec["target"] = r2(trigger + cfg["atr_target"] * a)
    else:
        rec["target"] = r2(level + cfg["r_multiple"] * (level - inv))

    if not is_index:
        idx = r["bo_idx"] if r["days"] else len(bars) - 1
        vr = vol_ratio(bars, idx, cfg["vol_avg"])
        rec["vol_ratio"] = r2(vr)
        rec["vol_on"] = "breakout bar" if r["days"] else "last bar"
        rec["vol_ok"] = bool(vr is not None and vr >= cfg["vol_min"])

    if weekly_primary:
        m = tf_status(resample(df, "ME"), cfg["m"])
        rec["m"] = m
        hi = float(df["High"].iloc[-252:].max())
        rec["hi52"] = r2(hi)
        rec["hi52_pct"] = r2((r["close"] / hi - 1) * 100)
    else:
        rec["w"] = tf_status(resample(df, "W-FRI"), cfg["w"])
        rec["m"] = tf_status(resample(df, "ME"), cfg["m"])
    return rec


def session_label(d):
    return d.strftime("%-d %b %Y (%a)")


def run(name, asof=None):
    cfg = SCANS[name]
    log = []
    uni = universe.load(cfg["universe"], log)
    tick = {f"{s}.NS": (s, n) for s, n in zip(uni["symbol"], uni["name"])}
    idx = {t: (code, label) for t, label, code in cfg["indices"]}
    log.append(f"universe {cfg['universe']}: {len(tick)} symbols")

    frames = prices.download(list(tick) + list(idx), period=cfg["period"], log=log)
    if asof:
        cut = pd.Timestamp(asof)
        frames = {t: f[f.index <= cut] for t, f in frames.items()}
        frames = {t: f for t, f in frames.items() if len(f) >= 30}
        log.append(f"as-of mode: bars after {asof} dropped")
    log.append(f"yahoo: {len(frames)} of {len(tick) + len(idx)} tickers returned data")
    if len(frames) < 0.5 * (len(tick) + len(idx)):
        raise RuntimeError(f"Yahoo returned only {len(frames)} of {len(tick) + len(idx)} tickers")

    if "^NSEI" in frames:
        session = frames["^NSEI"].index[-1].date()
    else:
        session = pd.Series([f.index[-1] for f in frames.values()]).mode()[0].date()

    now = datetime.now(IST)
    after_close_today = session == now.date() and 15 <= now.hour < 22
    bhav = prices.bhavcopy(session, log, wait=after_close_today and name != "intraday")

    rows, counts = [], {k: 0 for k in ("above", "on", "near1", "near2", "far", "extended")}
    stale = illiquid = nodata = errors = 0
    vol_confirmed_above = 0

    for t in list(tick) + list(idx):
        is_index = t in idx
        df = frames.get(t)
        if df is None:
            nodata += 1
            continue
        if df.index[-1].date() != session:
            stale += 1
            if stale <= 5:
                log.append(f"stale {t}: last bar {df.index[-1]}")
            continue
        if is_index:
            code, label = idx[t]
            sym, disp = code.split(":")[1], label
        else:
            sym, disp = tick[t]
            code = f"NSE:{sym}"
            if bhav is not None and sym in bhav.index:
                b = bhav.loc[sym]
                if b.get("CLOSE_PRICE") and b["CLOSE_PRICE"] > 0:
                    df = df.copy()
                    df.iloc[-1, df.columns.get_loc("Close")] = float(b["CLOSE_PRICE"])
                    if b.get("TTL_TRD_QNTY") and b["TTL_TRD_QNTY"] > 0:
                        df.iloc[-1, df.columns.get_loc("Volume")] = float(b["TTL_TRD_QNTY"])
            if cfg.get("min_turnover_cr"):
                tv = (df["Close"].iloc[-20:] * df["Volume"].iloc[-20:]).mean() / 1e7
                if not tv or tv < cfg["min_turnover_cr"]:
                    illiquid += 1
                    continue
        try:
            rec = analyse(df, cfg, is_index)
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.append(f"{t}: {e.__class__.__name__}: {e}")
            continue
        if rec is None:
            nodata += 1
            continue
        counts[rec["group"]] += 1
        if rec["group"] not in LISTED:
            continue
        rec.update(symbol=sym, name=disp, code=code, ticker=t, index=is_index)
        if not is_index and bhav is not None and sym in bhav.index:
            dp = bhav.loc[sym].get("DELIV_PER")
            rec["deliv"] = r2(dp) if dp == dp else None
        if rec["group"] == "above" and rec.get("vol_ok"):
            vol_confirmed_above += 1
        rows.append(rec)

    if name == "intraday":
        listed_stocks = [r["ticker"] for r in rows if not r["index"]]
        v15 = prices.avg_15m_volume(listed_stocks, log, asof=asof) if listed_stocks else {}
        for r in rows:
            if r["ticker"] in v15:
                r["v15_avg"] = round(v15[r["ticker"]])
                r["v15_trigger"] = round(v15[r["ticker"]] * cfg["vol_min"])

    rows.sort(key=lambda r: r["name"].lower())
    now_ist = datetime.now(IST)
    meta = dict(
        scan=name, title=cfg["title"], short=cfg["short"],
        session_date=str(session), session_label=session_label(session),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generated_ist=now_ist.strftime("%d %b %Y %H:%M IST"),
        universe=cfg["universe"], universe_size=len(tick), indices=len(idx),
        scanned=sum(counts.values()), stale=stale, illiquid=illiquid, nodata=nodata, errors=errors,
        counts=counts, vol_confirmed_above=vol_confirmed_above,
        bhavcopy=bhav is not None,
        params={k: cfg[k] for k in ("bands", "on_tol", "max_ext", "vol_min", "vol_avg", "tf_word",
                                     "pivot", "lookback", "recent") if k in cfg}
               | {k: cfg[k] for k in ("r_multiple", "atr_stop", "atr_target", "min_turnover_cr") if k in cfg},
        log=log[-60:],
    )
    if name == "intraday":
        meta["global"] = prices.global_markets(GLOBAL_TICKERS, log, asof=asof)

    out_dir = ROOT / "data" / name
    (out_dir / "history").mkdir(parents=True, exist_ok=True)
    doc = dict(meta=meta, rows=rows)
    text = json.dumps(doc, indent=1, default=str)
    (out_dir / "latest.json").write_text(text)
    (out_dir / "history" / f"{session}.json").write_text(text)
    (out_dir / "status.json").write_text(json.dumps(dict(ok=True, scan=name, session_date=str(session),
                                                         generated_at=meta["generated_at"]), indent=1))
    print(f"[{name}] session {session}: listed {len(rows)} | counts {counts} | stale {stale} "
          f"illiquid {illiquid} nodata {nodata} errors {errors} | bhavcopy {bhav is not None}")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scans", default="intraday,swing,longterm")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD: ignore bars after this date (backtest / re-run)")
    a = ap.parse_args(argv)
    ok = 0
    for name in [s.strip() for s in a.scans.split(",") if s.strip()]:
        try:
            run(name, a.asof)
            ok += 1
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            d = ROOT / "data" / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "status.json").write_text(json.dumps(dict(
                ok=False, scan=name, error=f"{e.__class__.__name__}: {e}",
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")), indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
