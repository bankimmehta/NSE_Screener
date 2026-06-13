"""
analytics.py — the model.

Pipeline:
  raw prices + fundamentals
        -> per-ticker feature row (indicators + ratios + analyst upside)
        -> sector-relative percentile sub-scores (0-100)
        -> weighted composite + buy-zone flag

Everything is percentile-ranked rather than z-scored so the 0-100 numbers stay
interpretable (a 90 means "top decile of this universe on this dimension").
Valuation and quality are ranked *within sector* (peer review); momentum and
analyst upside are ranked across the whole universe.
"""

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------------------
# Technical indicators (operate on an OHLCV DataFrame)
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = config.RSI_PERIOD) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return float(out.iloc[-1])


def atr_pct(df: pd.DataFrame, period: int = config.ATR_PERIOD) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return float(atr.iloc[-1] / close.iloc[-1])


def _ret(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1)


def beta(stock_close: pd.Series, bench_close: pd.Series,
         window: int = config.BETA_WINDOW) -> float:
    sr = stock_close.pct_change().dropna().iloc[-window:]
    br = bench_close.pct_change().dropna().iloc[-window:]
    j = pd.concat([sr, br], axis=1, join="inner").dropna()
    if len(j) < 30:
        return np.nan
    cov = np.cov(j.iloc[:, 0], j.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] else np.nan


def technicals(df: pd.DataFrame, bench: pd.DataFrame | None) -> dict:
    close = df["Close"]
    price = float(close.iloc[-1])
    sma50 = float(close.rolling(config.SMA_FAST).mean().iloc[-1])
    sma200 = float(close.rolling(config.SMA_SLOW).mean().iloc[-1]) if len(close) >= config.SMA_SLOW else np.nan
    hi52 = float(close.iloc[-252:].max())
    lo52 = float(close.iloc[-252:].min())
    pos52 = (price - lo52) / (hi52 - lo52) if hi52 > lo52 else np.nan
    daily = close.pct_change().dropna()
    ann_vol = float(daily.iloc[-252:].std() * np.sqrt(252)) if len(daily) > 30 else np.nan
    return {
        "price": price,
        "sma50": sma50,
        "sma200": sma200,
        "dist_sma200": price / sma200 - 1 if sma200 == sma200 else np.nan,
        "rsi": rsi(close),
        "atr_pct": atr_pct(df),
        "ann_vol": ann_vol,
        "pos_52w": pos52,
        "ret_3m": _ret(close, 63),
        "ret_6m": _ret(close, 126),
        "ret_1y": _ret(close, 252),
        "beta_calc": beta(close, bench["Close"]) if bench is not None else np.nan,
    }


# ---------------------------------------------------------------------------
# Buy-zone heuristic (continuous score + boolean flag)
# ---------------------------------------------------------------------------
def compute_buy_zone(row: pd.Series, bz: dict | None = None) -> tuple[float, bool]:
    """A 'good place to enter': uptrend intact, pulled back but not bleeding,
    not glued to its 52-week high, not a falling knife. Returns (score0_100, flag)."""
    bz = bz or config.BUY_ZONE
    price, sma200 = row["price"], row["sma200"]
    rsi_v, pos52, ret3m = row["rsi"], row["pos_52w"], row["ret_3m"]

    score = 50.0
    flag = True

    if pd.notna(sma200):
        ratio = price / sma200
        if ratio >= bz["uptrend_sma200_floor"]:
            score += 12
        else:
            flag = False
            score -= 15
        if ratio < bz["falling_knife_sma200"]:
            flag = False
            score -= 15

    if pd.notna(rsi_v):
        if bz["rsi_floor"] <= rsi_v <= 55:        # the sweet spot: pulled back, turning
            score += 15
        elif rsi_v > bz["rsi_overbought"]:
            flag = False
            score -= 12
        elif rsi_v < bz["rsi_floor"]:
            flag = False
            score -= 8

    if pd.notna(pos52):
        if pos52 > bz["pos52w_extended"]:          # hugging the highs -> little room
            flag = False
            score -= 10
        elif 0.25 <= pos52 <= 0.70:                # mid-range recovery room
            score += 10

    if pd.notna(ret3m) and ret3m < bz["ret3m_knife"]:
        flag = False
        score -= 10

    return float(np.clip(score, 0, 100)), bool(flag)


