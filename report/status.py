"""Freshness check used at the start of every scheduled Claude run.

    python -m report.status --scan swing
Prints JSON with `state`: fresh | holiday | stale | failed | missing.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

from .common import DATA, IST, load_scan, load_status


def expected_session(now_ist: datetime):
    d = now_ist.date() if now_ist.hour >= 18 else now_ist.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def check(scan: str) -> dict:
    now = datetime.now(IST)
    exp = expected_session(now)
    st = load_status(scan)
    if not st:
        return dict(scan=scan, state="missing", message="No data has been generated for this scan yet.")
    gen = datetime.strptime(st["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    age_h = round((now - gen).total_seconds() / 3600, 1)
    out = dict(scan=scan, expected_session=str(exp), generated_at=st["generated_at"], age_hours=age_h)
    if not st.get("ok"):
        out.update(state="failed", error=st.get("error"),
                   message=f"The GitHub data job failed {age_h} h ago: {st.get('error')}")
        return out
    sess = st["session_date"]
    out["session_date"] = sess
    if age_h > 20:
        out.update(state="stale", message=f"Latest data is {age_h} h old (session {sess}); the GitHub job has not run since.")
    elif sess < str(exp):
        out.update(state="holiday", message=f"Data job ran {age_h} h ago but the latest NSE session is {sess}, "
                                            f"not {exp}: market holiday or Yahoo has not posted the bar yet.")
    else:
        out.update(state="fresh", message="ok")
    return out


def summary(scan: str) -> str:
    doc = load_scan(scan)
    m, rows = doc["meta"], doc["rows"]
    c = m["counts"]
    b1, b2 = m["params"]["bands"]
    return (f"{m['short']} scan · {m['session_label']}: {c['above']} closed above "
            f"({m['vol_confirmed_above']} on ≥{m['params']['vol_min']:g}× volume), {c['on']} on, "
            f"{c['near1']} within {b1:g}% below, {c['near2']} {b1:g}–{b2:g}% below.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    if a.summary:
        print(summary(a.scan))
    else:
        print(json.dumps(check(a.scan), indent=1))


if __name__ == "__main__":
    main()
