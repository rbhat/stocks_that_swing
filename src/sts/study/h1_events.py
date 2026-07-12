"""H1 primary-cell event collection: per-event rows with an approximate
cost model, since the general per-event evidence contract (codex_review.md
#2 -- audited gross/base-cost/2x-cost R, right-censoring treatment,
slippage-vs-fee definition) is still deferred. This module's cost-in-R is a
disclosed approximation against a charter risk-budgeted reference position
(`risk.position_size` at `risk.START_CAPITAL`), not the audited contract --
see docs/preregs/2026-07-11_h1-trend-pullback.md "Known caveats", which
explicitly permits stating this limitation rather than blocking the study on
it.

The event walk below mirrors `sts.eventsim`'s ATR-mode walk (risk starts at
the entry bar itself, per the Fix-1 convention) rather than importing that
module's private `_sim_one`, so this module owns its own per-event contract
independently of eventsim's internals.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from sts import risk
from sts.catalyst import CatalystCalendar
from sts.signals.trend_pullback import DEFAULTS as TREND_PULLBACK_DEFAULTS
from sts.signals.trend_pullback import detect as detect_trend_pullback

_Z_90 = 1.2816  # one-sided 90% normal quantile, same constant as sts.eventsim

_PARAM_DEFAULTS = {
    "atr_window": risk.DEFAULT_ATR_WINDOW,
    "atr_stop_multiple": 2.0,
    "atr_target_multiple": 2.0,
}


def cost_r(entry: float, stop: float, bps_per_side: float, per_order: float) -> float:
    """Round-trip friction in R against a charter risk-budgeted reference
    position. Returns 0.0 if the reference position would size to 0 shares
    (stop distance too wide relative to the charter's caps)."""
    shares = risk.position_size(risk.START_CAPITAL, entry, stop)
    if shares <= 0:
        return 0.0
    stop_distance = entry - stop
    bps_cost = entry * (bps_per_side / 10_000) * 2
    order_cost_per_share = (per_order * 2) / shares
    return (bps_cost + order_cost_per_share) / stop_distance


def _simulate_event(symbol: str, df: pd.DataFrame, sig_iloc: int, atr_series: pd.Series, p: dict) -> dict | None:
    idx = df.index
    entry_iloc = sig_iloc + 1
    if entry_iloc >= len(idx):
        return None
    entry = float(df["open"].iloc[entry_iloc])
    if not np.isfinite(entry) or entry <= 0:
        return None
    atr_value = atr_series.iloc[sig_iloc]
    if not np.isfinite(atr_value):
        return None
    stop = risk.atr_stop(entry, float(atr_value), p["atr_stop_multiple"])
    target = risk.atr_target(entry, float(atr_value), p["atr_target_multiple"])
    try:
        pos = risk.Position(
            symbol=symbol, entry=entry, shares=1, stop=stop, target=target,
            opened=idx[entry_iloc].date(), config="trend_pullback",
        )
    except (ValueError, risk.RuleViolation):
        return None

    j = entry_iloc
    while j < len(idx):
        row = df.iloc[j]
        exits = risk.manage_bar(
            pos, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        )
        if exits:
            _reason, price, _shares = exits[0]
            r = risk.r_multiple(entry, price, stop)
            return {
                "entry": entry, "stop": stop, "r_gross": r,
                "hold_sessions": j - entry_iloc, "censored": False,
                "entry_date": idx[entry_iloc].date(),
            }
        j += 1

    exit_price = float(df["close"].iloc[-1])
    r = risk.r_multiple(entry, exit_price, stop)
    return {
        "entry": entry, "stop": stop, "r_gross": r,
        "hold_sessions": len(idx) - 1 - entry_iloc, "censored": True,
        "entry_date": idx[entry_iloc].date(),
    }


def collect_events(
    prices: dict[str, pd.DataFrame],
    start: dt.date,
    end: dt.date,
    cost_arms: dict[str, tuple[float, float]],
    catalyst_calendar: CatalystCalendar | None = None,
    params: dict | None = None,
) -> list[dict]:
    """Per-event rows for the H1 primary cell, event `signal_date` in
    [start, end). `cost_arms` maps arm name -> (bps_per_side, per_order); a
    `r_net_{arm}` column is added per arm. An event is skipped (never
    counted, not even as a loss) if its entry date falls within 2 sessions
    before a scheduled earnings date on `catalyst_calendar` (`block_entry`
    only -- holding through earnings once entered is permitted, same as the
    prereg and eventsim's own convention)."""
    p = {**_PARAM_DEFAULTS, **(params or {})}
    cal = catalyst_calendar if catalyst_calendar is not None else CatalystCalendar.load()

    rows: list[dict] = []
    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in detect_trend_pullback(symbol, df, TREND_PULLBACK_DEFAULTS, "trend_pullback"):
            if ev.date < start or ev.date >= end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            sim = _simulate_event(symbol, df, sig_iloc, atr_series, p)
            if sim is None:
                continue
            if cal.catalyst_within(symbol, sim["entry_date"], 2, "block_entry") is not None:
                continue
            row = {"symbol": symbol, "signal_date": ev.date, **sim}
            for arm_name, (bps, fee) in cost_arms.items():
                row[f"r_net_{arm_name}"] = sim["r_gross"] - cost_r(sim["entry"], sim["stop"], bps, fee)
            rows.append(row)
    return rows


def summarize(rows: list[dict], r_key: str = "r_gross") -> dict:
    """n / expectancy_r / expectancy_r_lower90 (one-sided 90% normal lower
    bound, None when n < 2) over `rows[*][r_key]`."""
    vals = [row[r_key] for row in rows]
    n = len(vals)
    arr = np.asarray(vals, dtype=float)
    expectancy = float(arr.mean()) if n else 0.0
    lower90 = None
    if n >= 2:
        sd = float(arr.std(ddof=1))
        lower90 = expectancy - _Z_90 * sd / n ** 0.5
    return {"n": n, "expectancy_r": expectancy, "expectancy_r_lower90": lower90}


def slice_by(rows: list[dict], key_fn) -> dict[str, dict]:
    """Group `rows` by `key_fn(row)`, `summarize` each group, sorted by key."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    return {k: summarize(v) for k, v in sorted(groups.items())}
