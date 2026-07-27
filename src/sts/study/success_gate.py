"""Pure, strategy-agnostic success-v2 metrics and artifact contract.

This module does no I/O and has no knowledge of detectors, ledgers, data
walls, or preregistrations. Callers provide closed-event facts and marked
portfolio sessions; the returned dictionaries are JSON-safe additions to a
new study artifact. Historical artifacts are intentionally not migrated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from sts import risk

MIN_PLANNED_R = 1.5
MAX_SUCCESS_RISK_PCT = 0.25
MAX_CHARTER_RISK_PCT = risk.MAX_STOP_PCT
MIN_EVENT_COUNT = 100
MAX_MEDIAN_HOLD_SESSIONS = 15

STATE_NOT_RUN = "not_run"
STATE_INADEQUATE = "inadequate"
STATE_INVALID_GEOMETRY = "invalid_geometry"
STATE_EVALUATED = "evaluated"

ARTIFACT_SCHEMA_VERSION = "success-v2.phase1"


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "min": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "max": None,
        }
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "min": float(arr.min()),
        "p25": float(np.quantile(arr, 0.25)),
        "median": float(np.median(arr)),
        "mean": float(arr.mean()),
        "p75": float(np.quantile(arr, 0.75)),
        "max": float(arr.max()),
    }


def entry_geometry(
    entry_fill: float,
    stop_initial: float,
    target_initial: float,
) -> dict[str, Any]:
    """Calculate and strictly judge one long-entry geometry.

    ``planned_r == 1.5``, ``initial_risk_pct == 25%``, and the existing
    charter boundary ``initial_risk_pct == 12%`` all fail because every
    corresponding rule is strict.
    """
    try:
        entry = _finite_number(entry_fill, "entry_fill")
        stop = _finite_number(stop_initial, "stop_initial")
        target = _finite_number(target_initial, "target_initial")
    except (TypeError, ValueError) as exc:
        return {
            "state": STATE_INVALID_GEOMETRY,
            "valid": False,
            "reason": str(exc),
            "initial_risk": None,
            "planned_r": None,
            "initial_risk_pct": None,
            "planned_r_pass": False,
            "success_risk_pass": False,
            "charter_risk_pass": False,
        }

    initial_risk = entry - stop
    if entry <= 0:
        reason = "entry_fill_must_be_positive"
    elif initial_risk <= 0:
        reason = "stop_initial_must_be_below_entry_fill"
    elif target <= entry:
        reason = "target_initial_must_be_above_entry_fill"
    else:
        reason = None

    if reason is not None:
        return {
            "state": STATE_INVALID_GEOMETRY,
            "valid": False,
            "reason": reason,
            "initial_risk": initial_risk if entry > 0 else None,
            "planned_r": None,
            "initial_risk_pct": (
                initial_risk / entry if entry > 0 and initial_risk > 0 else None
            ),
            "planned_r_pass": False,
            "success_risk_pass": False,
            "charter_risk_pass": False,
        }

    planned_r = (target - entry) / initial_risk
    initial_risk_pct = initial_risk / entry
    planned_r_pass = planned_r > MIN_PLANNED_R
    success_risk_pass = initial_risk_pct < MAX_SUCCESS_RISK_PCT
    charter_risk_pass = initial_risk_pct < MAX_CHARTER_RISK_PCT

    reasons = []
    if not planned_r_pass:
        reasons.append("planned_r_not_strictly_gt_1_5")
    if not success_risk_pass:
        reasons.append("initial_risk_pct_not_strictly_lt_25pct")
    if not charter_risk_pass:
        reasons.append("initial_risk_pct_not_strictly_lt_12pct_charter")
    valid = not reasons
    return {
        "state": STATE_EVALUATED if valid else STATE_INVALID_GEOMETRY,
        "valid": valid,
        "reason": None if valid else ",".join(reasons),
        "initial_risk": initial_risk,
        "planned_r": planned_r,
        "initial_risk_pct": initial_risk_pct,
        "planned_r_pass": planned_r_pass,
        "success_risk_pass": success_risk_pass,
        "charter_risk_pass": charter_risk_pass,
    }


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return None
    return gains / losses


def _event_not_run() -> dict[str, Any]:
    return {
        "evaluation_state": STATE_NOT_RUN,
        "passes": None,
        "adequacy": {"observed": 0, "required": MIN_EVENT_COUNT, "sufficient": False},
        "geometry": {"valid": 0, "invalid": 0, "all_valid": None},
        "metrics": None,
        "bars": None,
    }


def summarize_events(
    events: Sequence[dict[str, Any]] | None,
    *,
    raw_h15_returns: Sequence[float] | None = None,
    min_events: int = MIN_EVENT_COUNT,
) -> dict[str, Any]:
    """Summarize canonical closed-event facts for the success-v2 gate.

    Each event must provide ``entry_fill``, ``stop_initial``,
    ``target_initial``, ``gross_profit``, ``friction_base`` (both-side
    dollars), ``hold_sessions``, and ``mae_r`` (non-negative adverse
    excursion magnitude in initial-R units).
    """
    if events is None:
        result = _event_not_run()
        result["adequacy"]["required"] = min_events
        return result
    if min_events <= 0:
        raise ValueError("min_events must be positive")

    rows = list(events)
    geometries: list[dict[str, Any]] = []
    gross: list[float] = []
    friction: list[float] = []
    holds: list[float] = []
    mae_r: list[float] = []

    for index, row in enumerate(rows):
        geometries.append(
            entry_geometry(
                row.get("entry_fill"),
                row.get("stop_initial"),
                row.get("target_initial"),
            )
        )
        gross_value = _finite_number(row.get("gross_profit"), f"events[{index}].gross_profit")
        friction_value = _finite_number(
            row.get("friction_base"), f"events[{index}].friction_base"
        )
        hold_value = _finite_number(row.get("hold_sessions"), f"events[{index}].hold_sessions")
        mae_value = _finite_number(row.get("mae_r"), f"events[{index}].mae_r")
        if friction_value < 0:
            raise ValueError(f"events[{index}].friction_base must be non-negative")
        if hold_value < 0:
            raise ValueError(f"events[{index}].hold_sessions must be non-negative")
        if mae_value < 0:
            raise ValueError(f"events[{index}].mae_r must be non-negative")
        gross.append(gross_value)
        friction.append(friction_value)
        holds.append(hold_value)
        mae_r.append(mae_value)

    net_base = [value - cost for value, cost in zip(gross, friction)]
    net_2x = [value - 2 * cost for value, cost in zip(gross, friction)]
    valid_count = sum(bool(geometry["valid"]) for geometry in geometries)
    invalid_count = len(geometries) - valid_count

    if raw_h15_returns is None:
        raw_h15 = None
        raw_h15_pass: bool | None = None
    else:
        raw_values = [
            _finite_number(value, f"raw_h15_returns[{index}]")
            for index, value in enumerate(raw_h15_returns)
        ]
        raw_h15 = _distribution(raw_values)
        raw_h15_pass = bool(raw_values) and raw_h15["mean"] > 0

    wins = sum(value > 0 for value in net_base)
    losses = sum(value < 0 for value in net_base)
    flats = len(net_base) - wins - losses
    hold_summary = _distribution(holds)
    bars = {
        "event_count_ge_minimum": len(rows) >= min_events,
        "all_entry_geometry_valid": invalid_count == 0,
        "net_profit_base_positive": sum(net_base) > 0,
        "net_profit_2x_positive": sum(net_2x) > 0,
        "median_hold_le_15": (
            hold_summary["median"] is not None
            and hold_summary["median"] <= MAX_MEDIAN_HOLD_SESSIONS
        ),
        "raw_h15_return_positive": raw_h15_pass,
    }

    if invalid_count:
        evaluation_state = STATE_INVALID_GEOMETRY
    elif len(rows) < min_events:
        evaluation_state = STATE_INADEQUATE
    else:
        evaluation_state = STATE_EVALUATED

    required_bars = [value for value in bars.values() if value is not None]
    passes: bool | None
    if raw_h15_pass is None and all(required_bars):
        passes = None
    else:
        passes = len(required_bars) == len(bars) and all(required_bars)

    return {
        "evaluation_state": evaluation_state,
        "passes": passes,
        "adequacy": {
            "observed": len(rows),
            "required": min_events,
            "sufficient": len(rows) >= min_events,
        },
        "geometry": {
            "valid": valid_count,
            "invalid": invalid_count,
            "all_valid": invalid_count == 0,
            "planned_r": _distribution(
                [geometry["planned_r"] for geometry in geometries if geometry["planned_r"] is not None]
            ),
            "initial_risk_pct": _distribution(
                [
                    geometry["initial_risk_pct"]
                    for geometry in geometries
                    if geometry["initial_risk_pct"] is not None
                ]
            ),
            "invalid_reasons": sorted(
                {
                    geometry["reason"]
                    for geometry in geometries
                    if geometry["reason"] is not None
                }
            ),
        },
        "metrics": {
            "event_count": len(rows),
            "net_profit": {"base": sum(net_base), "2x": sum(net_2x)},
            "profit_factor": {
                "base": _profit_factor(net_base),
                "2x": _profit_factor(net_2x),
            },
            "win_loss": {
                "wins": wins,
                "losses": losses,
                "flat": flats,
                "win_rate": wins / len(rows) if rows else None,
                "base_net_profit": _distribution(net_base),
                "2x_net_profit": _distribution(net_2x),
            },
            "hold_sessions": hold_summary,
            "mae_r": _distribution(mae_r),
            "friction": {
                "base_total": sum(friction),
                "2x_total": 2 * sum(friction),
                "base_per_event": _distribution(friction),
            },
            "raw_h15_return": raw_h15,
        },
        "bars": bars,
    }


def max_drawdown(equity: Sequence[float]) -> float:
    """Maximum peak-to-trough loss fraction for a positive equity path."""
    if not equity:
        return 0.0
    values = [_finite_number(value, f"equity[{index}]") for index, value in enumerate(equity)]
    if any(value <= 0 for value in values):
        raise ValueError("equity values must be positive")
    peak = values[0]
    result = 0.0
    for value in values:
        peak = max(peak, value)
        result = max(result, (peak - value) / peak)
    return result


def summarize_portfolio(
    sessions: Sequence[dict[str, Any]] | None,
    *,
    start_capital: float,
    fill_geometries: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize marked equity/deployment and actual/modelled fill geometry."""
    if sessions is None:
        return {
            "evaluation_state": STATE_NOT_RUN,
            "passes": None,
            "metrics": None,
            "geometry": {"valid": 0, "invalid": 0, "all_valid": None},
            "bars": None,
        }
    capital = _finite_number(start_capital, "start_capital")
    if capital <= 0:
        raise ValueError("start_capital must be positive")

    rows = list(sessions)
    equity: list[float] = []
    deployment: list[float] = []
    for index, row in enumerate(rows):
        equity_value = _finite_number(row.get("equity"), f"sessions[{index}].equity")
        deployed = _finite_number(
            row.get("deployed_capital"), f"sessions[{index}].deployed_capital"
        )
        if equity_value <= 0:
            raise ValueError(f"sessions[{index}].equity must be positive")
        if deployed < 0:
            raise ValueError(f"sessions[{index}].deployed_capital must be non-negative")
        equity.append(equity_value)
        deployment.append(deployed / equity_value)

    geometries = [
        entry_geometry(
            row.get("entry_fill"),
            row.get("stop_initial"),
            row.get("target_initial"),
        )
        for row in (fill_geometries or [])
    ]
    invalid_count = sum(not geometry["valid"] for geometry in geometries)
    valid_count = len(geometries) - invalid_count
    net_return = equity[-1] / capital - 1 if equity else None
    drawdown = max_drawdown(equity)
    avg_deployed = float(np.mean(deployment)) if deployment else None
    bars = {
        "net_return_positive": net_return is not None and net_return > 0,
        "max_drawdown_le_40pct": bool(equity) and drawdown <= 0.40,
        "avg_deployed_ge_10pct": avg_deployed is not None and avg_deployed >= 0.10,
        "all_fill_geometry_valid": bool(geometries) and invalid_count == 0,
    }

    if invalid_count:
        state = STATE_INVALID_GEOMETRY
    elif not rows or not geometries:
        state = STATE_INADEQUATE
    else:
        state = STATE_EVALUATED
    return {
        "evaluation_state": state,
        "passes": all(bars.values()) if state == STATE_EVALUATED else False,
        "metrics": {
            "session_count": len(rows),
            "net_return": net_return,
            "max_drawdown": drawdown,
            "average_deployed_capital": avg_deployed,
            "deployment": _distribution(deployment),
        },
        "geometry": {
            "valid": valid_count,
            "invalid": invalid_count,
            "all_valid": bool(geometries) and invalid_count == 0,
            "invalid_reasons": sorted(
                {
                    geometry["reason"]
                    for geometry in geometries
                    if geometry["reason"] is not None
                }
            ),
        },
        "bars": bars,
    }


