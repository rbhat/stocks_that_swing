"""Volatility squeeze detector ("vol_squeeze_v1").

Idea: volatility dries up to a local extreme (yesterday's ATR sits in the
bottom of its own recent history), then today's range expands with an up
close near the top of the bar.

ATR here is the SIMPLE rolling mean of true range (not Wilder's smoothed
average) — chosen for readability over the classic recursive smoothing.

No lookahead: the squeeze percentile and expansion check are both built
from yesterday's ATR (`atr.shift(1)`), so everything but today's true range
and close/close_pos uses bars strictly before today. Safe to run on a
truncated or full frame with identical results for past dates.

`trend_filter` param (§5-C1 earned axis, pre-registered in
.scratch/vol_squeeze_trendfilter_grid_prereg.md): optionally requires a
trend state at the event bar before a squeeze event is kept. Three values —
"none" (default; byte-identical to the un-filtered detector), "bos_bullish"
(break-of-structure state, provenance transcripts/identifying_the_trend.md),
and "avwap_252_above" (anchored-VWAP state, provenance transcripts/vwap.md).
The feature constants below are the fixed definitions the source studies
measured, not searchable knobs. Fail-open: any unrecognized value (including
"none") applies no filter, so the state series are never even computed
unless one of the two named filters is active.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from sts.models import SignalEvent

DEFAULTS = {
    "atr_window": 14,
    "squeeze_window": 60,
    "squeeze_percentile": 0.20,
    "expansion_ratio": 1.5,
    "close_pos_min": 0.6,
    "trend_filter": "none",
}

# Trend-state filter definitions (§5-C1 grants; constants are the studied
# definitions, NOT searchable knobs):
#   bos       <- transcripts/identifying_the_trend.md (structure state)
#   avwap_252 <- transcripts/vwap.md (anchored-daily adaptation)
_BOS_WINDOW = 60      # closing-extreme window for structure breaks
_AVWAP_WINDOW = 252   # anchor: min low over the window ending at t-1
_AVWAP_BAND = 0.01    # +/-1% "at the level" zone


def _bos_state(df: pd.DataFrame) -> pd.Series:
    """+1 (bullish) after a close above the prior _BOS_WINDOW-bar max close,
    -1 (bearish) after a close below the prior min, carried forward until
    the opposite break. NaN until the first break. Verbatim port of
    .scratch/vol_squeeze_trendstate_study.py's `bos_state`."""
    close = df["close"]
    prior_max = close.shift(1).rolling(_BOS_WINDOW).max()
    prior_min = close.shift(1).rolling(_BOS_WINDOW).min()
    s = pd.Series(np.nan, index=df.index)
    s[close > prior_max] = 1.0
    s[close < prior_min] = -1.0
    s = s.ffill()
    return s.map({1.0: "bullish", -1.0: "bearish"})


def _avwap_state(df: pd.DataFrame) -> pd.Series:
    """Anchored-VWAP state (above/at/below). Anchor = iloc of the min low
    over the _AVWAP_WINDOW bars ending at t-1 (shift-safe). AVWAP from
    anchor..t inclusive via prefix sums of typical-price*volume. Verbatim
    port of .scratch/vol_squeeze_trendstate_study.py's `avwap_state(df,
    window)` with window=_AVWAP_WINDOW and AVWAP_BAND=_AVWAP_BAND."""
    window = _AVWAP_WINDOW
    n = len(df)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    anchor_iloc = np.full(n, -1, dtype=np.int64)
    if n > window:
        windows = sliding_window_view(low, window)  # windows[t-window] == low[t-window : t]
        with np.errstate(invalid="ignore"):
            all_nan = np.isnan(windows).any(axis=1)
            argmins = np.nanargmin(np.where(np.isnan(windows), np.inf, windows), axis=1)
        for t in range(window, n):
            w = t - window
            anchor_iloc[t] = -1 if all_nan[w] else w + int(argmins[w])

    tp = (high + low + close) / 3.0
    pv = np.cumsum(tp * volume)
    v = np.cumsum(volume)

    avwap = np.full(n, np.nan)
    for t in range(window, n):
        a = anchor_iloc[t]
        if a < 0:
            continue
        if a == 0:
            num, den = pv[t], v[t]
        else:
            num, den = pv[t] - pv[a - 1], v[t] - v[a - 1]
        if den > 0:
            avwap[t] = num / den

    out = pd.Series(np.nan, index=df.index, dtype=object)
    finite = np.isfinite(avwap)
    above = finite & (close > avwap * (1 + _AVWAP_BAND))
    below = finite & (close < avwap * (1 - _AVWAP_BAND))
    at = finite & ~above & ~below
    out.iloc[above] = "above"
    out.iloc[below] = "below"
    out.iloc[at] = "at"
    return out


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}
    atr_window = p["atr_window"]
    squeeze_window = p["squeeze_window"]

    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.rolling(atr_window).mean()
    atr_prev = atr.shift(1)  # ATR as of yesterday's close — today's bar is untouched.

    atr_percentile = atr_prev.rolling(squeeze_window).apply(
        lambda x: (x <= x[-1]).mean(), raw=True
    )
    is_squeezed = atr_percentile <= p["squeeze_percentile"]

    true_range_ratio = true_range / atr_prev
    expands = true_range_ratio >= p["expansion_ratio"]

    close_pos = (close - low) / (high - low)
    up_close = close > prev_close
    strong_close = close_pos >= p["close_pos_min"]

    triggered = is_squeezed & expands & up_close & strong_close
    triggered = triggered.fillna(False)

    trend_filter = p.get("trend_filter", "none")
    if trend_filter == "avwap_252_above":
        triggered &= (_avwap_state(df) == "above")
    elif trend_filter == "bos_bullish":
        triggered &= (_bos_state(df) == "bullish")
    # any other value (incl. "none") applies no filter — fail-open, house doctrine

    prior_low = low.shift(1).rolling(squeeze_window).min()
    prior_high = high.shift(1).rolling(squeeze_window).max()

    events: list[SignalEvent] = []
    for ts in df.index[triggered]:
        events.append(
            SignalEvent(
                symbol=symbol,
                date=ts.date(),
                config_name=config_name,
                params=dict(p),
                trigger_values={
                    "swing_low": float(prior_low.loc[ts]),
                    "swing_high": float(prior_high.loc[ts]),
                    "atr": float(atr_prev.loc[ts]),
                    "atr_percentile": float(atr_percentile.loc[ts]),
                    "true_range_ratio": float(true_range_ratio.loc[ts]),
                    "close_pos": float(close_pos.loc[ts]),
                    "close": float(close.loc[ts]),
                },
            )
        )
    return events
