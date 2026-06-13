#!/usr/bin/env python3
"""
audit.py — verify the data-quality fix across the whole universe.

Fetches every NIFTY 50 name and prints a table comparing Yahoo's raw
`revenueGrowth` snapshot against the cleaned value, so you can SEE which
tickers had artifacts (like INDUSINDBK's 272%) and how they were handled.

Run:  python audit.py            (needs internet; uses the 12h cache)
      python audit.py --refresh
"""

import argparse
import pandas as pd

import config
import data

pd.set_option("display.width", 160)
pd.set_option("display.max_rows", 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    tickers = data.get_universe("nifty50", args.top)
    funds = data.get_fundamentals(tickers, refresh=args.refresh)

    rows = []
    for t, f in funds.items():
        raw = f.get("revenueGrowth_raw")
        clean_v = f.get("revenueGrowth")
        rows.append({
            "ticker": t.replace(config.SUFFIX, ""),
            "financial": "Y" if f.get("is_financial") else "",
            "raw_%": round(raw * 100, 1) if isinstance(raw, (int, float)) and pd.notna(raw) else None,
            "clean_%": round(clean_v * 100, 1) if isinstance(clean_v, (int, float)) and pd.notna(clean_v) else None,
            "source": f.get("revenueGrowth_source"),
            "roe_%": round(f.get("returnOnEquity") * 100, 1) if pd.notna(f.get("returnOnEquity")) else None,
        })
    df = pd.DataFrame(rows).set_index("ticker")

    # flag rows where the raw snapshot was an artifact we corrected/dropped
    def flag(r):
        if r["raw_%"] is None:
            return ""
        if r["source"] in ("annual_stmt",) and abs(r["raw_%"]) > 60:
            return "  <-- raw snapshot suspicious; replaced w/ annual"
        if r["source"] == "dropped":
            return "  <-- raw dropped (artifact / bad base)"
        return ""
    df["note"] = [flag(r) for _, r in df.iterrows()]

    print("\nRevenue-growth audit (raw Yahoo snapshot vs cleaned):\n")
    print(df.sort_values("raw_%", key=lambda s: s.abs(), ascending=False, na_position="last").to_string())

    n_fixed = (df["source"].isin(["annual_stmt", "dropped"]) &
               df["raw_%"].abs().gt(60)).sum()
    print(f"\nFinancials flagged: {(df['financial']=='Y').sum()}  |  "
          f"suspicious raw snapshots corrected/dropped: {int(n_fixed)}")
    print("Look for the INDUSINDBK row: raw_% ~272 should now show a sane clean_% "
          "(or '—' if dropped).")


if __name__ == "__main__":
    main()
