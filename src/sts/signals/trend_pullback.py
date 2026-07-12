"""Trend-conditioned pullback detector (H1 primary cell: "trend_pullback").

Mechanism (docs/preregs/2026-07-11_h1-trend-pullback.md): a name in a
confirmed weekly uptrend (close above a rising 20-week MA) that prints an
RSI(2) oversold read, then closes back above the prior day's high, is a
short-horizon reversal transacting against standing structural demand, not
against a name in genuine distress.

Only the H1 prereg's PRIMARY cell is implemented here (Trend-1 x Trigger-1 x
Entry-1): weekly close > rising 20-week MA, RSI(2) < 10, entry on the first
reclaim of the prior day's high within `reclaim_max_wait` sessions of the
start of an oversold episode. Secondary grid cells (40-week MA,
consecutive-down-close/20d-SMA-tag triggers, limit-at-level entry) are out
of scope -- the prereg marks them descriptive-only, never load-bearing for
the verdict.

Weekly trend reuses `sts.weekly.resample_weekly` + `align_to_daily` for the
same shift-safety every other weekly consumer in this codebase gets (a
still-forming week is never read as final): the daily-aligned uptrend flag
rides through `align_to_daily`'s own `close` column since that function's
as-of join only knows OHLCV column names.

RSI(2) uses Wilder smoothing (`ewm(alpha=1/window, adjust=False)`), matching
`sts.risk.atr`'s own choice of simplicity over the classic recursive
smoother.

The oversold-episode-to-reclaim search is a small per-symbol scan, not
vectorized: oversold reads are sparse (RSI(2) < 10 is a tail event), so this
is cheap in practice and easier to reason about than a stateful vectorized
formulation. An "episode" is a maximal run of consecutive oversold days;
only the FIRST day of an episode starts a reclaim search, so a 3-day
oversold stretch resolves to at most one event, not one per day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sts.models import SignalEvent
from sts.weekly import align_to_daily, resample_weekly

DEFAULTS = {
    "weekly_ma_window": 20,
    "weekly_rising_lag": 4,
    "rsi_window": 2,
    "rsi_oversold": 10.0,
    "reclaim_max_wait": 10,
    "swing_window": 60,
}


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(avg_loss != 0.0, 100.0)


def _weekly_uptrend_daily(df: pd.DataFrame, p: dict) -> pd.Series:
    weekly = resample_weekly(df)
    if weekly.empty:
        return pd.Series(False, index=df.index)
    ma = weekly["close"].rolling(p["weekly_ma_window"]).mean()
    rising = ma > ma.shift(p["weekly_rising_lag"])
    uptrend = ((weekly["close"] > ma) & rising).fillna(False)
    carrier = weekly.copy()
    carrier["close"] = uptrend.astype(float)
    aligned = align_to_daily(carrier, df.index)["week_close"]
    return (aligned == 1.0).fillna(False)


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}
    high, low, close = df["high"], df["low"], df["close"]

    uptrend = _weekly_uptrend_daily(df, p)
    rsi2 = _rsi(close, p["rsi_window"])
    oversold = (rsi2 < p["rsi_oversold"]).fillna(False)
    episode_start = oversold & ~oversold.shift(1, fill_value=False)

    swing_low = low.shift(1).rolling(p["swing_window"]).min()
    swing_high = high.shift(1).rolling(p["swing_window"]).max()
    prior_high = high.shift(1)

    n = len(df)
    trigger_ilocs = np.flatnonzero((uptrend & episode_start).to_numpy())

    events: list[SignalEvent] = []
    for trig_i in trigger_ilocs:
        window_end = min(trig_i + p["reclaim_max_wait"], n - 1)
        for j in range(trig_i + 1, window_end + 1):
            if not bool(uptrend.iloc[j]):
                break
            ph = prior_high.iloc[j]
            if pd.isna(ph) or not (close.iloc[j] > ph):
                continue
            if pd.isna(swing_low.iloc[j]) or pd.isna(swing_high.iloc[j]):
                break
            ts = df.index[j]
            events.append(
                SignalEvent(
                    symbol=symbol,
                    date=ts.date(),
                    config_name=config_name,
                    params=dict(p),
                    trigger_values={
                        "swing_low": float(swing_low.iloc[j]),
                        "swing_high": float(swing_high.iloc[j]),
                        "rsi2_at_trigger": float(rsi2.iloc[trig_i]),
                        "reclaim_wait_sessions": int(j - trig_i),
                        "close": float(close.iloc[j]),
                    },
                )
            )
            break
    return events
