import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "results_cache.json"
IST = timezone(timedelta(hours=5, minutes=30))
GROUP_ORDER = ["above", "on", "near1", "near2"]


def today_ist() -> date:
    return datetime.now(IST).date()


def load_scan(scan: str) -> dict:
    return json.loads((DATA / scan / "latest.json").read_text())


def load_status(scan: str) -> dict:
    p = DATA / scan / "status.json"
    return json.loads(p.read_text()) if p.exists() else {}


def load_cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def save_cache(c: dict):
    CACHE.write_text(json.dumps(dict(sorted(c.items())), indent=1, ensure_ascii=False))


def fy_label(year: int, month: int) -> str:
    """Indian FY label for a quarter-end month. Jun 2026 -> Q1 FY27."""
    fy = year + 1 if month >= 4 else year
    q = {6: 1, 9: 2, 12: 3, 3: 4}[month]
    return f"Q{q} FY{fy % 100:02d}"


def expected_quarter(d: date):
    """(latest quarter most companies have reported, in_results_season)."""
    y = d.year
    md = (d.month, d.day)
    if md < (1, 15):
        return fy_label(y - 1, 9), True
    if md < (2, 15):
        return fy_label(y - 1, 12), True
    if md < (4, 15):
        return fy_label(y - 1, 12), False
    if md < (6, 1):
        return fy_label(y, 3), True
    if md < (7, 15):
        return fy_label(y, 3), False
    if md < (8, 15):
        return fy_label(y, 6), True
    if md < (10, 15):
        return fy_label(y, 6), False
    if md < (11, 15):
        return fy_label(y, 9), True
    return fy_label(y, 9), False


def indian(x, dp=2) -> str:
    """1234567.8 -> 12,34,567.80"""
    if x is None:
        return "–"
    neg = x < 0
    s = f"{abs(x):.{dp}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = whole + ("." + frac if frac else "")
    return ("−" if neg else "") + out


def shares(n) -> str:
    if n is None:
        return "–"
    if n >= 1e7:
        return f"{n / 1e7:.2f}Cr"
    if n >= 1e5:
        return f"{n / 1e5:.2f}L"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return f"{n:.0f}"
