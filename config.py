"""
config.py — NSE (India) screener configuration.

Same two-track philosophy as the US version: BUY ZONE (is this a sane entry?)
and UPSIDE (is there a data-backed reason to expect a move?) are scored
separately and only combined in the composite. Retargeted to NSE: tickers carry
the .NS suffix, the benchmark is the Nifty 50 index (^NSEI), and prices are INR.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / caching
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
OUTPUT_DIR = ROOT / "output"
CACHE_TTL_HOURS = 12
HISTORY_PERIOD = "5y"

# Market specifics
SUFFIX = ".NS"            # NSE tickers on Yahoo Finance
BENCHMARK = "^NSEI"       # Nifty 50 index (used for beta)
CURRENCY = "\u20b9"       # ₹

# ---------------------------------------------------------------------------
# Default universe: NIFTY 50 (largest, most liquid NSE names). Constituents
# rebalance periodically — use --universe wiki to pull the live list.
# Stored WITHOUT suffix; data.get_universe appends .NS.
# ---------------------------------------------------------------------------
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC",
 #   "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "BAJFINANCE", "AXISBANK",
 #   "ASIANPAINT", "MARUTI", "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO",
 #   "WIPRO", "NESTLEIND", "ONGC", "NTPC", "POWERGRID", "TATAMOTORS",
 #  "TATASTEEL", "JSWSTEEL", "ADANIENT", "ADANIPORTS", "COALINDIA",
 #  "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "TECHM", "GRASIM", "HINDALCO",
 #   "DRREDDY", "CIPLA", "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO",
 #   "INDUSINDBK", "M&M", "APOLLOHOSP", "BPCL", "TATACONSUM", "LTIM",
 #   "SHRIRAMFIN", "DIVISLAB",
]
DEFAULT_UNIVERSE = NIFTY_50

MIN_PEERS_FOR_SECTOR = 4

# ---------------------------------------------------------------------------
# Composite weights (renormalized per row over available sub-scores)
# ---------------------------------------------------------------------------
WEIGHTS = {
    "analyst_upside": 0.25,
    "buy_zone":       0.20,
    "valuation":      0.20,
    "quality":        0.20,
    "momentum":       0.15,
}

# ---------------------------------------------------------------------------
# Buy-zone heuristics
# ---------------------------------------------------------------------------
BUY_ZONE = {
    "uptrend_sma200_floor": 0.95,
    "falling_knife_sma200": 0.80,
    "rsi_overbought":       65,
    "rsi_floor":            30,
    "pos52w_extended":      0.92,
    "ret3m_knife":         -0.25,
}

MIN_IMPLIED_UPSIDE = 0.20

# Indicator periods
RSI_PERIOD = 14
ATR_PERIOD = 14
SMA_FAST = 50
SMA_SLOW = 200
BETA_WINDOW = 252
