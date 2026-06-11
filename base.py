"""
providers/base.py — pluggable data-source abstraction.

Each provider implements whatever subset it can serve and raises
NotSupported for the rest. The screener stays source-agnostic: it asks a
provider for a normalized snapshot / statements / prices and doesn't care where
they came from.

Normalized snapshot keys (all optional, NaN if unavailable):
  name, sector, market_cap, price, pe, forward_pe, pb, ps, peg, ev_ebitda,
  dividend_yield, roe, roce, debt_to_equity, revenue_growth, target_mean,
  target_high, target_low, recommendation, n_analysts, beta

Provider responsibilities are intentionally small so you can mix sources, e.g.
prices from Dhan, fundamentals from screener.in, analyst targets from yfinance.
"""

from __future__ import annotations
import abc


class NotSupported(Exception):
    """Raised when a provider can't serve a particular request."""


SNAPSHOT_KEYS = [
    "name", "sector", "market_cap", "price", "pe", "forward_pe", "pb", "ps",
    "peg", "ev_ebitda", "dividend_yield", "roe", "roce", "debt_to_equity",
    "revenue_growth", "target_mean", "target_high", "target_low",
    "recommendation", "n_analysts", "beta",
]


class Provider(abc.ABC):
    name = "base"
    #: True if this source needs API keys / login
    requires_auth = False

    def get_snapshot(self, symbol: str) -> dict:
        """Return a normalized snapshot dict (see SNAPSHOT_KEYS)."""
        raise NotSupported(f"{self.name}: snapshot not implemented")

    def get_statements(self, symbol: str) -> dict:
        """Return {'income','balance','cashflow', ...} DataFrames (raw)."""
        raise NotSupported(f"{self.name}: statements not implemented")

    def get_prices(self, symbol: str, period: str = "5y"):
        """Return an OHLCV DataFrame indexed by date."""
        raise NotSupported(f"{self.name}: prices not implemented")


_REGISTRY: dict[str, type[Provider]] = {}


def register(cls: type[Provider]) -> type[Provider]:
    _REGISTRY[cls.name] = cls
    return cls


def get_provider(name: str, **kwargs) -> Provider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown provider '{name}'. Available: {list(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def available() -> list[str]:
    return list(_REGISTRY)
