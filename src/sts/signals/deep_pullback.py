"""Deep-pullback volume-return detector ("deep_pullback_v1").

Idea (transcripts/momentum_and_squeeze.md): "deep pullbacks, low volume, then
volume surge" — a real prior swing pulls back deep (0.618+ retracement),
volume dries up while it does, and the entry trigger is the volume-surge up
day, not the depth itself. Scratch-study evidence: decisions.md 2026-07-04
(PROCEED — marginal: only the h=63 lift leg cleared the 70% year-slice bar;
the contrary discount-zone prior of 2026-07-02 is on record). Pre-registered
§1b protocol, 60 symbols, 1962-2024.

Same shift-safety discipline as sweep_reclaim.py: the swing (and hence the
retracement level) is computed from bars strictly before today, as is the
volume baseline and the dry-up window. Today contributes its own low to the
pullback window (the deepest print may be today's), its own volume to the
surge test, and its own close (the up-day / held-not-broken checks). Results
for a given date never change when future bars are appended, so full-history
and session-by-session runs are identical.

`swing_low`/`swing_high` in `trigger_values` feed the risk layer's Fibonacci
targets (interface contract shared by all families) — the same
prior-`swing_window` extremes that define the retracement level extend into
the targets for the very swing that was pulled back into.
"""

from __future__ import annotations

import pandas as pd

from sts.models import SignalEvent

DEFAULTS = {
    "swing_window": 60,
    "fib_deep": 0.618,
    "pullback_low_window": 5,
    "dryup_window": 5,
    "vol_base_window": 20,
    "dryup_ratio": 0.8,
    "surge_ratio": 1.5,
}


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}

    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

    # Prior-window swing extremes (exclude today), as in sweep_reclaim.py.
    swing_low = low.shift(1).rolling(p["swing_window"]).min()
    swing_high = high.shift(1).rolling(p["swing_window"]).max()
    level = swing_high - p["fib_deep"] * (swing_high - swing_low)

    # The pullback: the lowest low over the last `pullback_low_window` bars,
    # including today (today's own low may be the deepest print).
    pullback_low = low.rolling(p["pullback_low_window"]).min()

    # Volume baseline and the dry-up window, both computed from bars strictly
    # before today so the surge test below has an untainted comparison point.
    vol_base = volume.shift(1).rolling(p["vol_base_window"]).median()
    vol_recent = volume.shift(1).rolling(p["dryup_window"]).median()

    deep = pullback_low <= level
    held = close > swing_low
    dryup = vol_recent < p["dryup_ratio"] * vol_base
    surge = volume >= p["surge_ratio"] * vol_base
    up_day = close > close.shift(1)

    # Degenerate or cold swing windows / volume baselines are suppressed,
    # never defaulted: a NaN or flat swing has no retracement level, and a
    # zero or NaN baseline makes the dry-up/surge ratios meaningless.
    swings_warm = swing_low.notna() & swing_high.notna() & (swing_high > swing_low)
    vol_warm = vol_base.notna() & (vol_base > 0)

    triggered = (deep & held & dryup & surge & up_day & swings_warm & vol_warm).fillna(False)

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
                    "pullback_low": float(pullback_low.loc[ts]),
                    "close": float(close.loc[ts]),
                    "vol_ratio": float(volume.loc[ts] / vol_base.loc[ts]),
                },
            )
        )
    return events
