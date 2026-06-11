"""
providers/screener_in.py — fundamentals from screener.in.

This is the highest-value source for NSE fundamentals (multi-year P&L, balance
sheet, cash flow, and ratios that Yahoo doesn't expose well for Indian names).

IMPORTANT / PLEASE READ:
  * screener.in has no official public API; this scrapes the public company
    page. Review their Terms of Service and robots.txt and keep usage to
    personal research. This fetcher rate-limits and caches on disk to be
    polite; do not hammer the site or use it commercially without permission.
  * Some data (esp. consolidated numbers and certain ratios) requires a logged-
    in session on screener.in. Without login you still get standalone P&L /
    balance sheet / ratios for most names. To use a session, pass a `cookie`
    string (copy from your browser's DevTools after logging in).
  * Because I can't reach the live site from where this was written, the CSS
    section ids below reflect screener.in's known structure but may need a
    one-line tweak if they change the page. Each parse is wrapped so a miss
    degrades to NaN/empty rather than crashing.

Symbols are the plain NSE code WITHOUT the .NS suffix (e.g. "RELIANCE").
"""

from __future__ import annotations
import re
import time
import pickle
from pathlib import Path

import pandas as pd

from .base import Provider, register

CACHE = Path(__file__).resolve().parent.parent / "cache" / "screener_in"
CACHE.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
# screener.in section ids -> our statement keys
_SECTIONS = {
    "quarters": "quarterly",
    "profit-loss": "income",
    "balance-sheet": "balance",
    "cash-flow": "cashflow",
    "ratios": "ratios",
}
_RATE_LIMIT_S = 1.5  # be polite


def _num(x):
    """Parse '1,23,456' / '12.3%' / '₹ 1,234 Cr' -> float."""
    if x is None:
        return None
    s = re.sub(r"[₹,%]|Cr|Rs\.?|\s", "", str(x)).replace("\u20b9", "")
    try:
        return float(s)
    except ValueError:
        return None


@register
class ScreenerIn(Provider):
    name = "screener_in"
    requires_auth = False  # optional cookie for consolidated/logged-in data

    def __init__(self, cookie: str | None = None, consolidated: bool = False,
                 ttl_hours: int = 24):
        self.cookie = cookie
        self.consolidated = consolidated
        self.ttl_hours = ttl_hours

    # -- network --
    def _fetch_page(self, symbol: str) -> str:
        import requests  # local import so the package imports without it
        cache_f = CACHE / f"{symbol}{'_c' if self.consolidated else ''}.html"
        if cache_f.exists():
            age_h = (time.time() - cache_f.stat().st_mtime) / 3600
            if age_h < self.ttl_hours:
                return cache_f.read_text(encoding="utf-8")

        path = "consolidated/" if self.consolidated else ""
        url = f"https://www.screener.in/company/{symbol}/{path}"
        headers = dict(_HEADERS)
        if self.cookie:
            headers["Cookie"] = self.cookie
        time.sleep(_RATE_LIMIT_S)
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        cache_f.write_text(resp.text, encoding="utf-8")
        return resp.text

    # -- parsing --
    def _top_ratios(self, soup) -> dict:
        out = {}
        ul = soup.find(id="top-ratios")
        if not ul:
            return out
        for li in ul.find_all("li"):
            name_el = li.find(class_="name")
            val_el = li.find(class_="value") or li.find(class_="number")
            if name_el and val_el:
                out[name_el.get_text(strip=True)] = val_el.get_text(" ", strip=True)
        return out

    def _section_table(self, soup, section_id: str) -> pd.DataFrame:
        import io
        sec = soup.find("section", id=section_id) or soup.find(id=section_id)
        if not sec:
            return pd.DataFrame()
        try:
            tables = pd.read_html(io.StringIO(str(sec)))
            return tables[0] if tables else pd.DataFrame()
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_snapshot(self, symbol: str) -> dict:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(self._fetch_page(symbol), "html.parser")
        tr = self._top_ratios(soup)

        def pick(*labels):
            for lab in labels:
                for k, v in tr.items():
                    if lab.lower() in k.lower():
                        return _num(v)
            return None

        name_el = soup.find("h1")
        return {
            "name": name_el.get_text(strip=True) if name_el else symbol,
            "sector": None,  # screener shows peers/sector elsewhere; left for extension
            "market_cap": pick("Market Cap"),
            "price": pick("Current Price"),
            "pe": pick("Stock P/E", "P/E"),
            "pb": pick("Price to Book", "Book Value") and None,  # book value != P/B
            "dividend_yield": pick("Dividend Yield"),
            "roce": pick("ROCE"),
            "roe": pick("ROE"),
            "debt_to_equity": pick("Debt to equity"),
            # not on the standard page; left NaN so other providers can fill:
            "forward_pe": None, "ps": None, "peg": None, "ev_ebitda": None,
            "revenue_growth": None, "target_mean": None, "target_high": None,
            "target_low": None, "recommendation": None, "n_analysts": None,
            "beta": None,
        }

    def get_statements(self, symbol: str) -> dict:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(self._fetch_page(symbol), "html.parser")
        out = {}
        for sec_id, key in _SECTIONS.items():
            out[key] = self._section_table(soup, sec_id)
        return out
