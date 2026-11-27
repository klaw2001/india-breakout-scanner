"""Breakout level logic.

Definitions (also printed in the PDF):
- Swing high (pivot): a bar whose high is the highest of `left` bars before it
  and `right` bars after it. Only confirmed pivots count, and the current bar is
  never used to confirm one, so today's bar can break a level cleanly.
- Breakout level, in priority order:
    1. a pivot broken within the last `recent` bars that price is still holding
       (the highest such level, so a gap through two levels reports the bigger one);
    2. otherwise the nearest untaken pivot above price (nearest overhead resistance);
    3. otherwise (price above every pivot in the window) the highest pivot in the window.
- Invalidation: the most recent confirmed swing low below the breakout level.
- Target: breakout + R x (breakout - invalidation).
"""
import numpy as np
import pandas as pd


def pivot_mask(s: pd.Series, left: int, right: int, high: bool = True) -> np.ndarray:
    if high:
        win = s.rolling(left + right + 1).max().shift(-right)
        lft = s.shift(1).rolling(left).max()
        m = (s >= win) & (s > lft)
    else:
        win = s.rolling(left + right + 1).min().shift(-right)
        lft = s.shift(1).rolling(left).min()
        m = (s <= win) & (s < lft)
    return m.fillna(False).to_numpy(dtype=bool)


def breakout(bars: pd.DataFrame, pivot, lookback: int, recent: int, on_tol: float = 0.10):
    """`bars`: OHLCV with the current (latest) bar last. Returns a dict or None."""
    left, right = pivot
    n = len(bars)
    if n < left + right + 6:
        return None
    hist = bars.iloc[:-1]
    highs = hist["High"].to_numpy()
    closes = bars["Close"].to_numpy()
    t = n - 1
    close = float(closes[t])
    pm = pivot_mask(hist["High"], left, right, high=True)
    start = max(0, len(hist) - lookback)
    piv = [i for i in range(start, len(hist)) if pm[i]]
    fallback = False
    if not piv:
        piv = [start + int(np.argmax(highs[start:]))]
        fallback = True

    info = []
    for i in piv:
        p = float(highs[i])
        cross = np.nonzero(closes[i + 1:t + 1] > p)[0]
        first = i + 1 + int(cross[0]) if len(cross) else None
        info.append((i, p, first))

    recent_broken = [x for x in info
                     if x[2] is not None and x[2] >= t - recent + 1 and close >= x[1] * (1 - on_tol / 100)]
    if recent_broken:
        i, p, f = max(recent_broken, key=lambda x: x[1])
        days = t - f + 1
        bo_idx = f
        kind = "fresh"
    else:
        active = [x for x in info if x[2] is None]
        if active:
            i, p, f = min(active, key=lambda x: x[1])
            days, bo_idx, kind = 0, None, "overhead"
        else:
            i, p, f = max(info, key=lambda x: x[1])
            days, j = 0, t
            while j > i and closes[j] > p:
                days += 1
                j -= 1
            bo_idx = t - days + 1 if days else None
            kind = "held" if days else "lost"

    diff = (close / p - 1) * 100
    return dict(level=p, level_idx=i, level_date=str(bars.index[i].date()), diff=diff,
                days=days, bo_idx=bo_idx, kind=kind, fallback=fallback, close=close)


def invalidation(bars: pd.DataFrame, level: float, pivot, lookback: int) -> float:
    hist = bars.iloc[:-1]
    lows = hist["Low"].to_numpy()
    pm = pivot_mask(hist["Low"], pivot[0], pivot[1], high=False)
    start = max(0, len(hist) - lookback)
    cands = [i for i in range(start, len(hist)) if pm[i] and lows[i] < level * 0.999]
    if cands:
        return float(lows[cands[-1]])
    window = lows[start:]
    below = window[window < level * 0.999]
    return float(below.min()) if len(below) else float(window.min())


def atr(bars: pd.DataFrame, n: int = 14) -> float:
    h, l, c = bars["High"], bars["Low"], bars["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-n:].mean())


def vol_ratio(bars: pd.DataFrame, idx: int, n: int):
    """Volume of bar `idx` divided by the average of the `n` bars before it."""
    v = bars["Volume"].to_numpy()
    if idx is None or idx < n or v[idx] <= 0:
        return None
    base = v[idx - n:idx]
    base = base[base > 0]
    if len(base) < n // 2:
        return None
    return float(v[idx] / base.mean())


def resample(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    out = daily.resample(rule).agg(agg).dropna(subset=["Close"])
    # label each bar with its last actual trading day, not the calendar period end
    last_day = daily["Close"].resample(rule).apply(lambda s: s.index.max() if len(s) else pd.NaT)
    out.index = pd.DatetimeIndex(last_day.reindex(out.index).values)
    return out


def tf_status(bars: pd.DataFrame, spec: dict):
    r = breakout(bars, spec["pivot"], spec["lookback"], spec["recent"])
    if r is None:
        return None
    return dict(level=round(r["level"], 2), above=bool(r["close"] > r["level"]))
