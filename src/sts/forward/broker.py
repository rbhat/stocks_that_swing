"""PaperBroker interface + stub implementation.

Resting stop/target management is NOT broker-side this phase: exits are
governed by the daily-bar engine (pipeline upkeep) per prereg. The
interface leaves room for a real broker (Alpaca/IBKR) to slot in later via
no-op hooks `place_protective(row)` / `cancel(entry_id)`.
"""

from __future__ import annotations

import datetime as dt
import math
from abc import ABC, abstractmethod
from typing import Callable, TypedDict


class Fill(TypedDict):
    price: float
    fees: float
    timestamp: str


def cost_side(price: float, qty: int, bps: float = 5.0, per_order: float = 1.0) -> float:
    """One-sided execution cost: bps of notional plus a flat per-order fee."""
    return price * qty * (bps / 10_000) + per_order


class PaperBroker(ABC):
    """Abstract paper-trading broker interface."""

    @abstractmethod
    def fill_entry(self, symbol: str, date: dt.date, qty: int) -> Fill | None:
        """Fill an entry order. Returns None if no fill is available yet."""
        raise NotImplementedError

    def place_protective(self, row: dict) -> None:
        """No-op hook: resting stop/target management is pipeline-upkeep-side
        this phase. A real broker implementation may override this to place
        a resting stop/target order."""
        return None

    def cancel(self, entry_id: str) -> None:
        """No-op hook: a real broker implementation may override this to
        cancel a resting order for `entry_id`."""
        return None


class StubPaperBroker(PaperBroker):
    """Fills at the actual session open, as reported by `get_open`."""

    def __init__(self, get_open: Callable[[str, dt.date], float | None]):
        self._get_open = get_open

    def fill_entry(self, symbol: str, date: dt.date, qty: int) -> Fill | None:
        price = self._get_open(symbol, date)
        if price is None or not math.isfinite(price) or price <= 0:
            return None
        fees = cost_side(price, qty)
        return Fill(
            price=price,
            fees=fees,
            timestamp=dt.datetime.now(dt.UTC).isoformat(),
        )
