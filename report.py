#!/usr/bin/env python3
"""
report.py — generate a SELF-CONTAINED interactive HTML dashboard.

Why this exists: if Streamlit won't render in your environment, this sidesteps
it entirely. No server, no port, no websocket — it writes one `nse_report.html`
file with the Plotly charts and a sortable ranking table embedded inline. Open
it by double-clicking; works offline.

Usage:
  python report.py                 # fetch NIFTY 50, write nse_report.html
  python report.py --refresh
"""

import argparse
import webbrowser
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

import config
import data
import analytics
import export

DISPLAY = export.DISPLAY
CUR = config.CURRENCY


def _fmt_cell(col, v):
    if pd.isna(v):
        return "—"
    if col in ("price", "target_mean"):
        return f"{CUR}{v:,.2f}"
    if col in ("implied_upside", "pos_52w", "rev_growth", "roe", "ann_vol"):
        return f"{v*100:.1f}%"
    if col == "dist_sma200":
        return f"{v*100:+.1f}%"
    if col in ("fwd_pe", "beta"):
        return f"{v:.2f}"
    if col == "rsi" or col.startswith("score_") or col == "composite":
        return f"{v:.0f}" if col != "composite" else f"{v:.1f}"
    if col == "buy_zone":
        return "✅" if v else ""
    return str(v)


def _table_html(ranked: pd.DataFrame) -> str:
    cols = ["ticker"] + [c for c in DISPLAY if c in ranked.columns]
    df = ranked.reset_index()[cols]
    comp_min, comp_max = df["composite"].min(), df["composite"].max()
    rng = (comp_max - comp_min) or 1.0

    head = "".join(f"<th onclick='sortTable({i})'>{c}</th>" for i, c in enumerate(cols))
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            disp = _fmt_cell(c, r[c]) if c != "ticker" else str(r[c]).replace(config.SUFFIX, "")
            style = ""
            sort_val = r[c] if pd.notna(r[c]) else -1e9
            if c == "composite" and pd.notna(r[c]):
                t = (r[c] - comp_min) / rng
                g = int(220 - t * 150)
                style = f"background:rgb({g},{int(200+ t*30)},{g});font-weight:600"
            tds.append(f"<td data-sort='{sort_val}' style='{style}'>{disp}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table id='tbl'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _scatter(ranked: pd.DataFrame) -> str:
    pf = ranked.reset_index()
    fig = go.Figure()
    for sec, g in pf.groupby("sector"):
        fig.add_trace(go.Scatter(
            x=g["composite"], y=g["implied_upside"] * 100, mode="markers+text",
            text=[t.replace(config.SUFFIX, "") for t in g["ticker"]],
            textposition="top center", name=str(sec)))
    fig.update_layout(height=520, xaxis_title="Composite score",
                      yaxis_title="Implied upside %", legend=dict(font=dict(size=9)),
                      margin=dict(t=20), title="Implied upside vs Composite")
    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_html(ranked: pd.DataFrame, min_upside: float = config.MIN_IMPLIED_UPSIDE) -> str:
    actionable = ranked[(ranked["buy_zone"]) & (ranked["implied_upside"] >= min_upside)]
    med = ranked["implied_upside"].median()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = f"""
      <div class='cards'>
        <div class='card'><div class='n'>{len(ranked)}</div><div class='l'>Universe</div></div>
        <div class='card'><div class='n'>{int(ranked['buy_zone'].sum())}</div><div class='l'>In buy zone</div></div>
        <div class='card'><div class='n'>{len(actionable)}</div><div class='l'>Actionable ≥{min_upside:.0%}</div></div>
        <div class='card'><div class='n'>{med*100:.1f}%</div><div class='l'>Median upside</div></div>
      </div>"""

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<title>NSE NIFTY Screener</title>
<script>{get_plotlyjs()}</script>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1a1a1a;background:#fafafa}}
 h1{{margin:0 0 2px}} .sub{{color:#666;margin-bottom:18px}}
 .cards{{display:flex;gap:14px;margin:18px 0}}
 .card{{background:#fff;border:1px solid #e3e3e3;border-radius:10px;padding:14px 20px;min-width:120px}}
 .card .n{{font-size:26px;font-weight:700;color:#1B5E20}} .card .l{{color:#777;font-size:13px}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
 th,td{{padding:7px 9px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap}}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
 th{{background:#1B5E20;color:#fff;cursor:pointer;position:sticky;top:0}}
 th:hover{{background:#2E7D32}} tr:hover td{{background:#f5fbf5}}
 .wrap{{max-height:640px;overflow:auto;border:1px solid #e3e3e3;border-radius:10px}}
 .note{{color:#888;font-size:12px;margin-top:10px}}
</style></head><body>
<h1>🇮🇳 NSE NIFTY Buy-Zone / Upside Screener</h1>
<div class='sub'>Generated {stamp} · prices in ₹ · click any column header to sort · not financial advice</div>
{cards}
<div id='chart'>{_scatter(ranked)}</div>
<h3>Rankings</h3>
<div class='wrap'>{_table_html(ranked)}</div>
<div class='note'>Composite blends analyst upside, buy-zone, sector-relative valuation &amp; quality, and momentum.</div>
<script>
let dir={{}};
function sortTable(n){{
  const tb=document.getElementById('tbl'),rows=[...tb.tBodies[0].rows];
  dir[n]=!dir[n];
  rows.sort((a,b)=>{{
    let x=parseFloat(a.cells[n].dataset.sort),y=parseFloat(b.cells[n].dataset.sort);
    if(isNaN(x)) x=a.cells[n].innerText, y=b.cells[n].innerText, x=x.localeCompare(y);
    else x=x-y;
    return dir[n]?x:-x;
  }});
  rows.forEach(r=>tb.tBodies[0].appendChild(r));
}}
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["nifty50", "wiki"], default="nifty50")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--min-upside", type=float, default=config.MIN_IMPLIED_UPSIDE)
    ap.add_argument("--open", action="store_true", help="open in browser when done")
    args = ap.parse_args()

    tickers = data.get_universe(args.universe, args.top)
    print(f"Fetching {len(tickers)} names...")
    prices = data.get_prices(tickers, refresh=args.refresh)
    funds = data.get_fundamentals(tickers, refresh=args.refresh)
    feats = analytics.build_features(prices, funds)
    ranked = analytics.score(feats)

    html = build_html(ranked, args.min_upside)
    out = config.ROOT / "nse_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({out.stat().st_size//1024} KB)")
    print("Open it by double-clicking, or: file://" + str(out))
    if args.open:
        webbrowser.open("file://" + str(out))


if __name__ == "__main__":
    main()
