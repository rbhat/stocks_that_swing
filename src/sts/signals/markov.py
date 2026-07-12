"""Markov-state detector ("markov_state_v1").

Idea: discretize each daily bar into one of 6 states — a 3-way return
bucket (down/flat/up, relative to a volatility-scaled band) crossed with a
2-way volume bucket (quiet/loud) — and learn, incrementally and per symbol,
a first-order Markov transition matrix plus the mean next-day return
observed after each state. A LONG signal fires when the model's own
expected cumulative return over `horizon` days clears two thresholds. There
are no other entry conditions: the learned probability edge is the only
gate.

State construction has the same no-lookahead discipline as breakout.py: the
true-range/ATR band, the return sign it's compared against, and the volume
median are all built from `shift(1)` bars, so only today's own close and
volume decide today's bucket (exactly like the breakout trigger uses only
today's close/volume against prior-window levels).

The learning loop itself is sequential and "update-then-score": at bar t
the transition `state[t-1] -> state[t]` and the reward `r(state[t-1])` are
recorded first, and only afterwards is bar t scored using the
now-updated counts. So bar t's signal can depend on the transition that
just landed on it, but never on anything at t+1 or later — running the
detector on `df` or on `df.iloc[:k]` for any `k` produces identical events
for every date `< k` (see test_markov_no_lookahead /
test_markov_replay_equals_full). This also means estimation is a per-symbol
expanding window: early in a symbol's history the transition/reward
estimates are thin, which is exactly what Laplace smoothing (`alpha`) and
the `min_train` warm-up gate are for — without them a handful of lucky
transitions could look like a real edge.

State design and thresholds motivated by the 2026-07-03 in-sample scratch
study (see tested_signals.md §2 and decisions.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sts.models import SignalEvent

DEFAULTS = {
    "atr_window": 14,
    "ret_band": 0.25,
    "vol_window": 20,
    "alpha": 1.0,
    "horizon": 5,
    "min_exp_ret": 0.005,
    "min_lift": 0.002,
    "min_train": 250,
    "swing_window": 60,
}

N_STATES = 6


def detect(symbol: str, df: pd.DataFrame, params: dict, config_name: str) -> list[SignalEvent]:
    p = {**DEFAULTS, **params}
    atr_window = p["atr_window"]
    ret_band = p["ret_band"]
    vol_window = p["vol_window"]
    alpha = p["alpha"]
    horizon = p["horizon"]
    min_exp_ret = p["min_exp_ret"]
    min_lift = p["min_lift"]
    min_train = p["min_train"]
    swing_window = p["swing_window"]

    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    prev_close = close.shift(1)

    # -- state series (vectorized, prior-bar edges only) ---------------------
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_pct = true_range.rolling(atr_window).mean().shift(1) / prev_close
    band = ret_band * atr_pct

    ret = close.pct_change()
    vol_median = volume.shift(1).rolling(vol_window).median()

    valid = ret.notna() & band.notna() & vol_median.notna()

    ret_bucket = np.where(ret < -band, 0.0, np.where(ret > band, 2.0, 1.0))
    vol_bucket = np.where(volume > vol_median, 1.0, 0.0)
    state = np.where(valid.to_numpy(), ret_bucket * 2 + vol_bucket, np.nan)
    ret_bucket = np.where(valid.to_numpy(), ret_bucket, np.nan)
    vol_bucket = np.where(valid.to_numpy(), vol_bucket, np.nan)
    ret_values = ret.to_numpy()

    # Wider prior-window swing points, for fib targets only (see breakout.py).
    swing_low = low.shift(1).rolling(swing_window).min()
    swing_high = high.shift(1).rolling(swing_window).max()
    swings_warm = (swing_low.notna() & swing_high.notna()).to_numpy()

    n = len(df)
    counts = np.zeros((N_STATES, N_STATES), dtype=float)
    reward_sum = np.zeros(N_STATES, dtype=float)
    reward_count = np.zeros(N_STATES, dtype=float)
    global_sum = 0.0
    global_count = 0.0

    events: list[SignalEvent] = []

    for i in range(n):
        # 1. Update from the transition that just landed on bar i.
        if i > 0:
            s_prev, s_cur = state[i - 1], state[i]
            if not (np.isnan(s_prev) or np.isnan(s_cur)):
                s_prev_i, s_cur_i = int(s_prev), int(s_cur)
                counts[s_prev_i, s_cur_i] += 1.0
                reward_sum[s_prev_i] += ret_values[i]
                reward_count[s_prev_i] += 1.0
                global_sum += ret_values[i]
                global_count += 1.0

        # 2. Score bar i using only data <= i.
        total_transitions = counts.sum()
        s_t = state[i]
        warm = (
            total_transitions >= min_train
            and not np.isnan(s_t)
            and swings_warm[i]
        )
        if not warm:
            continue

        row_sums = (counts + alpha).sum(axis=1, keepdims=True)
        transition_p = (counts + alpha) / row_sums
        r = np.where(reward_count > 0, np.divide(
            reward_sum, reward_count, out=np.zeros_like(reward_sum), where=reward_count > 0
        ), 0.0)

        dist = np.zeros(N_STATES, dtype=float)
        dist[int(s_t)] = 1.0
        exp_h = 0.0
        for _ in range(horizon):
            exp_h += float(dist @ r)
            dist = dist @ transition_p

        base = horizon * (global_sum / global_count if global_count > 0 else 0.0)
        lift = exp_h - base

        if exp_h >= min_exp_ret and lift >= min_lift:
            ts = df.index[i]
            events.append(
                SignalEvent(
                    symbol=symbol,
                    date=ts.date(),
                    config_name=config_name,
                    params=dict(p),
                    trigger_values={
                        "swing_low": float(swing_low.iloc[i]),
                        "swing_high": float(swing_high.iloc[i]),
                        "close": float(close.iloc[i]),
                        "ret_bucket": float(ret_bucket[i]),
                        "vol_bucket": float(vol_bucket[i]),
                        "exp_ret_h": float(exp_h),
                        "lift": float(lift),
                    },
                )
            )

    return events
