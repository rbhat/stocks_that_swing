"""Fixed-policy event labels and the three locked ML targets."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from sts import risk
from sts.ml.contracts import ContractViolation, require_date

ATR_STOP_MULTIPLE = 2.0
ATR_TARGET_MULTIPLE = 4.0
TIME_STOP_SESSIONS = 15
RAW_RETURN_HORIZON = 15
BASE_BPS_PER_SIDE = 5.0
BASE_PER_ORDER_USD = 1.0
DOUBLE_BPS_PER_SIDE = 10.0
DOUBLE_PER_ORDER_USD = 2.0
MIN_PLANNED_R = 1.5
MAX_CHARTER_RISK_PCT = 0.12
MAX_SUCCESS_RISK_PCT = 0.25


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ContractViolation(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ContractViolation(f"{name} must be a finite number")
    return result


@dataclass(frozen=True)
class Bar:
    session: dt.date
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        require_date(self.session, "bar session")
        open_price = _finite(self.open, "bar open")
        high = _finite(self.high, "bar high")
        low = _finite(self.low, "bar low")
        close = _finite(self.close, "bar close")
        if min(open_price, high, low, close) <= 0:
            raise ContractViolation("bar prices must be positive")
        if high < max(open_price, close) or low > min(open_price, close):
            raise ContractViolation("bar OHLC geometry is invalid")


@dataclass(frozen=True)
class FixedGeometry:
    entry_fill: float
    atr14: float
    stop_initial: float
    target_initial: float
    initial_risk: float
    initial_risk_pct: float
    planned_r: float


def fixed_geometry(entry_fill: float, atr14: float) -> FixedGeometry:
    """Build and strictly validate the locked actual-fill geometry."""
    entry = _finite(entry_fill, "entry_fill")
    atr_value = _finite(atr14, "atr14")
    if entry <= 0:
        raise ContractViolation("entry_fill must be positive")
    if atr_value <= 0:
        raise ContractViolation("atr14 must be positive")

    # Match the Phase-3 instrument: the charter stop helper never permits a
    # wider stop, and strict validation below rejects its exact 12% boundary.
    stop = risk.atr_stop(entry, atr_value, ATR_STOP_MULTIPLE)
    target = risk.atr_target(entry, atr_value, ATR_TARGET_MULTIPLE)
    initial_risk = entry - stop
    initial_risk_pct = initial_risk / entry
    planned_r = (target - entry) / initial_risk
    if planned_r <= MIN_PLANNED_R:
        raise ContractViolation("planned_r must be strictly greater than 1.5")
    if initial_risk_pct >= MAX_SUCCESS_RISK_PCT:
        raise ContractViolation("initial risk must be strictly below 25%")
    if initial_risk_pct >= MAX_CHARTER_RISK_PCT:
        raise ContractViolation("initial risk must be strictly below 12%")
    return FixedGeometry(
        entry_fill=entry,
        atr14=atr_value,
        stop_initial=stop,
        target_initial=target,
        initial_risk=initial_risk,
        initial_risk_pct=initial_risk_pct,
        planned_r=planned_r,
    )


@dataclass(frozen=True)
class FixedPolicyOutcome:
    signal_session: dt.date
    entry_session: dt.date
    exit_session: dt.date
    entry_fill: float
    stop_initial: float
    target_initial: float
    quantity: int
    exit_price: float
    exit_reason: str
    hold_sessions: int
    gross_profit: float
    friction_base: float
    friction_2x: float
    net_r_base: float
    net_r_2x: float
    raw_h15_return: float


def _round_trip_friction(
    entry: float,
    exit_price: float,
    quantity: int,
    *,
    bps_per_side: float,
    per_order_usd: float,
) -> float:
    return (
        entry * quantity * bps_per_side / 10_000
        + per_order_usd
        + exit_price * quantity * bps_per_side / 10_000
        + per_order_usd
    )


def simulate_fixed_policy(
    *,
    signal_session: dt.date,
    atr14: float,
    forward_bars: Sequence[Bar],
) -> FixedPolicyOutcome:
    """Measure one event from next open through the locked 15-session policy.

    ``forward_bars[0]`` is the actual next exchange session and
    ``forward_bars[15]`` supplies the raw h=15 close. The first 15 bars are
    exit-managed; a same-bar stop always wins over a target.
    """
    signal = require_date(signal_session, "signal_session")
    bars = tuple(forward_bars)
    required = RAW_RETURN_HORIZON + 1
    if len(bars) < required:
        raise ContractViolation(
            f"complete label path requires {required} forward sessions"
        )
    if any(not isinstance(bar, Bar) for bar in bars[:required]):
        raise ContractViolation("forward_bars must contain Bar values")
    sessions = tuple(bar.session for bar in bars[:required])
    if sessions[0] <= signal:
        raise ContractViolation("entry session must follow signal_session")
    if any(left >= right for left, right in pairwise(sessions)):
        raise ContractViolation("forward bar sessions must be strictly increasing")

    geometry = fixed_geometry(bars[0].open, atr14)
    quantity = risk.position_size(
        risk.START_CAPITAL,
        geometry.entry_fill,
        geometry.stop_initial,
    )
    if quantity < 1:
        raise ContractViolation("fixed-policy position size is zero")

    exit_index = TIME_STOP_SESSIONS - 1
    exit_price = bars[exit_index].close
    exit_reason = "time"
    for index, bar in enumerate(bars[:TIME_STOP_SESSIONS]):
        if bar.low <= geometry.stop_initial:
            exit_index = index
            exit_price = min(geometry.stop_initial, bar.open)
            exit_reason = (
                "stop_gap" if bar.open < geometry.stop_initial else "stop"
            )
            break
        if bar.high >= geometry.target_initial:
            exit_index = index
            exit_price = max(geometry.target_initial, bar.open)
            exit_reason = "target"
            break

    gross_profit = quantity * (exit_price - geometry.entry_fill)
    base_friction = _round_trip_friction(
        geometry.entry_fill,
        exit_price,
        quantity,
        bps_per_side=BASE_BPS_PER_SIDE,
        per_order_usd=BASE_PER_ORDER_USD,
    )
    double_friction = _round_trip_friction(
        geometry.entry_fill,
        exit_price,
        quantity,
        bps_per_side=DOUBLE_BPS_PER_SIDE,
        per_order_usd=DOUBLE_PER_ORDER_USD,
    )
    risk_dollars = quantity * geometry.initial_risk
    raw_return = bars[RAW_RETURN_HORIZON].close / geometry.entry_fill - 1
    return FixedPolicyOutcome(
        signal_session=signal,
        entry_session=bars[0].session,
        exit_session=bars[exit_index].session,
        entry_fill=geometry.entry_fill,
        stop_initial=geometry.stop_initial,
        target_initial=geometry.target_initial,
        quantity=quantity,
        exit_price=exit_price,
        exit_reason=exit_reason,
        hold_sessions=exit_index + 1,
        gross_profit=gross_profit,
        friction_base=base_friction,
        friction_2x=double_friction,
        net_r_base=(gross_profit - base_friction) / risk_dollars,
        net_r_2x=(gross_profit - double_friction) / risk_dollars,
        raw_h15_return=raw_return,
    )


@dataclass(frozen=True)
class TargetValues:
    relative_net_r_2x: float
    spy_residual_h15: float
    useful_opportunity: int


def calculate_targets(
    *,
    net_r_2x: float,
    track_a_median_net_r_2x: float,
    raw_h15_return: float,
    spy_h15_return: float,
) -> TargetValues:
    """Calculate T1, T2, and T3 without filling any missing fact."""
    absolute_net_r = _finite(net_r_2x, "net_r_2x")
    track_a_median = _finite(
        track_a_median_net_r_2x, "track_a_median_net_r_2x"
    )
    raw_return = _finite(raw_h15_return, "raw_h15_return")
    spy_return = _finite(spy_h15_return, "spy_h15_return")
    relative = absolute_net_r - track_a_median
    return TargetValues(
        relative_net_r_2x=relative,
        spy_residual_h15=raw_return - spy_return,
        useful_opportunity=int(
            absolute_net_r > 0 and relative > 0 and raw_return > 0
        ),
    )
