# NSE NIFTY Buy-Zone / Upside Screener

The NSE (India) sibling of the US screener — same engine and methodology,
retargeted to NIFTY large caps. Pulls 5y of price history plus fundamentals and
analyst targets via Yahoo Finance (`.NS` tickers, `^NSEI` benchmark), ranks
names on a composite of five sub-scores, and surfaces those in a buy zone with
data-backed implied upside. Prices in ₹.

## Run as a webpage (Streamlit)
```bash
pip install -r requirements.txt
streamlit run app.py
```
This opens the dashboard in your browser (default http://localhost:8501).
Click **Fetch data** in the sidebar on first load. The weight sliders re-rank
the universe **live** without re-downloading; **Force refresh** re-pulls from
Yahoo. Tabs: **Rankings** (styled table, CSV + Excel download), **Explore**
(upside-vs-composite and valuation-vs-quality scatters, sector averages),
**Detail** (price + SMA50/200 + analyst target, RSI, sub-scores, fundamentals,
headlines).

## CLI
```bash
python screen.py                 # NIFTY 50, full ranked table
python screen.py --filter        # buy-zone names with >= 20% implied upside
python screen.py --universe wiki --refresh   # live constituents from Wikipedia
python screen.py --news
```
Writes both a CSV and a formatted **.xlsx** (color-scaled composite, frozen
header, % formats) to `output/`.

## The model (knobs in `config.py`)
Composite = weighted blend of five 0–100 percentile sub-scores; weights
renormalize per row over whatever data is present.

| Sub-score | Rewards | Ranked against |
|---|---|---|
| **Analyst** (0.25) | implied upside to mean target (2×) + recommendation | universe |
| **Buy zone** (0.20) | uptrend intact, pulled back, not overbought / falling-knife | rules |
| **Valuation** (0.20) | cheap P/E, fwd P/E, P/S, EV/EBITDA, PEG vs peers | **sector** |
| **Quality** (0.20) | revenue/earnings growth, margins, ROE, low leverage | **sector** |
| **Momentum** (0.15) | 3m/6m return, distance above 200-DMA | universe |

**Buy zone** ("sane entry") and **implied upside** ("room to run") are scored
separately; `--filter` / the actionable count require both.

## NSE-specific caveats
- **Analyst coverage on Yahoo is thinner for Indian names** than US — some
  `targetMeanPrice` / recommendation cells come back blank, so the analyst
  sub-score is sparser. Per-row weight renormalization keeps that from unfairly
  sinking a name, but lean more on valuation/quality/buy-zone here.
- NIFTY 50 constituents rebalance; `--universe wiki` (CLI) or the *wiki* source
  (app) pulls the current list.
- yfinance is unofficial and rate-limits harder from shared cloud IPs. Running
  locally is smoothest; if you deploy to Streamlit Cloud, the 12h disk cache and
  the Fetch button matter more.

## Files
- `config.py` — NIFTY universe, ₹, `^NSEI`, weights, thresholds
- `data.py` — universe + `.NS` suffixing + cached downloads
- `analytics.py` — indicators, features, scoring (shared, market-agnostic)
- `export.py` — formatted .xlsx writer (used by CLI + app)
- `screen.py` — CLI (CSV + XLSX output)
- `app.py` — Streamlit dashboard

Not financial advice — this ranks a shortlist to research, it does not pick.
