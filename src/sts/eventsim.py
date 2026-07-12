"""Signal-level (event) exit simulation — this project's Phase-2 harness.

Runs a detector over a dict of price frames and simulates every event
INDEPENDENTLY through `sts.risk`'s swing-native exit structure: ATR- or
structure-anchored stop, ATR- or structure-anchored target, and the hard
15-session time stop, managed bar-by-bar via `risk.manage_bar`. Entry is
always the next bar's open after the signal fires.

Two-layer read (docs/PLAN.md Phase 2, docs/HYPOTHESES.md "bars shape"):
- Layer (a), `raw_forward_returns`: exit-free forward returns at fixed
  horizons — the entry's raw price edge in isolation, no stop, no target,
  no time cap.
- Layer (b), `simulate_events`: the same events run through the full swing
  exit structure, reported as R multiples (expectancy).
Layer (a) must be positive on its own; a family that only wins after
exit-sim is an exit artifact, not a real signal (docs/HYPOTHESES.md).

Independent-event convention (documented explicitly, not inherited): no
portfolio caps, no slot competition, no slippage, no commissions — each
event is one full hypothetical position, so this module measures the
SIGNAL, not the book. A future portfolio-level backtest (out of scope here)
would measure the book; both layers would appear side by side in a study
artifact.

No lookahead: the ATR value used for an event's stop/target is read at the
SIGNAL bar (known by that day's close), never at or after the entry bar —
the same no-lookahead convention `sts.signals.breakout` already uses for
its own rolling windows.

Deterministic: no RNG anywhere in this module.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

import numpy as np
import pandas as pd

from sts import risk
from sts.models import SignalEvent
from sts.signals import resolve_detector

# One-sided 90% normal quantile for the lower confidence bound on mean R.
_Z_90 = 1.2816

Detector = Callable[[str, pd.DataFrame, dict, str], list[SignalEvent]]

_PARAM_DEFAULTS = {
    "atr_window": risk.DEFAULT_ATR_WINDOW,
    "stop_mode": "atr",
    "target_mode": "atr",
    "atr_stop_multiple": 2.0,
    "atr_target_multiple": 2.0,
}


def simulate_events(
    prices: dict[str, pd.DataFrame],
    config_name: str,
    params: dict,
    start: dt.date | None = None,
    end: dt.date | None = None,
    detector: Detector | None = None,
) -> dict:
    """Detect and exit-sim every event of `config_name` over `prices`.

    `detector`, if given, is called directly instead of resolving
    `config_name` via `sts.signals.resolve_detector` — same contract as any
    registered detector (`detector(symbol, df, params, config_name) ->
    list[SignalEvent]`). This lets tests (and ad hoc negative controls)
    drive the simulator without registering a config.

    `params` (all optional, `params={}` runs with ATR-based defaults):
    - "atr_window" (int, default 14)
    - "stop_mode" / "target_mode": "atr" | "structure" (default "atr")
    - "atr_stop_multiple" / "atr_target_multiple" (float, default 2.0)
    In "structure" mode, the stop/target level is read from the event's
    `trigger_values["stop_level"]` / `["target_level"]` — a study wires
    whatever structure price it wants directly; this module doesn't know or
    care how it was derived. An event missing the level it needs is skipped.

    `start`/`end` filter EVENT dates (`start <= event.date < end`); the
    frames themselves are used as given — pre-`start` bars are legal
    detector warmup, and enforcing a data wall is the caller's job (pass
    frames already truncated at the wall).

    Returns a summary dict (never the raw per-event list — artifacts stay
    small): n, expectancy_r, expectancy_r_lower90 (one-sided 90% lower bound
    of mean R, normal approximation; None when n < 2), n_skipped (no next
    bar / non-finite entry / ATR not warm / missing structure level /
    invalid stop-target construction), n_censored (still open when the
    frame runs out — the ONLY form of censoring, since the 15-session hard
    time stop lives inside `risk.manage_bar` and always resolves a position
    by then), median_hold_sessions, and by_year {"YYYY": {"n",
    "expectancy_r"}} keyed by the event's fire year.
    """
    p = {**_PARAM_DEFAULTS, **params}
    detect = detector if detector is not None else resolve_detector(config_name)

    rs: list[float] = []
    holds: list[int] = []
    n_skipped = 0
    n_censored = 0
    by_year: dict[str, list[float]] = {}

    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in detect(symbol, df, params, config_name):
            if start is not None and ev.date < start:
                continue
            if end is not None and ev.date >= end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                n_skipped += 1
                continue
            sim = _sim_one(df, sig_iloc, atr_series, ev, p)
            if sim is None:
                n_skipped += 1
                continue
            r, hold, censored = sim
            rs.append(r)
            holds.append(hold)
            n_censored += int(censored)
            by_year.setdefault(str(ev.date.year), []).append(r)

    n = len(rs)
    arr = np.asarray(rs, dtype=float)
    expectancy = float(arr.mean()) if n else 0.0
    lower90 = None
    if n >= 2:
        sd = float(arr.std(ddof=1))
        lower90 = expectancy - _Z_90 * sd / n ** 0.5

    return {
        "n": n,
        "expectancy_r": expectancy,
        "expectancy_r_lower90": lower90,
        "n_skipped": n_skipped,
        "n_censored": n_censored,
        "median_hold_sessions": float(np.median(holds)) if holds else None,
        "by_year": {
            year: {"n": len(vals), "expectancy_r": float(np.mean(vals))}
            for year, vals in sorted(by_year.items())
        },
    }


def _sim_one(
    df: pd.DataFrame,
    sig_iloc: int,
    atr_series: pd.Series,
    ev: SignalEvent,
    p: dict,
) -> tuple[float, int, bool] | None:
    """One event through the risk structure. Returns (r_multiple,
    hold_sessions, censored) or None if the event is unusable."""
    idx = df.index
    entry_iloc = sig_iloc + 1
    if entry_iloc >= len(idx):
        return None
    entry = float(df["open"].iloc[entry_iloc])
    if not np.isfinite(entry) or entry <= 0:
        return None

    stop_mode = p["stop_mode"]
    target_mode = p["target_mode"]
    needs_atr = stop_mode == "atr" or target_mode == "atr"
    atr_value = None
    if needs_atr:
        atr_value = atr_series.iloc[sig_iloc]
        if not np.isfinite(atr_value):
            return None

    try:
        if stop_mode == "structure":
            level = ev.trigger_values.get("stop_level")
            if level is None:
                return None
            stop = risk.structure_stop(entry, float(level))
        else:
            stop = risk.atr_stop(entry, float(atr_value), p["atr_stop_multiple"])

        if target_mode == "structure":
            level = ev.trigger_values.get("target_level")
            if level is None:
                return None
            target = risk.structure_target(float(level))
        else:
            target = risk.atr_target(entry, float(atr_value), p["atr_target_multiple"])

        pos = risk.Position(
            symbol=ev.symbol,
            entry=entry,
            shares=1,
            stop=stop,
            target=target,
            opened=idx[entry_iloc].date(),
            config=ev.config_name,
        )
    except (ValueError, risk.RuleViolation):
        return None

    j = entry_iloc + 1
    exit_iloc = entry_iloc
    r: float | None = None
    censored = False
    while j < len(idx):
        row = df.iloc[j]
        exits = risk.manage_bar(
            pos, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        )
        if exits:
            _reason, price, _shares = exits[0]
            r = risk.r_multiple(entry, price, stop)
            exit_iloc = j
            break
        j += 1
    else:
        # Frame ran out with the position still open: censor at last close.
        exit_price = float(df["close"].iloc[-1])
        r = risk.r_multiple(entry, exit_price, stop)
        exit_iloc = len(idx) - 1
        censored = True

    return r, exit_iloc - entry_iloc, censored


def raw_forward_returns(
    prices: dict[str, pd.DataFrame],
    config_name: str,
    params: dict,
    horizons: tuple[int, ...] = (5, 10, 15),
    start: dt.date | None = None,
    end: dt.date | None = None,
    detector: Detector | None = None,
) -> dict:
    """Layer (a): exit-free raw forward returns for every event.

    Entry = next bar's open (same convention as `simulate_events`). For each
    horizon `h`, forward return = close[entry_iloc + h] / entry - 1, skipped
    (not counted, for that horizon only) when entry_iloc + h is out of
    bounds. No stop, no target, no time cap — this measures the entry's raw
    price edge in isolation, before any exit structure is applied.

    Returns {"n_events": int, "by_horizon": {h: {"n", "mean_return",
    "median_return"}}}. Empty-safe: n=0 and mean/median=None when there are
    no valid observations for a horizon (or no events at all) — never
    raises.
    """
    detect = detector if detector is not None else resolve_detector(config_name)
    n_events = 0
    by_horizon_returns: dict[int, list[float]] = {h: [] for h in horizons}

    for symbol in sorted(prices):
        df = prices[symbol]
        if df is None or df.empty:
            continue
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        close = df["close"]
        for ev in detect(symbol, df, params, config_name):
            if start is not None and ev.date < start:
                continue
            if end is not None and ev.date >= end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            entry_iloc = sig_iloc + 1
            if entry_iloc >= len(df.index):
                continue
            entry = float(df["open"].iloc[entry_iloc])
            if not np.isfinite(entry) or entry <= 0:
                continue
            n_events += 1
            for h in horizons:
                target_iloc = entry_iloc + h
                if target_iloc >= len(df.index):
                    continue
                fwd_close = float(close.iloc[target_iloc])
                if not np.isfinite(fwd_close):
                    continue
                by_horizon_returns[h].append(fwd_close / entry - 1)

    by_horizon = {}
    for h in horizons:
        vals = by_horizon_returns[h]
        if vals:
            arr = np.asarray(vals, dtype=float)
            by_horizon[h] = {
                "n": len(vals),
                "mean_return": float(arr.mean()),
                "median_return": float(np.median(arr)),
            }
        else:
            by_horizon[h] = {"n": 0, "mean_return": None, "median_return": None}

    return {"n_events": n_events, "by_horizon": by_horizon}
