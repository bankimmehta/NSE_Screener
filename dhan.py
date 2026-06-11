"""
providers/dhan.py — historical OHLC prices via Dhan's OFFICIAL API.

Unlike screener.in, this is a sanctioned API (DhanHQ). It needs a Dhan account
and credentials; set them as environment variables:

  export DHAN_CLIENT_ID=xxxx
  export DHAN_ACCESS_TOKEN=xxxx      # generate from web.dhan.co -> DhanHQ API

Resolving a symbol -> securityId uses Dhan's public instrument master CSV.
Dhan serves prices well but NOT deep fundamental statements — pair it with
screener.in for fundamentals.

Docs: https://dhanhq.co/docs/v2/
(Could not be tested from the build environment; structure follows the v2 API.)
"""

from __future__ import annotations
import os
import datetime as dt
from pathlib import Path

import pandas as pd

from .base import Provider, register, NotSupported

CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE.mkdir(exist_ok=True)
_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_HIST_URL = "https://api.dhan.co/v2/charts/historical"


@register
class Dhan(Provider):
    name = "dhan"
    requires_auth = True

    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        self._master = None

    def _load_master(self) -> pd.DataFrame:
        if self._master is not None:
            return self._master
        cache_f = CACHE / "dhan_master.csv"
        if cache_f.exists():
            self._master = pd.read_csv(cache_f, low_memory=False)
        else:
            self._master = pd.read_csv(_MASTER_URL, low_memory=False)
            self._master.to_csv(cache_f, index=False)
        return self._master

    def _security_id(self, symbol: str) -> str:
        """Map an NSE equity symbol (e.g. RELIANCE) to Dhan securityId."""
        m = self._load_master()
        # column names vary across master versions; match defensively
        sym_cols = [c for c in m.columns if "SYMBOL" in c.upper() or "TRADING" in c.upper()]
        seg_cols = [c for c in m.columns if "SEGMENT" in c.upper() or "EXCH" in c.upper()]
        id_cols = [c for c in m.columns if "SECURITY" in c.upper() and "ID" in c.upper()]
        if not (sym_cols and id_cols):
            raise NotSupported("dhan: could not locate columns in instrument master")
        df = m
        sym = symbol.replace(".NS", "").upper()
        mask = False
        for sc in sym_cols:
            mask = mask | (df[sc].astype(str).str.upper() == sym)
        hit = df[mask]
        if seg_cols:
            for gc in seg_cols:
                nse = hit[hit[gc].astype(str).str.upper().str.contains("NSE", na=False)]
                if not nse.empty:
                    hit = nse
                    break
        if hit.empty:
            raise NotSupported(f"dhan: no securityId for {sym}")
        return str(hit.iloc[0][id_cols[0]])

    def get_prices(self, symbol: str, period: str = "5y") -> pd.DataFrame:
        import requests
        if not (self.client_id and self.access_token):
            raise NotSupported("dhan: set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN")
        sec_id = self._security_id(symbol)
        years = int(str(period).rstrip("y") or 5)
        to_d = dt.date.today()
        from_d = to_d - dt.timedelta(days=365 * years + 5)
        headers = {"access-token": self.access_token, "client-id": self.client_id,
                   "Content-Type": "application/json"}
        body = {"securityId": sec_id, "exchangeSegment": "NSE_EQ",
                "instrument": "EQUITY", "fromDate": from_d.isoformat(),
                "toDate": to_d.isoformat()}
        r = requests.post(_HIST_URL, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        d = r.json()
        # v2 returns parallel arrays
        df = pd.DataFrame({
            "Open": d.get("open", []), "High": d.get("high", []),
            "Low": d.get("low", []), "Close": d.get("close", []),
            "Volume": d.get("volume", []),
        })
        ts = d.get("timestamp") or d.get("start_Time") or []
        if len(ts) == len(df):
            df.index = pd.to_datetime(ts, unit="s")
            df.index.name = "Date"
        return df
