#!/usr/bin/env python3
"""
screen.py — run the NSE screener from the command line.

Examples
--------
  python screen.py                       # NIFTY 50, full ranked table
  python screen.py --filter              # buy-zone names with >= 20% upside
  python screen.py --universe wiki --refresh
  python screen.py --news
  python screen.py --min-upside 0.25 --filter

Writes both a CSV and a formatted XLSX to ./output/.
"""

import argparse
from datetime import datetime

import pandas as pd

import config
import data
import analytics
import export

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

DISPLAY = export.DISPLAY
PCT_COLS = ["implied_upside", "pos_52w", "dist_sma200", "rev_growth", "roe", "ann_vol"]


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in PCT_COLS:
        if c in d:
            d[c] = (d[c] * 100).round(1)
    for c in ["price", "target_mean", "fwd_pe", "rsi", "beta"]:
        if c in d:
            d[c] = d[c].round(2)
    return d


def main() -> None:
    p = argparse.ArgumentParser(description="NSE NIFTY buy-zone / upside screener")
    p.add_argument("--universe", choices=["nifty50", "wiki"], default="nifty50")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--news", action="store_true")
    p.add_argument("--filter", action="store_true")
    p.add_argument("--min-upside", type=float, default=config.MIN_IMPLIED_UPSIDE)
    args = p.parse_args()

    cur = config.CURRENCY
    print(f"[1/4] Resolving universe ({args.universe})...")
    tickers = data.get_universe(args.universe, args.top)
    print(f"      {len(tickers)} tickers.")

    print("[2/4] Downloading 5y prices (cached)...")
    prices = data.get_prices(tickers, refresh=args.refresh)

    print("[3/4] Downloading fundamentals / analyst targets (cached)...")
    fundamentals = data.get_fundamentals(tickers, workers=args.workers,
                                         with_news=args.news, refresh=args.refresh)

    print("[4/4] Building features and scoring...")
    feats = analytics.build_features(prices, fundamentals)
    ranked = analytics.score(feats)

    actionable = ranked[(ranked["buy_zone"]) & (ranked["implied_upside"] >= args.min_upside)]

    view = actionable if args.filter else ranked
    title = (f"ACTIONABLE: buy-zone & upside >= {args.min_upside:.0%} ({len(actionable)})"
             if args.filter else f"ALL {len(ranked)} NAMES — ranked by composite")

    out = _fmt(view[[c for c in DISPLAY if c in view.columns]])
    print("\n" + "=" * 100)
    print(title + f"   (prices in {cur})")
    print("=" * 100)
    print(out.to_string())

    if not args.filter and len(actionable):
        print(f"\n>>> {len(actionable)} names clear the actionable filter: "
              f"{', '.join(actionable.index.tolist())}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = config.OUTPUT_DIR / f"nse_screen_{stamp}.csv"
    xlsx_path = config.OUTPUT_DIR / f"nse_screen_{stamp}.xlsx"
    ranked.to_csv(csv_path)
    with open(xlsx_path, "wb") as f:
        f.write(export.to_excel_bytes(ranked))
    print(f"\nSaved: {csv_path}\n       {xlsx_path}")

    if args.news:
        print("\n--- Recent headlines (buy-zone names) ---")
        for t in actionable.index[:10]:
            items = fundamentals.get(t, {}).get("news", [])
            if items:
                print(f"\n{t}:")
                for it in items[:3]:
                    print(f"  - {it.get('title')}  [{it.get('publisher')}]")


if __name__ == "__main__":
    main()
