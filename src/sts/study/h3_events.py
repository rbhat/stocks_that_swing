"""H3 event collection: the H1 per-event walk generalized to any registered
detector family, for the re-geometried breakout/squeeze study
(docs/HYPOTHESES.md §H3). Detectors run verbatim on their studied DEFAULTS —
zero re-tuning is the study's premise — and every event is managed
swing-native exactly as in `sts.study.h1_events` (ATR stop/target,
`risk.manage_bar` walk, charter cost-in-R approximation, 2-session
pre-earnings entry embargo). `summarize` / `slice_by` / `cost_r` are reused
from h1_events so the two studies share one evidence contract.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from sts import risk
from sts.catalyst import CatalystCalendar
from sts.signals import resolve_detector
from sts.study.h1_events import _PARAM_DEFAULTS, cost_r, entry_geometry


def _simulate_event(
    symbol: str, df: pd.DataFrame, sig_iloc: int, atr_series: pd.Series, p: dict, config_name: str
) -> dict | None:
    """Same walk as h1_events._simulate_event, with the event's own config
    name recorded on the Position instead of a hardcoded one."""
    geo = entry_geometry(df, sig_iloc, atr_series, p)
    if geo is None:
        return None
    idx = df.index
    entry_iloc, entry, stop, target = geo["entry_iloc"], geo["entry"], geo["stop"], geo["target"]
    try:
        pos = risk.Position(
            symbol=symbol, entry=entry, shares=1, stop=stop, target=target,
            opened=idx[entry_iloc].date(), config=config_name,
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
            reason, price, _shares = exits[0]
            r = risk.r_multiple(entry, price, stop)
            return {
                "entry": entry, "stop": stop, "r_gross": r,
                "hold_sessions": j - entry_iloc, "censored": False,
                "exit_reason": reason, "entry_date": idx[entry_iloc].date(),
            }
        j += 1

    exit_price = float(df["close"].iloc[-1])
    r = risk.r_multiple(entry, exit_price, stop)
    return {
        "entry": entry, "stop": stop, "r_gross": r,
        "hold_sessions": len(idx) - 1 - entry_iloc, "censored": True,
        "exit_reason": "censored", "entry_date": idx[entry_iloc].date(),
    }


def collect_events(
    prices: dict[str, pd.DataFrame],
    config_name: str,
    detector_params: dict,
    start: dt.date,
    end: dt.date,
    cost_arms: dict[str, tuple[float, float]],
    catalyst_calendar: CatalystCalendar | None = None,
    risk_params: dict | None = None,
) -> list[dict]:
    """Per-event rows for one H3 cell, event `signal_date` in [start, end).
    Semantics match h1_events.collect_events exactly (skip-not-loss earnings
    embargo, per-arm `r_net_{arm}` columns); only the detector differs."""
    detect = resolve_detector(config_name)
    p = {**_PARAM_DEFAULTS, **(risk_params or {})}
    cal = catalyst_calendar if catalyst_calendar is not None else CatalystCalendar.load()

    rows: list[dict] = []
    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in detect(symbol, df, detector_params, config_name):
            if ev.date < start or ev.date >= end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            sim = _simulate_event(symbol, df, sig_iloc, atr_series, p, config_name)
            if sim is None:
                continue
            if cal.catalyst_within(symbol, sim["entry_date"], 2, "block_entry") is not None:
                continue
            row = {"symbol": symbol, "signal_date": ev.date, **sim}
            for arm_name, (bps, fee) in cost_arms.items():
                row[f"r_net_{arm_name}"] = sim["r_gross"] - cost_r(sim["entry"], sim["stop"], bps, fee)
            rows.append(row)
    return rows
