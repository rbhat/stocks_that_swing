"""Signal-level (event) exit simulation — gate v2's layer-1 evidence.

Runs a config's detector over a dict of price frames and simulates every
event INDEPENDENTLY through the real `stm.risk` structure: entry at the next
bar's open, 30% initial stop, Fibonacci targets from the event's
`swing_low`/`swing_high`, bar-by-bar `risk.manage_bar`, and any remainder
still open at the end of the frame censored at the last available close.
This is the proven §1b study template (see `.scratch/avwap_feature_study.py`
`exit_sim_r`) promoted into `src` so validation can use it.

Independent-event convention (documented caveat, same as every §1b study):
no portfolio caps, no slot competition, no slippage, no commissions — each
event is one full hypothetical position, so R measures the SIGNAL, not the
book's expression of it. `stm.backtest` measures the book; both layers
appear in the validation artifact.

`max_sessions` (the censoring-matched in-sample arm): `manage_bar` runs
through the boundary bar inclusive (bars_held == max_sessions), then any
residual shares are censored at that bar's CLOSE — the same last-close
censoring used at end-of-frame, so `max_sessions=None` is the natural limit.
This is a study censoring convention, deliberately NOT the engine's
`time_exit` hook (which flattens at the open with its own exit reason).

`catalyst_guard` params are deliberately ignored here: the entry embargo is
measured ~0R (decisions.md 2026-07-04 3-arm A/B), the pre-event exit leg is
disabled (`-1`) on every live config, and the wide study roster has no
calendar coverage anyway. The guard is exercised at layer 2 (the portfolio
OOS backtest) where a real calendar exists.

Deterministic: no RNG anywhere in this module.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from sts import risk
from sts.signals import resolve_detector

# One-sided 90% normal quantile for the lower confidence bound on mean R.
_Z_90 = 1.2816


def simulate_events(
    prices: dict[str, pd.DataFrame],
    config_name: str,
    params: dict,
    start: dt.date | None = None,
    end: dt.date | None = None,
    max_sessions: int | None = None,
) -> dict:
    """Detect and exit-sim every event of `config_name` over `prices`.

    `start`/`end` filter EVENT dates (`start <= event.date < end`); the
    frames themselves are used as given — pre-`start` bars are legal detector
    warmup (the `split_prices` contract), and enforcing a data wall is the
    caller's job (pass frames already truncated at the wall).

    Returns a summary dict (never the raw per-event list — artifacts stay
    small): n, expectancy_r, expectancy_r_lower90 (one-sided 90% lower bound
    of mean R, normal approximation; None when n < 2), n_skipped (no next
    bar / bad swings / degenerate fib targets), n_censored (closed by the
    `max_sessions` cap or the end of the frame), median_hold_sessions, and
    by_year {"YYYY": {"n", "expectancy_r"}} keyed by the event's fire year.
    """
    detector = resolve_detector(config_name)
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
        for ev in detector(symbol, df, params, config_name):
            if start is not None and ev.date < start:
                continue
            if end is not None and ev.date >= end:
                continue
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                n_skipped += 1
                continue
            sim = _sim_one(
                df, sig_iloc,
                ev.trigger_values.get("swing_low"),
                ev.trigger_values.get("swing_high"),
                max_sessions,
            )
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
    swing_low: float | None,
    swing_high: float | None,
    max_sessions: int | None,
) -> tuple[float, int, bool] | None:
    """One event through the risk structure. Returns (r_multiple,
    hold_sessions, censored) or None if the event is unusable (no next bar,
    missing/degenerate swings, non-positive entry)."""
    idx = df.index
    entry_iloc = sig_iloc + 1
    if entry_iloc >= len(idx):
        return None
    entry = float(df["open"].iloc[entry_iloc])
    if not np.isfinite(entry) or entry <= 0:
        return None
    if swing_low is None or swing_high is None:
        return None
    stop = risk.initial_stop(entry)
    try:
        targets = risk.fib_targets(swing_low, swing_high, entry)
    except ValueError:
        return None

    pos = risk.Position(
        symbol="EVENT", entry=entry, shares=100, stop=stop, initial_stop=stop,
        targets=targets, opened=idx[entry_iloc].date(), config="eventsim",
    )
    slices: list[tuple[float, int]] = []
    censored = False
    exit_iloc = entry_iloc
    j = entry_iloc + 1
    while j < len(idx) and pos.shares > 0:
        row = df.iloc[j]
        for _reason, price, shares in risk.manage_bar(
            pos, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        ):
            slices.append((price, shares))
            exit_iloc = j
        if pos.shares > 0 and max_sessions is not None and (j - entry_iloc) >= max_sessions:
            slices.append((float(row["close"]), pos.shares))
            pos.shares = 0
            censored = True
            exit_iloc = j
        j += 1
    if pos.shares > 0:
        slices.append((float(df["close"].iloc[-1]), pos.shares))
        pos.shares = 0
        censored = True
        exit_iloc = len(idx) - 1

    total_shares = sum(s for _, s in slices)
    if total_shares <= 0:
        return None
    wavg_exit = sum(p * s for p, s in slices) / total_shares
    return risk.r_multiple(entry, wavg_exit, stop), exit_iloc - entry_iloc, censored
