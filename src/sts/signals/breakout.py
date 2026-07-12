"""Consolidation breakout detector ("consolidation_breakout_v1").

Idea: a tight multi-week range with volume dried up, then a close above the
range high on volume waking back up.

All windows are computed on bars strictly before today (`shift(1)` then
rolling) so nothing here can see today's high/low/close/volume except the
two values that define the trigger itself: today's close and today's
volume. This makes the detector safe to run session-by-session (backtest
replay) or on the full history at once (forward job) — results for a given
date never change when future bars are appended.

`swing_low`/`swing_high` in `trigger_values` feed the risk layer's Fibonacci
targets and are deliberately wider than the `lookback` consolidation range:
they're the rolling min low / max high over the prior `swing_window` bars,
so a fib extension has real structure behind it instead of the tight
20-bar box. The consolidation-range stats (`range_pct`, `tight`, the
breakout level itself) still use `lookback`.
"""

from __future__ import annotations

import pandas as pd

from sts.models import SignalEvent

DEFAULTS = {
    "lookback": 20,
    "max_range_pct": 0.10,
    "quiet_window": 10,
    "quiet_vol_ratio": 0.8,
    "breakout_vol_ratio": 1.5,
    "swing_window": 60,
}


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}
    lookback = p["lookback"]
    quiet_window = p["quiet_window"]
    swing_window = p["swing_window"]

    high, low = df["high"], df["low"]
    close, volume = df["close"], df["volume"]

    # Prior-window (excludes today) range and volume stats.
    prior_high = high.shift(1).rolling(lookback).max()
    prior_low = low.shift(1).rolling(lookback).min()
    range_pct = (prior_high - prior_low) / prior_low
    lookback_mean_vol = volume.shift(1).rolling(lookback).mean()
    quiet_mean_vol = volume.shift(1).rolling(quiet_window).mean()

    # Wider prior-window swing points, for fib targets only (see docstring).
    swing_low = low.shift(1).rolling(swing_window).min()
    swing_high = high.shift(1).rolling(swing_window).max()

    tight = range_pct <= p["max_range_pct"]
    quiet_then_awake = quiet_mean_vol <= p["quiet_vol_ratio"] * lookback_mean_vol
    # lookback_mean_vol can be 0 (a symbol with genuine zero-volume bars):
    # guard so 0/0 (NaN) and x/0 (inf) both read as "not loud" instead of
    # letting inf silently pass the >= threshold.
    volume_ratio = volume / lookback_mean_vol
    loud_today = (lookback_mean_vol > 0) & (volume_ratio >= p["breakout_vol_ratio"])
    breaks_out = close > prior_high

    # Swing window must be warm: NaN swings would silently ride the risk
    # layer's 2R fallback instead of real fib structure — suppress instead.
    swings_warm = swing_low.notna() & swing_high.notna()

    triggered = tight & quiet_then_awake & loud_today & breaks_out & swings_warm
    triggered = triggered.fillna(False)

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
                    "range_pct": float(range_pct.loc[ts]),
                    "volume_ratio": float(volume_ratio.loc[ts]),
                    "close": float(close.loc[ts]),
                },
            )
        )
    return events
