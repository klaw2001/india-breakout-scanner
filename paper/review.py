"""Daily review inputs for Claude: a compact digest (stdout) and a self-contained dashboard (HTML).

    python -m paper.review --date 2026-11-27                 # live days in paper/days/
    python -m paper.review --date 2026-11-26 --replay        # a replay in paper/replays/
Standard library only, so it runs anywhere without installing anything.
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config as C

ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))


def inr(x, signed=False):
    if x is None:
        return "–"
    s = f"{abs(x):,.0f}"
    # Indian grouping
    whole = s.replace(",", "")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    sign = "−" if x < 0 else ("+" if signed and x > 0 else "")
    return f"{sign}₹{s}"


def load_days(src: Path, upto: str):
    days = []
    for p in sorted(src.glob("*.json")):
        if p.stem <= upto:
            try:
                st = json.loads(p.read_text())
                if st.get("status") in ("closed", "no-session"):
                    days.append(st)
            except Exception:  # noqa: BLE001
                pass
    return days


def stats(days):
    trades = [dict(t, date=d["date"]) for d in days for t in d.get("closed", [])]
    nets = [t["net"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    equity, eq = [], C.CAPITAL
    daily = []
    for d in days:
        if d.get("status") != "closed":
            continue
        n = round(sum(t["net"] for t in d.get("closed", [])), 2)
        eq = round(eq + n, 2)
        daily.append(dict(date=d["date"], net=n, trades=len(d.get("closed", [])), equity=eq))
    peak, mdd = C.CAPITAL, 0.0
    for x in daily:
        peak = max(peak, x["equity"])
        mdd = min(mdd, (x["equity"] - peak) / peak * 100)
    filt = {}
    for d in days:
        for w in d.get("whatif", []):
            f = filt.setdefault(w["filter"], dict(filter=w["filter"], count=0, winners=0, total_r=0.0))
            f["count"] += 1
            f["winners"] += w["r"] > 0
            f["total_r"] = round(f["total_r"] + w["r"], 2)
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return dict(
        days=len(daily), trades=len(trades), wins=len(wins), losses=len(losses),
        win_rate=round(len(wins) / len(trades) * 100, 1) if trades else None,
        net=round(sum(nets), 2), gross=round(sum(t["gross"] for t in trades), 2),
        charges=round(sum(t["charges"] for t in trades), 2),
        total_r=round(sum(t["r"] or 0 for t in trades), 2),
        avg_r=round(sum(t["r"] or 0 for t in trades) / len(trades), 2) if trades else None,
        profit_factor=round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        equity=daily[-1]["equity"] if daily else C.CAPITAL, max_dd=round(mdd, 2),
        daily=daily, trades_list=trades, filters=sorted(filt.values(), key=lambda f: -f["count"]),
        exit_reasons=reasons,
    )


def digest(day_st, s, d):
    L = []
    t = day_st.get("closed", [])
    L.append(f"# Paper trading review: {d:%d %b %Y (%a)}")
    if day_st.get("status") == "no-session":
        L.append("No NSE session today (holiday): no trades.")
    else:
        net = sum(x["net"] for x in t)
        exits = {}
        for x in t:
            exits[x["reason"]] = exits.get(x["reason"], 0) + 1
        L.append(f"Watchlist {len(day_st['watchlist'])} stocks (scan of {day_st['watchlist_session']}); "
                 f"breakouts seen {day_st.get('breakouts_seen', '?')}; trades {len(t)} "
                 f"({', '.join(f'{v} {k}' for k, v in exits.items()) or 'none'}); "
                 f"net {inr(net, True)} after {inr(sum(x['charges'] for x in t))} charges; "
                 f"total {sum(x['r'] or 0 for x in t):+.2f}R.")
        if t:
            L.append("\n| stock | in | entry | out | exit | why | net | R |\n|---|---|---|---|---|---|---|---|")
            for x in t:
                L.append(f"| {x['symbol']} | {x['entry_time']} | {x['entry']:.2f} | {x['exit_time']} | {x['exit']:.2f} | "
                         f"{x['reason']} | {inr(x['net'], True)} | {x['r']:+.2f} |")
        wi = day_st.get("whatif", [])
        if wi:
            L.append("\nSkipped breakouts today, if taken at the first signal with the same exits:")
            agg = {}
            for w in wi:
                a = agg.setdefault(w["filter"], [0, 0, 0.0])
                a[0] += 1
                a[1] += w["r"] > 0
                a[2] += w["r"]
            L.append("| filter | skipped | would-be winners | total R |\n|---|---|---|---|")
            for k, (n, wn, r) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
                L.append(f"| {k} | {n} | {wn} | {r:+.2f} |")
            best = sorted(wi, key=lambda w: -w["r"])[:3]
            worst = sorted(wi, key=lambda w: w["r"])[:3]
            L.append("Best missed: " + "; ".join(f"{w['symbol']} {w['r']:+.2f}R ({w['filter']}, {w['signal_time']})" for w in best))
            L.append("Worst avoided: " + "; ".join(f"{w['symbol']} {w['r']:+.2f}R ({w['filter']}, {w['signal_time']})" for w in worst))
        if day_st.get("whatif_error"):
            L.append(f"(what-if failed: {day_st['whatif_error']})")
    L.append(f"\n## Since start ({s['days']} trading days)")
    if s["trades"]:
        L.append(f"Trades {s['trades']}, win rate {s['win_rate']}%, avg {s['avg_r']:+.2f}R, total {s['total_r']:+.2f}R, "
                 f"net {inr(s['net'], True)} (charges {inr(s['charges'])}), equity {inr(s['equity'])}, "
                 f"max drawdown {s['max_dd']}%, profit factor {s['profit_factor'] or '–'}. "
                 f"Exits: {', '.join(f'{v} {k}' for k, v in s['exit_reasons'].items())}.")
    else:
        L.append("No trades yet.")
    if s["filters"]:
        L.append("All skipped breakouts so far, by filter: " + "; ".join(
            f"{f['filter']} {f['count']} skipped, {f['winners']} would have won, {f['total_r']:+.2f}R" for f in s["filters"]))
    L.append(f"\nRules: risk {inr(C.RISK_PER_TRADE)}/trade, max {C.MAX_OPEN} open, entries {C.FIRST_ENTRY}-{C.LAST_ENTRY}, "
             f"square-off {C.SQUARE_OFF}, volume filter {'on' if C.REQUIRE_VOLUME else 'off'} "
             f"(opening candle {C.OPEN_CANDLE_VOL_MULT:g}x), chase limit {C.MAX_CHASE_ATR} ATR, min reward {C.MIN_RR}R.")
    return "\n".join(L)


# ---------------------------------------------------------------- dashboard
HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper trading dashboard</title>
<style>
.viz-root{color-scheme:light;--page:#f9f9f9;--surface-1:#ffffff;--text-primary:#191919;--text-secondary:#666666;
 --grid:#e7e7e7;--axis:#c2c2c2;--series-1:#257de0;--pos:#257de0;--neg:#ec4647;--ring:rgba(11,11,11,.10);--good-text:#006c10;--bad-text:#b42318}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--page:#0b0b0b;--surface-1:#191919;
 --text-primary:#efefef;--text-secondary:#9c9c9c;--grid:#303030;--axis:#474747;--series-1:#338ced;--pos:#338ced;--neg:#eb6263;--ring:rgba(255,255,255,.10);--good-text:#53c556;--bad-text:#f08a8a}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--page:#0b0b0b;--surface-1:#191919;--text-primary:#efefef;--text-secondary:#9c9c9c;
 --grid:#303030;--axis:#474747;--series-1:#338ced;--pos:#338ced;--neg:#eb6263;--ring:rgba(255,255,255,.10);--good-text:#53c556;--bad-text:#f08a8a}
*{box-sizing:border-box}body{margin:0}
.viz-root{background:var(--page);color:var(--text-primary);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:28px 20px 48px;min-height:100vh}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px;font-weight:600}.sub{color:var(--text-secondary);margin:0 0 20px}
.card{background:var(--surface-1);border:1px solid var(--ring);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 2px;font-weight:600}.card .note{color:var(--text-secondary);font-size:12.5px;margin:0 0 10px}
.top{display:grid;grid-template-columns:minmax(220px,1.1fr) 3fr;gap:16px;margin-bottom:16px}
.hero .label{color:var(--text-secondary);font-size:13px}.hero .value{font-size:48px;font-weight:600;line-height:1.1;margin:6px 0}
.hero .delta{font-size:13px;color:var(--text-secondary)}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.tile .label{color:var(--text-secondary);font-size:12.5px}.tile .value{font-size:22px;font-weight:600;margin-top:2px}
.up{color:var(--good-text)}.down{color:var(--bad-text)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--text-secondary);font:11px system-ui,-apple-system,"Segoe UI",sans-serif}
table{width:100%;border-collapse:collapse;font-size:13px}th{color:var(--text-secondary);font-weight:500;text-align:left;border-bottom:1px solid var(--grid);padding:6px 8px}
td{padding:6px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}td.n,th.n{text-align:right}
.tip{position:fixed;pointer-events:none;background:var(--surface-1);border:1px solid var(--ring);border-radius:8px;padding:8px 10px;
 box-shadow:0 4px 16px rgba(0,0,0,.12);font-size:12.5px;display:none;z-index:9}
.tip b{display:block;font-size:14px}.tip .k{display:inline-block;width:12px;height:2px;vertical-align:middle;margin-right:6px}
.empty{color:var(--text-secondary);padding:12px 0}
@media (max-width:760px){.top,.grid2{grid-template-columns:1fr}.tiles{grid-template-columns:repeat(2,1fr)}}
</style></head>
<body><div class="viz-root"><div class="wrap">
<h1>Paper trading: intraday breakouts</h1>
<p class="sub" id="sub"></p>
<div class="top">
 <div class="card hero"><div class="label">Net P&amp;L since start</div><div class="value" id="hero"></div><div class="delta" id="herodelta"></div></div>
 <div class="tiles" id="tiles"></div>
</div>
<div class="card"><h2>Equity</h2><p class="note">Paper capital after each trading day, net of charges</p><div id="eq"></div></div>
<div class="grid2">
 <div class="card"><h2>Daily net P&amp;L</h2><p class="note">Blue = profit day, red = loss day</p><div id="daily"></div></div>
 <div class="card"><h2>Skipped breakouts: total R if taken</h2><p class="note">Each filter's skipped signals, replayed with the same exits. Positive = the filter cost profit.</p><div id="filt"></div></div>
</div>
<div class="card"><h2 id="todayh">Latest day's trades</h2><div id="today"></div></div>
<div class="card"><h2>Latest day's skipped breakouts</h2><p class="note">What each would have done if taken at its first signal</p><div id="skipped"></div></div>
<div class="card"><h2>All trades</h2><div id="all"></div></div>
</div><div class="tip" id="tip"></div></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const fmt = new Intl.NumberFormat("en-IN", {maximumFractionDigits: 0});
const rupee = (x, s) => (x < 0 ? "−" : (s && x > 0 ? "+" : "")) + "₹" + fmt.format(Math.abs(x));
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const h = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const tip = document.getElementById("tip");
function showTip(ev, title, lines, color) {
  tip.replaceChildren(); const b = h("b", title); tip.appendChild(b);
  lines.forEach(l => { const d = h("div"); if (color) { const k = h("span", "", "k"); k.style.background = color; d.appendChild(k); } d.appendChild(document.createTextNode(l)); tip.appendChild(d); });
  tip.style.display = "block"; const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + "px"; tip.style.top = (ev.clientY + 14) + "px";
}
const hideTip = () => tip.style.display = "none";
function ticks(lo, hi, n) { const span = hi - lo || Math.abs(hi) || 1; const step0 = span / n; const p = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * p).find(s => s >= step0); const out = []; for (let v = Math.floor(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6)); return out; }
const compact = v => Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(Math.abs(v) >= 1e6 ? 1 : 2).replace(/\.?0+$/, "") + "L" : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1).replace(/\.0$/, "") + "K" : String(Math.round(v));

document.getElementById("sub").textContent = `As of ${D.asof} · ${D.s.days} trading day${D.s.days === 1 ? "" : "s"} · ₹${fmt.format(D.rules.capital)} paper capital, ₹${fmt.format(D.rules.risk)} risk per trade, max ${D.rules.max_open} open`;
const hero = document.getElementById("hero"); hero.textContent = rupee(D.s.net, true); hero.className = "value " + (D.s.net > 0 ? "up" : D.s.net < 0 ? "down" : "");
document.getElementById("herodelta").textContent = `Equity ₹${fmt.format(D.s.equity)} (${((D.s.equity / D.rules.capital - 1) * 100).toFixed(2)}% on capital)`;
const tiles = [["Trades", D.s.trades], ["Win rate", D.s.win_rate == null ? "–" : D.s.win_rate + "%"], ["Average R", D.s.avg_r == null ? "–" : (D.s.avg_r > 0 ? "+" : "") + D.s.avg_r.toFixed(2) + "R"],
  ["Profit factor", D.s.profit_factor == null ? "–" : D.s.profit_factor.toFixed(2)], ["Max drawdown", D.s.max_dd.toFixed(2) + "%"], ["Charges paid", rupee(D.s.charges)]];
const tw = document.getElementById("tiles"); tiles.forEach(([l, v]) => { const c = h("div", undefined, "card tile"); c.style.margin = 0; c.appendChild(h("div", l, "label")); c.appendChild(h("div", String(v), "value")); tw.appendChild(c); });

// ---- equity line
(function () {
  const host = document.getElementById("eq"); const pts = [{date: "start", equity: D.rules.capital}].concat(D.s.daily);
  if (D.s.daily.length === 0) { host.appendChild(h("div", "No completed trading days yet.", "empty")); return; }
  const W = 1000, H = 260, m = {l: 64, r: 24, t: 12, b: 28}; const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Equity after each trading day"}, host);
  const vals = pts.map(p => p.equity); let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.15 || D.rules.capital * 0.005; lo -= pad; hi += pad;
  const tk = ticks(lo, hi, 4); lo = Math.min(lo, tk[0]); hi = Math.max(hi, tk[tk.length - 1]);
  const x = i => m.l + (pts.length === 1 ? 0 : i * (W - m.l - m.r) / (pts.length - 1)); const y = v => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);
  tk.forEach(v => { el("line", {x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "var(--grid)", "stroke-width": 1}, svg); const t = el("text", {x: m.l - 8, y: y(v) + 4, "text-anchor": "end"}, svg); t.textContent = "₹" + compact(v); });
  const step = Math.max(1, Math.ceil(pts.length / 8)); pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1) { const t = el("text", {x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}, svg); t.textContent = p.date === "start" ? "Start" : p.date.slice(5); } });
  const d = pts.map((p, i) => (i ? "L" : "M") + x(i) + " " + y(p.equity)).join(" ");
  el("path", {d: d + ` L ${x(pts.length - 1)} ${H - m.b} L ${x(0)} ${H - m.b} Z`, fill: "var(--series-1)", "fill-opacity": 0.1, stroke: "none"}, svg);
  el("path", {d, fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"}, svg);
  const last = pts.length - 1; el("circle", {cx: x(last), cy: y(pts[last].equity), r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2}, svg);
  const cross = el("line", {y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden"}, svg);
  const dot = el("circle", {r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden"}, svg);
  const hit = el("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent", tabindex: 0}, svg);
  const move = ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) * W / r.width; const i = Math.max(0, Math.min(last, Math.round((px - m.l) / ((W - m.l - m.r) / Math.max(1, last)))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible"); dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(pts[i].equity)); dot.setAttribute("visibility", "visible");
    const p = pts[i]; showTip(ev, "₹" + fmt.format(p.equity), [p.date === "start" ? "Starting capital" : `${p.date} · day ${rupee(p.net, true)} · ${p.trades} trades`], "var(--series-1)"); };
  hit.addEventListener("pointermove", move); hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
})();

// ---- generic diverging bars (vertical columns or horizontal bars)
function diverging(hostId, items, horizontal, emptyText) {
  const host = document.getElementById(hostId); if (!items.length) { host.appendChild(h("div", emptyText, "empty")); return; }
  const W = 480, H = horizontal ? Math.max(120, items.length * 44 + 30) : 240; const m = horizontal ? {l: 92, r: 64, t: 6, b: 22} : {l: 56, r: 12, t: 12, b: 28};
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img"}, host); const vals = items.map(d => d.v); let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (lo === hi) hi = 1; const tk = ticks(lo, hi, 4); lo = Math.min(lo, tk[0]); hi = Math.max(hi, tk[tk.length - 1]);
  const len = horizontal ? W - m.l - m.r : H - m.t - m.b; const pos = v => (v - lo) / (hi - lo) * len; const band = (horizontal ? H - m.t - m.b : W - m.l - m.r) / items.length; const thick = Math.min(24, band * 0.6);
  tk.forEach(v => { if (horizontal) { const X = m.l + pos(v); el("line", {x1: X, x2: X, y1: m.t, y2: H - m.b, stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1}, svg); const t = el("text", {x: X, y: H - 6, "text-anchor": "middle"}, svg); t.textContent = items.unit === "R" ? (v > 0 ? "+" : "") + v + "R" : compact(v); }
    else { const Y = H - m.b - pos(v); el("line", {x1: m.l, x2: W - m.r, y1: Y, y2: Y, stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1}, svg); const t = el("text", {x: m.l - 8, y: Y + 4, "text-anchor": "end"}, svg); t.textContent = "₹" + compact(v); } });
  items.forEach((d, i) => { const z = pos(0), p = pos(d.v), a = Math.min(z, p), L = Math.max(Math.abs(p - z), 1.5); const c = d.v >= 0 ? "var(--pos)" : "var(--neg)"; const r = Math.min(4, L / 2, thick / 2);
    let path; if (horizontal) { const y0 = m.t + i * band + (band - thick) / 2, x0 = m.l + a, x1 = x0 + L;
      path = d.v >= 0 ? `M${x0} ${y0}H${x1 - r}Q${x1} ${y0} ${x1} ${y0 + r}V${y0 + thick - r}Q${x1} ${y0 + thick} ${x1 - r} ${y0 + thick}H${x0}Z` : `M${x1} ${y0}H${x0 + r}Q${x0} ${y0} ${x0} ${y0 + r}V${y0 + thick - r}Q${x0} ${y0 + thick} ${x0 + r} ${y0 + thick}H${x1}Z`;
      const lab = el("text", {x: m.l - 8, y: y0 + thick / 2 + 4, "text-anchor": "end"}, svg); lab.textContent = d.label;
      const val = el("text", {x: d.v >= 0 ? x1 + 6 : x0 - 6, y: y0 + thick / 2 + 4, "text-anchor": d.v >= 0 ? "start" : "end", style: "fill:var(--text-primary)"}, svg); val.textContent = d.valueText; }
    else { const x0 = m.l + i * band + (band - thick) / 2, yb = H - m.b - a, yt = yb - L;
      path = d.v >= 0 ? `M${x0} ${yb}V${yt + r}Q${x0} ${yt} ${x0 + r} ${yt}H${x0 + thick - r}Q${x0 + thick} ${yt} ${x0 + thick} ${yt + r}V${yb}Z` : `M${x0} ${yt}V${yb - r}Q${x0} ${yb} ${x0 + r} ${yb}H${x0 + thick - r}Q${x0 + thick} ${yb} ${x0 + thick} ${yb - r}V${yt}Z`;
      if (items.length <= 12 || i % Math.ceil(items.length / 12) === 0) { const t = el("text", {x: x0 + thick / 2, y: H - 8, "text-anchor": "middle"}, svg); t.textContent = d.label; } }
    const mark = el("path", {d: path, fill: c, tabindex: 0}, svg);
    const hitR = horizontal ? el("rect", {x: m.l, y: m.t + i * band, width: W - m.l - m.r, height: band, fill: "transparent"}, svg) : el("rect", {x: m.l + i * band, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent"}, svg);
    [mark, hitR].forEach(t => { t.addEventListener("pointermove", ev => { mark.setAttribute("fill-opacity", .8); showTip(ev, d.valueText, d.tip, c); }); t.addEventListener("pointerleave", () => { mark.setAttribute("fill-opacity", 1); hideTip(); }); }); });
}
diverging("daily", D.s.daily.map(d => ({label: d.date.slice(5), v: d.net, valueText: rupee(d.net, true), tip: [`${d.date} · ${d.trades} trades`, `Equity ₹${fmt.format(d.equity)}`]})), false, "No completed trading days yet.");
const fi = D.s.filters.map(f => ({label: f.filter, v: f.total_r, valueText: (f.total_r > 0 ? "+" : "") + f.total_r.toFixed(2) + "R", tip: [`${f.count} skipped, ${f.winners} would have won`, `Filter: ${f.filter}`]})); fi.unit = "R";
diverging("filt", fi, true, "No skipped breakouts recorded yet.");

// ---- tables
function table(hostId, cols, rows, empty) { const host = document.getElementById(hostId); if (!rows.length) { host.appendChild(h("div", empty, "empty")); return; }
  const t = h("table"); const tr = h("tr"); cols.forEach(c => tr.appendChild(h("th", c[0], c[2] ? "n" : ""))); const th = h("thead"); th.appendChild(tr); t.appendChild(th);
  const tb = h("tbody"); rows.forEach(r => { const row = h("tr"); cols.forEach(c => { const v = c[1](r); const td = h("td", v.text ?? v, c[2] ? "n" : ""); if (v.cls) td.classList.add(v.cls); row.appendChild(td); }); tb.appendChild(row); }); t.appendChild(tb); host.appendChild(t); }
const money = v => ({text: rupee(v, true), cls: v > 0 ? "up" : v < 0 ? "down" : ""}); const rr = v => ({text: (v > 0 ? "+" : "") + (v ?? 0).toFixed(2) + "R", cls: v > 0 ? "up" : v < 0 ? "down" : ""});
document.getElementById("todayh").textContent = D.latest ? `Latest day's trades (${D.latest.date})` : "Latest day's trades";
const tcols = [["Stock", r => r.symbol], ["In", r => r.entry_time], ["Entry", r => r.entry.toFixed(2), 1], ["Qty", r => String(r.qty), 1], ["Stop", r => r.stop.toFixed(2), 1], ["Target", r => r.target.toFixed(2), 1],
  ["Out", r => r.exit_time], ["Exit", r => r.exit.toFixed(2), 1], ["Why", r => r.reason], ["Net", r => money(r.net), 1], ["R", r => rr(r.r), 1]];
table("today", tcols, D.latest ? D.latest.closed : [], "No trades on the latest day.");
table("skipped", [["Stock", r => r.symbol], ["Signal", r => r.signal_time], ["Skipped for", r => r.filter], ["Entry", r => r.entry.toFixed(2), 1], ["Out", r => r.exit_time], ["Exit", r => r.exit.toFixed(2), 1], ["How", r => r.exit_reason], ["R", r => rr(r.r), 1]],
  D.latest ? (D.latest.whatif || []).slice().sort((a, b) => b.r - a.r) : [], "No skipped breakouts on the latest day.");
table("all", [["Date", r => r.date]].concat(tcols), D.s.trades_list.slice().reverse().slice(0, 100), "No trades yet.");
</script></body></html>
"""


