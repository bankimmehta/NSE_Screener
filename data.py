"""
data.py — NSE data layer (network + disk cache).

Identical structure to the US version; the only NSE-specific bits are universe
resolution (NIFTY 50 default / live Wikipedia pull) and automatic .NS suffixing.
yfinance serves NSE names as TICKER.NS and the Nifty index as ^NSEI.
"""

import time
import pickle
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

import config

warnings.simplefilter("ignore", category=FutureWarning)
config.CACHE_DIR.mkdir(exist_ok=True)
config.OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
def _with_suffix(sym: str) -> str:
    sym = sym.strip().upper()
    if sym.startswith("^"):          # index, leave alone
        return sym
    return sym if sym.endswith(config.SUFFIX) else sym + config.SUFFIX


def get_universe(kind: str = "nifty50", top: int = 50) -> list[str]:
    """Return NSE tickers (with .NS suffix).

    kind="nifty50" -> curated NIFTY 50 from config
    kind="wiki"    -> live NIFTY 50 constituents scraped from Wikipedia
    """
    if kind in ("nifty50", "default"):
        return [_with_suffix(s) for s in config.DEFAULT_UNIVERSE[:top]]

    if kind == "wiki":
        url = "https://en.wikipedia.org/wiki/NIFTY_50"
        try:
            tables = pd.read_html(url)
            syms = None
            for tbl in tables:
                cols = [str(c).lower() for c in tbl.columns]
                for cand in ("symbol", "ticker"):
                    if cand in cols:
                        syms = tbl[tbl.columns[cols.index(cand)]].astype(str).tolist()
                        break
                if syms:
                    break
            if not syms:
                raise ValueError("no symbol column found")
            return [_with_suffix(s) for s in syms][:top]
        except Exception as e:  # noqa: BLE001
            print(f"[universe] Wikipedia fetch failed ({e}); using NIFTY 50 list.")
            return [_with_suffix(s) for s in config.DEFAULT_UNIVERSE[:top]]

    raise ValueError(f"Unknown universe kind: {kind}")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _fresh(path) -> bool:
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < config.CACHE_TTL_HOURS


# ---------------------------------------------------------------------------
# Prices (batched)
# ---------------------------------------------------------------------------
def get_prices(tickers: list[str], refresh: bool = False) -> dict[str, pd.DataFrame]:
    cache = config.CACHE_DIR / "prices.pkl"
    if not refresh and _fresh(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)

    symbols = list(dict.fromkeys(tickers + [config.BENCHMARK]))
    raw = yf.download(symbols, period=config.HISTORY_PERIOD, auto_adjust=True,
                      group_by="ticker", threads=True, progress=False)

    out: dict[str, pd.DataFrame] = {}
    for t in symbols:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(how="all")
            if len(df) > 50:
                out[t] = df
        except Exception:  # noqa: BLE001
            continue

    with open(cache, "wb") as f:
        pickle.dump(out, f)
    return out


# ---------------------------------------------------------------------------
# Fundamentals + analyst + news (per ticker)
# ---------------------------------------------------------------------------
_INFO_KEYS = [
    "shortName", "sector", "industry", "marketCap", "currentPrice",
    "trailingPE", "forwardPE", "priceToSalesTrailing12Months", "pegRatio",
    "enterpriseToEbitda", "revenueGrowth", "earningsGrowth",
    "earningsQuarterlyGrowth", "profitMargins", "returnOnEquity",
    "debtToEquity", "freeCashflow", "beta",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "recommendationMean", "numberOfAnalystOpinions",
]


def _safe_info(tk: yf.Ticker) -> dict:
    try:
        return tk.get_info() or {}
    except Exception:  # noqa: BLE001
        try:
            return tk.info or {}
        except Exception:  # noqa: BLE001
            return {}


def _analyst_fallback(tk: yf.Ticker, info: dict) -> dict:
    if info.get("targetMeanPrice"):
        return info
    try:
        apt = tk.get_analyst_price_targets()
        if apt:
            info.setdefault("targetMeanPrice", apt.get("mean"))
            info.setdefault("targetHighPrice", apt.get("high"))
            info.setdefault("targetLowPrice", apt.get("low"))
    except Exception:  # noqa: BLE001
        pass
    return info


def _fetch_one(ticker: str, with_news: bool) -> tuple[str, dict]:
    tk = yf.Ticker(ticker)
    info = _safe_info(tk)
    info = _analyst_fallback(tk, info)
    rec = {k: info.get(k, np.nan) for k in _INFO_KEYS}

    try:
        fi = tk.fast_info
        if not rec.get("currentPrice") or pd.isna(rec["currentPrice"]):
            rec["currentPrice"] = fi.get("last_price")
        if not rec.get("marketCap") or pd.isna(rec["marketCap"]):
            rec["marketCap"] = fi.get("market_cap")
    except Exception:  # noqa: BLE001
        pass

    rec["news"] = []
    if with_news:
        try:
            for it in (tk.news or [])[:8]:
                c = it.get("content", it)
                rec["news"].append({
                    "title": c.get("title"),
                    "publisher": (c.get("provider") or {}).get("displayName")
                                 if isinstance(c.get("provider"), dict) else c.get("publisher"),
                    "link": (c.get("canonicalUrl") or {}).get("url")
                            if isinstance(c.get("canonicalUrl"), dict) else c.get("link"),
                })
        except Exception:  # noqa: BLE001
            pass

    return ticker, rec


def get_fundamentals(tickers: list[str], workers: int = 6,
                     with_news: bool = False, refresh: bool = False) -> dict[str, dict]:
    cache = config.CACHE_DIR / "fundamentals.pkl"
    if not refresh and _fresh(cache):
        with open(cache, "rb") as f:
            cached = pickle.load(f)
        if all(t in cached for t in tickers):
            return cached

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_one, t, with_news): t for t in tickers}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                _, rec = fut.result()
                out[t] = rec
            except Exception as e:  # noqa: BLE001
                print(f"[fundamentals] {t} failed: {e}")
            time.sleep(0.05)

    with open(cache, "wb") as f:
        pickle.dump(out, f)
    return out
