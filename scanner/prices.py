"""Price data: Yahoo Finance (history, 15-min bars, global markets) and the NSE
bhavcopy (official closes and delivery %)."""
import io
import time
from datetime import date

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .universe import UA

COLS = ["Open", "High", "Low", "Close", "Volume"]


def _split(df: pd.DataFrame, chunk: list) -> dict:
    out = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = set(df.columns.get_level_values(0))
        for t in chunk:
            if t not in lvl0:
                continue
            sub = df[t]
            if not set(COLS).issubset(sub.columns):
                continue
            out[t] = sub[COLS]
    elif len(chunk) == 1 and set(COLS).issubset(df.columns):
        out[chunk[0]] = df[COLS]
    return out


def download(tickers, period="5y", interval="1d", batch=80, log=None, min_rows=30):
    """Download OHLCV for many tickers. Returns {ticker: DataFrame}."""
    frames = {}
    tickers = list(dict.fromkeys(tickers))
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        df = None
        for attempt in range(4):
            try:
                df = yf.download(chunk, period=period, interval=interval, group_by="ticker",
                                 auto_adjust=False, actions=False, threads=True, progress=False,
                                 timeout=30)
                break
            except Exception as e:  # noqa: BLE001
                if log is not None:
                    log.append(f"yahoo batch {i // batch} attempt {attempt + 1}: {e}")
                time.sleep(10 * (attempt + 1))
        for t, sub in _split(df, chunk).items():
            sub = sub.dropna(subset=["Close", "High", "Low"])
            sub = sub[sub["Close"] > 0]
            if len(sub) >= min_rows:
                sub.index = pd.to_datetime(sub.index).tz_localize(None) if sub.index.tz is not None else pd.to_datetime(sub.index)
                frames[t] = sub.astype("float64")
        # missing tickers get one retry on their own (Yahoo drops a few per batch)
        missing = [t for t in chunk if t not in frames]
        if missing and len(missing) < len(chunk):
            time.sleep(2)
            try:
                df2 = yf.download(missing, period=period, interval=interval, group_by="ticker",
                                  auto_adjust=False, actions=False, threads=True, progress=False, timeout=30)
                for t, sub in _split(df2, missing).items():
                    sub = sub.dropna(subset=["Close", "High", "Low"])
                    sub = sub[sub["Close"] > 0]
                    if len(sub) >= min_rows:
                        sub.index = pd.to_datetime(sub.index).tz_localize(None) if sub.index.tz is not None else pd.to_datetime(sub.index)
                        frames[t] = sub.astype("float64")
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1.0)
    return frames


def bhavcopy(d: date, log: list):
    """NSE full bhavcopy with delivery data for date d -> DataFrame indexed by SYMBOL, or None."""
    ds = d.strftime("%d%m%Y")
    urls = [
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv",
        f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv",
    ]
    s = requests.Session()
    s.headers.update(UA)
    for u in urls:
        for attempt in range(2):
            try:
                r = s.get(u, timeout=30)
                if r.status_code == 200 and b"SYMBOL" in r.content[:200]:
                    df = pd.read_csv(io.StringIO(r.text), dtype=str)
                    df.columns = [c.strip() for c in df.columns]
                    df = df.apply(lambda c: c.str.strip())
                    df = df[df["SERIES"].isin(["EQ", "BE", "BZ"])].copy()
                    for c in ["CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_QTY", "DELIV_PER",
                              "HIGH_PRICE", "LOW_PRICE", "OPEN_PRICE", "PREV_CLOSE"]:
                        if c in df:
                            df[c] = pd.to_numeric(df[c], errors="coerce")
                    df = df.drop_duplicates("SYMBOL").set_index("SYMBOL")
                    log.append(f"bhavcopy {d}: {len(df)} rows from {u.split('/')[2]}")
                    return df
                log.append(f"bhavcopy {d}: {u.split('/')[2]} HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                log.append(f"bhavcopy {d}: {u.split('/')[2]} {e.__class__.__name__}")
            time.sleep(3)
    return None


def avg_15m_volume(tickers, log):
    """Average volume per 15-minute candle over the last ~10 sessions (excluding the 09:15 open candle)."""
    frames = download(tickers, period="10d", interval="15m", batch=50, log=log, min_rows=20)
    out = {}
    for t, df in frames.items():
        v = df["Volume"]
        idx = df.index
        mask = ~((idx.hour == 9) & (idx.minute == 15)) if hasattr(idx, "hour") else np.ones(len(v), bool)
        v = v[mask]
        v = v[v > 0]
        if len(v) >= 20:
            out[t] = float(v.mean())
    return out


def global_markets(tickers, log):
    frames = download([t for t, _ in tickers], period="1mo", interval="1d", batch=20, log=log, min_rows=3)
    rows = []
    for t, label in tickers:
        df = frames.get(t)
        if df is None or len(df) < 2:
            rows.append(dict(ticker=t, label=label, close=None, chg=None, date=None))
            continue
        c = df["Close"].iloc[-1]
        p = df["Close"].iloc[-2]
        rows.append(dict(ticker=t, label=label, close=round(float(c), 2),
                         chg=round(float((c / p - 1) * 100), 2), date=str(df.index[-1].date())))
    return rows
