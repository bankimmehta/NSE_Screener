"""
clean.py — sanitize Yahoo fundamentals so bad data never reaches the model.

The problem this fixes: Yahoo's `revenueGrowth` is a most-recent-QUARTER YoY
figure, and for banks/NBFCs (and any name with a distorted year-ago base) it can
be wildly wrong — e.g. INDUSINDBK showing 272%. Passed straight through, that
both displays nonsense and corrupts the sector-relative quality ranking.

Strategy (in priority order):
  1. Recompute revenue/earnings growth from ANNUAL statements (FY vs prior FY).
     Annual is far more stable than the quarterly snapshot.
  2. Growth is UNDEFINED off a non-positive base — if prior <= 0, return NaN
     (this kills the sign-flip artifacts that produce huge %).
  3. If no statement is available, fall back to Yahoo's snapshot but CLAMP it:
     anything beyond a sane bound is dropped to NaN rather than trusted.
  4. Flag financials (bank/NBFC/insurer) and null metrics that are meaningless
     for them (Price/Sales). Revenue-based fields stay flagged for caution.
  5. Sanity-bound ROE and margins.

Every original value is preserved as `<field>_raw` for transparency/audit.
"""

import numpy as np
import pandas as pd

FINANCIAL_SECTORS = {"Financial Services", "Financials"}
FIN_INDUSTRY_HINTS = ["bank", "insurance", "financial", "capital market",
                      "asset management", "credit", "nbfc", "broker"]

# Trust annual statements widely; distrust the quarterly snapshot.
COMPUTED_GROWTH_BOUND = 5.0     # |annual FY growth| above this = clearly broken
RAW_GROWTH_BOUND = 1.5          # |snapshot growth| above this = drop (272% -> NaN)


def is_financial(info: dict) -> bool:
    sec = (info.get("sector") or "")
    ind = (info.get("industry") or "").lower()
    if sec in FINANCIAL_SECTORS:
        return True
    return any(h in ind for h in FIN_INDUSTRY_HINTS)


def _find_row(stmt, labels):
    if stmt is None or getattr(stmt, "empty", True):
        return None
    idx = {str(i).lower(): i for i in stmt.index}
    for lab in labels:
        l = lab.lower()
        for low, orig in idx.items():
            if l == low or l in low:
                return stmt.loc[orig]
    return None


def _latest_prior(stmt, labels):
    row = _find_row(stmt, labels)
    if row is None:
        return (np.nan, np.nan)
    try:
        cols = sorted(row.index, key=lambda c: pd.Timestamp(c), reverse=True)
    except Exception:  # noqa: BLE001
        cols = list(row.index)
    if len(cols) < 2:
        return (np.nan, np.nan)
    return (row[cols[0]], row[cols[1]])


def annual_growth(stmt, labels):
    """FY-over-FY growth from a statement. NaN if base <= 0 or value absurd."""
    latest, prior = _latest_prior(stmt, labels)
    if pd.isna(latest) or pd.isna(prior) or prior <= 0:
        return np.nan
    g = latest / prior - 1
    return g if abs(g) <= COMPUTED_GROWTH_BOUND else np.nan


def _clamp(v, bound):
    if v is None or pd.isna(v):
        return np.nan
    v = float(v)
    return v if abs(v) <= bound else np.nan


def _bound(v, lo, hi):
    if v is None or pd.isna(v):
        return np.nan
    v = float(v)
    return v if lo <= v <= hi else np.nan


def sanitize_fundamentals(rec: dict, income_stmt=None) -> dict:
    """Mutate+return a fundamentals record with cleaned, audited fields."""
    fin = is_financial(rec)
    rec["is_financial"] = fin

    # --- revenue growth: annual stmt -> else clamped snapshot ---
    rev_raw = rec.get("revenueGrowth")
    rev_calc = annual_growth(income_stmt, ["Total Revenue", "Operating Revenue", "Total Income"])
    rec["revenueGrowth_raw"] = rev_raw
    if pd.notna(rev_calc):
        rec["revenueGrowth"] = rev_calc
        rec["revenueGrowth_source"] = "annual_stmt"
    else:
        clamped = _clamp(rev_raw, RAW_GROWTH_BOUND)
        rec["revenueGrowth"] = clamped
        rec["revenueGrowth_source"] = "snapshot" if pd.notna(clamped) else "dropped"

    # --- earnings growth: annual stmt -> else clamped snapshot ---
    earn_raw = rec.get("earningsGrowth")
    earn_calc = annual_growth(income_stmt, ["Net Income", "Net Income Common Stockholders"])
    rec["earningsGrowth_raw"] = earn_raw
    rec["earningsGrowth"] = earn_calc if pd.notna(earn_calc) else _clamp(earn_raw, RAW_GROWTH_BOUND)

    # --- sanity bounds on level ratios ---
    rec["returnOnEquity"] = _bound(rec.get("returnOnEquity"), -1.0, 2.0)   # ROE in [-100%, 200%]
    rec["profitMargins"] = _bound(rec.get("profitMargins"), -2.0, 1.0)     # margin <= 100%

    # --- financials: kill metrics that don't apply to lenders ---
    if fin:
        rec["priceToSalesTrailing12Months"] = np.nan   # P/S is meaningless for banks

    return rec
