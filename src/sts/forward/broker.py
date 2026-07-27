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
from collections.abc import Callable
from typing import TypedDict

from sts import risk
from sts.study.success_gate import entry_geometry


class Fill(TypedDict):
    price: float
    fees: float
    timestamp: str


def actual_fill_geometry(candidate: dict, entry_fill: float) -> dict:
    """Re-anchor and strictly validate candidate geometry at the real open.

    Success-v2 candidates must carry the stop/target ATR multiples as
    immutable facts.  Legacy candidates remain readable through the frozen
    2.0/2.0 fallback, but only success-v2 geometry is judged by this helper's
    ``accepted`` result.
    """
    version = candidate.get("strategy_version")
    if version is not None:
        missing = [
            field
            for field in ("stop_atr_multiple", "target_atr_multiple")
            if field not in candidate
        ]
        if missing:
            return {
                "accepted": False,
                "reason": f"missing_candidate_geometry_facts:{','.join(missing)}",
                "entry_fill": entry_fill,
                "stop_initial": None,
                "target_initial": None,
                "metrics": None,
            }
    stop_multiple = float(candidate.get("stop_atr_multiple", 2.0))
    target_multiple = float(candidate.get("target_atr_multiple", 2.0))
    try:
        atr_sig = float(candidate["atr_sig"])
        stop = risk.atr_stop(entry_fill, atr_sig, stop_multiple)
        target = risk.atr_target(entry_fill, atr_sig, target_multiple)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "accepted": False,
            "reason": f"invalid_candidate_geometry_facts:{exc}",
            "entry_fill": entry_fill,
            "stop_initial": None,
            "target_initial": None,
            "metrics": None,
        }

    metrics = entry_geometry(entry_fill, stop, target)
    accepted = bool(metrics["valid"])
    return {
        "accepted": accepted,
        "reason": None if accepted else metrics["reason"],
        "entry_fill": entry_fill,
        "stop_initial": stop,
        "target_initial": target,
        "stop_atr_multiple": stop_multiple,
        "target_atr_multiple": target_multiple,
        "metrics": metrics,
    }


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
        return

    def cancel(self, entry_id: str) -> None:
        """No-op hook: a real broker implementation may override this to
        cancel a resting order for `entry_id`."""
        return


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