# ---------------------------------------------------------------------------
# Feature assembly
# ---------------------------------------------------------------------------
def build_features(prices: dict, fundamentals: dict) -> pd.DataFrame:
    bench = prices.get(config.BENCHMARK)
    rows = []
    for t, f in fundamentals.items():
        if t not in prices:
            continue
        tech = technicals(prices[t], bench)

        price = tech["price"] or f.get("currentPrice")
        tgt = f.get("targetMeanPrice")
        implied = (tgt / price - 1) if (tgt and price and price > 0) else np.nan

        rows.append({
            "ticker": t,
            "name": f.get("shortName"),
            "sector": f.get("sector") or "Unknown",
            "marketCap": f.get("marketCap"),
            **tech,
            # valuation
            "pe": f.get("trailingPE"),
            "fwd_pe": f.get("forwardPE"),
            "ps": f.get("priceToSalesTrailing12Months"),
            "peg": f.get("pegRatio"),
            "ev_ebitda": f.get("enterpriseToEbitda"),
            # quality
            "rev_growth": f.get("revenueGrowth"),
            "rev_growth_raw": f.get("revenueGrowth_raw"),
            "rev_growth_source": f.get("revenueGrowth_source"),
            "is_financial": bool(f.get("is_financial", False)),
            "earn_growth": f.get("earningsGrowth") if pd.notna(f.get("earningsGrowth"))
                           else f.get("earningsQuarterlyGrowth"),
            "margin": f.get("profitMargins"),
            "roe": f.get("returnOnEquity"),
            "de": f.get("debtToEquity"),
            "fcf": f.get("freeCashflow"),
            # analyst
            "target_mean": tgt,
            "target_high": f.get("targetHighPrice"),
            "target_low": f.get("targetLowPrice"),
            "implied_upside": implied,
            "rec_mean": f.get("recommendationMean"),
            "n_analysts": f.get("numberOfAnalystOpinions"),
            "beta": f.get("beta") if pd.notna(f.get("beta")) else tech["beta_calc"],
            "n_news": len(f.get("news") or []),
        })
    return pd.DataFrame(rows).set_index("ticker")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _pct(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Percentile rank -> 0-100. NaNs stay NaN. Optionally invert."""
    r = series.rank(pct=True)
    r = r if higher_is_better else (1 - r)
    return r * 100


def _sector_pct(df: pd.DataFrame, col: str, higher_is_better: bool) -> pd.Series:
    """Rank within sector; fall back to universe-wide for thin sectors."""
    out = pd.Series(index=df.index, dtype=float)
    for sec, grp in df.groupby("sector"):
        if grp[col].notna().sum() >= config.MIN_PEERS_FOR_SECTOR:
            out.loc[grp.index] = _pct(grp[col], higher_is_better)
    missing = out.isna() & df[col].notna()
    if missing.any():
        out.loc[missing] = _pct(df.loc[missing, col], higher_is_better).reindex(df.index)[missing]
    return out


def _blend(parts: list[pd.Series]) -> pd.Series:
    """Average available sub-components per row (ignoring NaNs)."""
    m = pd.concat(parts, axis=1)
    return m.mean(axis=1, skipna=True)


def score(df: pd.DataFrame, weights: dict | None = None,
          bz: dict | None = None) -> pd.DataFrame:
    weights = weights or config.WEIGHTS
    df = df.copy()

    # --- Buy zone ---
    res = df.apply(lambda r: compute_buy_zone(r, bz), axis=1, result_type="expand")
    df["score_buy_zone"] = res[0]
    df["buy_zone"] = res[1]

    # --- Valuation (cheaper vs peers = better; lower multiple = better) ---
    df["score_valuation"] = _blend([
        _sector_pct(df, "pe", higher_is_better=False),
        _sector_pct(df, "fwd_pe", higher_is_better=False),
        _sector_pct(df, "ps", higher_is_better=False),
        _sector_pct(df, "ev_ebitda", higher_is_better=False),
        _sector_pct(df, "peg", higher_is_better=False),
    ])

    # --- Quality (growth/margins/returns up good; leverage down good) ---
    df["score_quality"] = _blend([
        _sector_pct(df, "rev_growth", True),
        _sector_pct(df, "earn_growth", True),
        _sector_pct(df, "margin", True),
        _sector_pct(df, "roe", True),
        _sector_pct(df, "de", False),
    ])

    # --- Momentum (trend health, universe-wide) ---
    df["score_momentum"] = _blend([
        _pct(df["ret_6m"], True),
        _pct(df["ret_3m"], True),
        _pct(df["dist_sma200"], True),
    ])

    # --- Analyst upside (implied upside + recommendation quality) ---
    up = _pct(df["implied_upside"], True)
    rec = _pct(df["rec_mean"], higher_is_better=False)  # 1=strong buy is best
    df["score_analyst"] = _blend([up, up, rec])         # weight upside 2x vs rec

    # --- Composite: renormalize weights over available sub-scores per row ---
    cols = {
        "score_analyst": weights["analyst_upside"],
        "score_buy_zone": weights["buy_zone"],
        "score_valuation": weights["valuation"],
        "score_quality": weights["quality"],
        "score_momentum": weights["momentum"],
    }
    sub = df[list(cols)]
    w = pd.Series(cols)
    weighted = sub.mul(w, axis=1)
    avail_w = sub.notna().mul(w, axis=1).sum(axis=1)
    df["composite"] = (weighted.sum(axis=1) / avail_w).round(1)

    return df.sort_values("composite", ascending=False)