def dashboard(days, s, latest, asof) -> str:
    data = dict(asof=asof, rules=dict(capital=C.CAPITAL, risk=C.RISK_PER_TRADE, max_open=C.MAX_OPEN), s=s,
                latest=dict(date=latest["date"], closed=latest.get("closed", []), whatif=latest.get("whatif", [])) if latest else None)
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    return HTML.replace("__DATA__", blob)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    ap.add_argument("--replay", action="store_true", help="read paper/replays instead of paper/days")
    ap.add_argument("--out", help="dashboard path (default paper/dashboard.html)")
    a = ap.parse_args(argv)
    d = date.fromisoformat(a.date) if a.date else datetime.now(IST).date()
    src = ROOT / "paper" / ("replays" if a.replay else "days")
    days = load_days(src, str(d))
    day_file = src / f"{d}.json"
    if not day_file.exists():
        print(f"NO_DAY_FILE: {day_file.relative_to(ROOT)} does not exist (server did not push today's close, "
              f"or no session).")
        latest = days[-1] if days else None
    else:
        latest = json.loads(day_file.read_text())
        if latest.get("status") == "open":
            print("DAY_NOT_CLOSED: today's file exists but the close step has not run yet.")
    s = stats(days)
    if latest and day_file.exists():
        print(digest(latest, s, d))
    out = Path(a.out) if a.out else ROOT / "paper" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dashboard(days, s, latest, str(d)))
    print(f"\nDASHBOARD: {out}")


if __name__ == "__main__":
    main()