def matched_return_bootstrap(
    oos_sessions: Sequence[dict[str, Any]] | None,
    *,
    closed_trade_count: int,
    elapsed_session_count: int,
    block_size: int,
    n_bootstrap: int = 2_000,
    seed: int = 0,
    max_attempt_multiplier: int = 100,
) -> dict[str, Any]:
    """Conditional circular blocked bootstrap for the matched OOS band.

    Each source row supplies ``session_return`` and ``closed_trades``.
    Replicates contain exactly ``elapsed_session_count`` sampled sessions and
    are accepted only when their summed close count exactly matches
    ``closed_trade_count``.
    """
    if oos_sessions is None:
        return {
            "evaluation_state": STATE_NOT_RUN,
            "interval_90": None,
            "accepted_replicates": 0,
            "requested_replicates": n_bootstrap,
            "attempts": 0,
        }
    if (
        not isinstance(closed_trade_count, int)
        or isinstance(closed_trade_count, bool)
        or closed_trade_count < 0
    ):
        raise ValueError("closed_trade_count must be a non-negative integer")
    for name, value in (
        ("elapsed_session_count", elapsed_session_count),
        ("block_size", block_size),
        ("n_bootstrap", n_bootstrap),
        ("max_attempt_multiplier", max_attempt_multiplier),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    rows = list(oos_sessions)
    if not rows:
        return {
            "evaluation_state": STATE_INADEQUATE,
            "interval_90": None,
            "accepted_replicates": 0,
            "requested_replicates": n_bootstrap,
            "attempts": 0,
        }
    if closed_trade_count == 0:
        return {
            "evaluation_state": STATE_INADEQUATE,
            "interval_90": None,
            "accepted_replicates": 0,
            "requested_replicates": n_bootstrap,
            "attempts": 0,
            "block_size": block_size,
            "matched_closed_trade_count": closed_trade_count,
            "matched_elapsed_session_count": elapsed_session_count,
            "seed": seed,
        }

    returns: list[float] = []
    closes: list[int] = []
    for index, row in enumerate(rows):
        value = _finite_number(row.get("session_return"), f"oos_sessions[{index}].session_return")
        if value <= -1:
            raise ValueError(f"oos_sessions[{index}].session_return must be greater than -1")
        close_count = row.get("closed_trades")
        if (
            not isinstance(close_count, int)
            or isinstance(close_count, bool)
            or close_count < 0
        ):
            raise ValueError(f"oos_sessions[{index}].closed_trades must be a non-negative integer")
        returns.append(value)
        closes.append(close_count)

    rng = np.random.default_rng(seed)
    accepted: list[float] = []
    attempts = 0
    max_attempts = n_bootstrap * max_attempt_multiplier
    source_n = len(rows)

    while len(accepted) < n_bootstrap and attempts < max_attempts:
        attempts += 1
        sampled_returns: list[float] = []
        sampled_closes: list[int] = []
        while len(sampled_returns) < elapsed_session_count:
            start = int(rng.integers(0, source_n))
            for offset in range(block_size):
                source_index = (start + offset) % source_n
                sampled_returns.append(returns[source_index])
                sampled_closes.append(closes[source_index])
                if len(sampled_returns) == elapsed_session_count:
                    break
        if sum(sampled_closes) != closed_trade_count:
            continue
        accepted.append(float(np.prod(np.asarray(sampled_returns) + 1.0) - 1.0))

    interval = None
    if accepted:
        interval = {
            "lower": float(np.quantile(accepted, 0.05)),
            "upper": float(np.quantile(accepted, 0.95)),
            "confidence": 0.90,
        }
    return {
        "evaluation_state": (
            STATE_EVALUATED if len(accepted) == n_bootstrap else STATE_INADEQUATE
        ),
        "interval_90": interval,
        "accepted_replicates": len(accepted),
        "requested_replicates": n_bootstrap,
        "attempts": attempts,
        "block_size": block_size,
        "matched_closed_trade_count": closed_trade_count,
        "matched_elapsed_session_count": elapsed_session_count,
        "seed": seed,
    }


def build_success_artifact(
    *,
    events: Sequence[dict[str, Any]] | None = None,
    raw_h15_returns: Sequence[float] | None = None,
    portfolio_sessions: Sequence[dict[str, Any]] | None = None,
    portfolio_start_capital: float = 1.0,
    fill_geometries: Sequence[dict[str, Any]] | None = None,
    matched_oos_sessions: Sequence[dict[str, Any]] | None = None,
    matched_closed_trade_count: int = 1,
    matched_elapsed_session_count: int = 1,
    matched_block_size: int = 1,
    min_events: int = MIN_EVENT_COUNT,
    bootstrap_replicates: int = 2_000,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    """Build the success-v2 metrics section for a new study artifact."""
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "event_gate": summarize_events(
            events,
            raw_h15_returns=raw_h15_returns,
            min_events=min_events,
        ),
        "portfolio_gate": summarize_portfolio(
            portfolio_sessions,
            start_capital=portfolio_start_capital,
            fill_geometries=fill_geometries,
        ),
        "matched_oos_band": matched_return_bootstrap(
            matched_oos_sessions,
            closed_trade_count=matched_closed_trade_count,
            elapsed_session_count=matched_elapsed_session_count,
            block_size=matched_block_size,
            n_bootstrap=bootstrap_replicates,
            seed=bootstrap_seed,
        ),
    }
