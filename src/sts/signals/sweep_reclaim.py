"""Liquidity-sweep reclaim detector ("sweep_reclaim_v1").

Idea (transcripts/fibonacci_with_liquidity_sweeps.md): in a structure with a
real prior swing, price sweeps below the 0.618 retracement of the swing —
taking out stops resting under the "discount zone" — then closes back above
it. The close back above the level is the entry trigger, never the sweep
itself. Scratch-study evidence: decisions.md 2026-07-03 (PROCEED; 60
symbols, 63 years, pre-registered §1b protocol).

Only the `sweep_fib` variant from that study is implemented. The companion
`reclaim_level` variant (reclaim of the prior swing low after a breakdown
close, transcripts/liquidity.md) is PARKED per the study — 34 events across
60 symbols is far below the pre-registered n>=300 adequacy bar — and stays
in tested_signals.md §1a with its unmet data requirement rather than in code.

All levels are computed from bars strictly before today (`shift(1)` then
rolling), same discipline as breakout.py: today contributes only its own
low (the pierce) and close (the reclaim). Results for a given date never
change when future bars are appended, so full-history and session-by-session
runs are identical.

`swing_low`/`swing_high` in `trigger_values` feed the risk layer's Fibonacci
targets (interface contract shared by all families). They are the same
prior-`swing_window` extremes that define the retracement level, so the
targets extend the very swing whose discount zone was swept.
"""

from __future__ import annotations

import pandas as pd

from sts.models import SignalEvent

DEFAULTS = {
    "swing_window": 60,
    "fib_retrace": 0.618,
    "pierce_window": 3,
}


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}
    swing_window = p["swing_window"]
    pierce_window = p["pierce_window"]

    high, low, close = df["high"], df["low"], df["close"]

    # Prior-window swing extremes (exclude today), as in breakout.py.
    swing_low = low.shift(1).rolling(swing_window).min()
    swing_high = high.shift(1).rolling(swing_window).max()
    level = swing_high - p["fib_retrace"] * (swing_high - swing_low)

    # The sweep: some bar in the last `pierce_window` bars (including today)
    # traded below the level. `sweep_low` records how deep it went.
    sweep_low = low.rolling(pierce_window).min()
    pierced = sweep_low < level

    # The reclaim: today closes back above the level, and this is either the
    # first close back above (yesterday still closed at/below yesterday's
    # level) or a same-bar hammer sweep (today's own low pierced intraday).
    reclaimed = close > level
    fresh = (close.shift(1) <= level.shift(1)) | (low < level)

    # Degenerate or cold swing windows are suppressed, never defaulted: a
    # NaN or flat swing has no retracement level and no fib structure.
    swings_warm = swing_low.notna() & swing_high.notna() & (swing_high > swing_low)

    triggered = (pierced & reclaimed & fresh & swings_warm).fillna(False)

    events: list[SignalEvent] = []
    for ts in df.index[triggered]:
        events.append(
            SignalEvent(
                symbol=symbol,
                date=ts.date(),
                config_name=config_name,
                params=dict(p),
                trigger_values={
                    "swing_low": float(swing_low.loc[ts]),
                    "swing_high": float(swing_high.loc[ts]),
                    "level": float(level.loc[ts]),
                    "sweep_low": float(sweep_low.loc[ts]),
                    "close": float(close.loc[ts]),
                },
            )
        )
    return events
