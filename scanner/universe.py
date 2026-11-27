"""Stock universes: F&O list, Nifty 500, all NSE equities.

Each list is refreshed from NSE at most once a week and committed to
data/universe/ so a blocked or failed download falls back to the last good copy.
"""
import io
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
UNI_DIR = ROOT / "data" / "universe"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

SOURCES = {
    "equity_l": [
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    ],
    "nifty500": [
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    ],
    "nifty200": [
        "https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    ],
    "fo_mktlots": [
        "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv",
        "https://archives.nseindia.com/content/fo/fo_mktlots.csv",
    ],
}

MAX_AGE_DAYS = 7
_SUFFIX = re.compile(r"\s+(limited|ltd\.?)$", re.I)


def clean_name(name: str) -> str:
    name = " ".join(str(name).split())
    name = _SUFFIX.sub("", name).strip()
    return name


def _fetch(urls):
    s = requests.Session()
    s.headers.update(UA)
    last = None
    for u in urls:
        for attempt in range(2):
            try:
                r = s.get(u, timeout=30)
                if r.status_code == 200 and len(r.content) > 200 and b"<html" not in r.content[:300].lower():
                    return r.text, u
                last = f"{u} -> HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = f"{u} -> {e.__class__.__name__}: {e}"
            time.sleep(2)
    raise RuntimeError(last or "no source")


def _cached(name: str, log: list) -> pd.DataFrame:
    """Return the raw CSV for `name`, refreshing it if stale."""
    UNI_DIR.mkdir(parents=True, exist_ok=True)
    path = UNI_DIR / f"{name}.csv"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < MAX_AGE_DAYS * 86400
    if not fresh:
        try:
            text, src = _fetch(SOURCES[name])
            path.write_text(text)
            log.append(f"universe {name}: refreshed from {src}")
        except Exception as e:  # noqa: BLE001
            if path.exists():
                log.append(f"universe {name}: refresh failed ({e}); using cached copy")
            else:
                raise RuntimeError(f"universe {name}: no data ({e})")
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    return df.apply(lambda c: c.str.strip() if pd.api.types.is_string_dtype(c) else c)


def _equity_names(log):
    try:
        eq = _cached("equity_l", log)
    except Exception as e:  # noqa: BLE001
        log.append(str(e))
        return {}, set()
    eq = eq[eq["SERIES"].isin(["EQ", "BE", "BZ"])]
    names = {r.SYMBOL: clean_name(r["NAME OF COMPANY"]) for _, r in eq.iterrows()}
    return names, set(eq["SYMBOL"])


def load(kind: str, log: list) -> pd.DataFrame:
    """Return DataFrame[symbol, name] for the universe `kind`."""
    names, eq_symbols = _equity_names(log)

    if kind == "nifty500" or kind == "nifty200":
        df = _cached(kind, log)
        out = pd.DataFrame({"symbol": df["Symbol"], "name": df["Company Name"].map(clean_name)})

    elif kind == "fo":
        try:
            df = _cached("fo_mktlots", log)
            col = [c for c in df.columns if c.upper() == "SYMBOL"][0]
            syms = [s for s in df[col].dropna().unique() if s and s.upper() != "SYMBOL"]
            if eq_symbols:
                syms = [s for s in syms if s in eq_symbols]   # drops index rows (NIFTY, BANKNIFTY...)
            if len(syms) < 100:
                raise RuntimeError(f"only {len(syms)} F&O symbols parsed")
            out = pd.DataFrame({"symbol": syms})
            out["name"] = out["symbol"].map(lambda s: names.get(s, s))
        except Exception as e:  # noqa: BLE001
            log.append(f"F&O list unavailable ({e}); using Nifty 200 as the intraday universe")
            df = _cached("nifty200", log)
            out = pd.DataFrame({"symbol": df["Symbol"], "name": df["Company Name"].map(clean_name)})

    elif kind == "allnse":
        if not names:
            raise RuntimeError("EQUITY_L unavailable and no cached copy")
        out = pd.DataFrame({"symbol": list(names), "name": list(names.values())})

    else:
        raise ValueError(kind)

    out = out.dropna().drop_duplicates("symbol").reset_index(drop=True)
    return out


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
