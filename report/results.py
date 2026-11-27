"""Quarterly-results cache shared by all scans.

  python -m report.results todo --scan swing --limit 20     # stocks needing a lookup (JSON)
  python -m report.results set HDFCBANK --quarter "Q2 FY27" --verdict In-line \
         --text "Rev ₹95,132 Cr +9%, PAT ₹21,537 Cr +6% YoY"

Verdict rule (consolidated, YoY): Good = PAT growth >= +15% or a swing from loss to
profit; Bad = PAT down YoY, a fresh loss, or a wider loss; In-line = everything between.
Use NA when no result can be found (e.g. recent IPO); it is re-checked after 14 days.
"""
import argparse
import json
from datetime import date, timedelta

from .common import GROUP_ORDER, expected_quarter, load_cache, load_scan, save_cache, today_ist

VERDICTS = {"good": "Good", "in-line": "In-line", "inline": "In-line", "bad": "Bad", "na": "NA", "n/a": "NA"}


def needs_lookup(entry, exp_q, in_season, today: date):
    if not entry:
        return "missing"
    checked = date.fromisoformat(entry.get("checked", "2000-01-01"))
    age = (today - checked).days
    if entry.get("verdict") == "NA":
        return "retry" if age >= 14 else None
    if entry.get("quarter") != exp_q:
        if in_season and age < 5:
            return None
        return "new quarter"
    return None


def todo(scans, limit):
    cache = load_cache()
    today = today_ist()
    exp_q, in_season = expected_quarter(today)
    seen, out = set(), []
    rows = []
    for s in scans:
        try:
            rows += load_scan(s)["rows"]
        except FileNotFoundError:
            pass
    rows.sort(key=lambda r: GROUP_ORDER.index(r["group"]))
    for r in rows:
        if r.get("index") or r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        why = needs_lookup(cache.get(r["symbol"]), exp_q, in_season, today)
        if why:
            out.append(dict(symbol=r["symbol"], name=r["name"], group=r["group"], reason=why,
                            expected_quarter=exp_q,
                            have=cache.get(r["symbol"], {}).get("quarter")))
    return dict(expected_quarter=exp_q, in_season=in_season, total=len(out), items=out[:limit])


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("todo")
    t.add_argument("--scan", default="swing", help="comma list")
    t.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("set")
    s.add_argument("symbol")
    s.add_argument("--quarter", required=True)
    s.add_argument("--verdict", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--source", default="web search")
    a = ap.parse_args(argv)

    if a.cmd == "todo":
        print(json.dumps(todo([x.strip() for x in a.scan.split(",")], a.limit), indent=1, ensure_ascii=False))
    else:
        v = VERDICTS.get(a.verdict.strip().lower())
        if not v:
            raise SystemExit(f"verdict must be one of Good, In-line, Bad, NA (got {a.verdict})")
        c = load_cache()
        c[a.symbol.upper()] = dict(quarter=a.quarter.strip(), verdict=v, text=a.text.strip(),
                                   checked=str(today_ist()), source=a.source)
        save_cache(c)
        print(f"saved {a.symbol.upper()}: {v} {a.quarter}")


if __name__ == "__main__":
    main()
