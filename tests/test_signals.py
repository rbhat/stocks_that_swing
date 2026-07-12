import datetime as dt

import numpy as np
import pandas as pd
import pytest

from sts.models import SignalEvent
from sts.signals import DETECTORS, detect_all, resolve_detector
from sts.signals.breakout import detect as detect_breakout
from sts.signals.markov import DEFAULTS as MARKOV_DEFAULTS
from sts.signals.markov import detect as detect_markov
from sts.signals.squeeze import detect as detect_squeeze
from sts.signals.deep_pullback import detect as detect_deep_pullback
from sts.signals.sweep_reclaim import detect as detect_sweep_reclaim


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """Build an OHLCV frame like sts.data.store: lowercase columns, tz-naive
    DatetimeIndex named "date". Calendar precision doesn't matter to the
    detectors (they're index-agnostic), so plain business days are enough.
    """
    idx = pd.bdate_range("2024-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def flat_bar(o=100.0, h=101.0, l=99.0, c=100.0, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# breakout.py — consolidation_breakout_v1
# ---------------------------------------------------------------------------
# 20-bar lookback immediately before the breakout bar: 10 bars @ volume 1000
# (indices 40-49) then 10 quiet bars @ volume 600 (indices 50-59). 40 padding
# bars (0-39) at the front so the default swing_window=60 has a full prior
# window to compute swing_low/swing_high from (all padding/base/quiet bars
# share the same flat h=101/l=99, so the wider window doesn't change the
# 99/101 swing values the lookback-only window used to produce).
# lookback_mean_vol = (10*1000 + 10*600) / 20 = 800
# quiet_mean_vol = 600 <= 0.8 * 800 = 640  -> quiet-then-wake satisfied
# Note: spec suggested quiet volume 700, but 700 fails the 0.8 ratio against
# a base of 1000 (700 > 0.8*850=680); dropped to 600 so the quiet condition
# is genuinely met with margin. This is synthetic-data tuning, not a
# threshold change.

def _breakout_base_rows(n_pad=40, n_base=10, n_quiet=10):
    rows = []
    for _ in range(n_pad):
        rows.append(flat_bar(v=1000))
    for _ in range(n_base):
        rows.append(flat_bar(v=1000))
    for _ in range(n_quiet):
        rows.append(flat_bar(v=600))
    return rows


def test_breakout_positive():
    rows = _breakout_base_rows()
    # breakout bar: close 3% above range high (101), loud volume
    rows.append({"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 2500})
    df = make_frame(rows)

    events = detect_breakout("TEST", df, {}, "consolidation_breakout_v1")

    assert len(events) == 1
    ev = events[0]
    assert ev.symbol == "TEST"
    assert ev.date == df.index[-1].date()
    assert ev.config_name == "consolidation_breakout_v1"
    from sts.signals.breakout import DEFAULTS as BREAKOUT_DEFAULTS
    assert ev.params == BREAKOUT_DEFAULTS
    assert ev.trigger_values["swing_low"] == pytest.approx(99.0)
    assert ev.trigger_values["swing_high"] == pytest.approx(101.0)
    assert ev.trigger_values["volume_ratio"] > 1.5


def test_breakout_suppressed_while_swing_window_cold():
    # Same trigger bar, but only 30 prior bars (< swing_window=60): the fib
    # swings would be NaN, so the event must be suppressed, not emitted with
    # a defaulted target structure.
    rows = _breakout_base_rows(n_pad=10, n_base=10, n_quiet=10)
    rows.append({"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 2500})
    df = make_frame(rows)

    assert detect_breakout("TEST", df, {}, "consolidation_breakout_v1") == []
    # and with a shortened swing_window it fires again — proving the swing
    # warmth was the only blocker
    events = detect_breakout("TEST", df, {"swing_window": 20}, "consolidation_breakout_v1")
    assert len(events) == 1


def test_breakout_negative_not_loud():
    rows = _breakout_base_rows()
    rows.append({"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 1000})
    df = make_frame(rows)
    assert detect_breakout("TEST", df, {}, "consolidation_breakout_v1") == []


def test_breakout_negative_wide_range():
    rows = _breakout_base_rows()
    # widen the range within the lookback window (base section, indices
    # 40-49): one bar with a much higher high, one with a much lower low
    # -> range_pct well above 10%.
    rows[45] = flat_bar(h=115.0, v=1000)
    rows[47] = flat_bar(l=85.0, v=1000)
    # close above the widened range high, loud volume -- isolates range check
    rows.append({"open": 116.0, "high": 122.0, "low": 115.5, "close": 120.0, "volume": 2500})
    df = make_frame(rows)
    assert detect_breakout("TEST", df, {}, "consolidation_breakout_v1") == []


def test_breakout_negative_close_inside_range():
    rows = _breakout_base_rows()
    # close stays inside the [99, 101] range despite loud volume
    rows.append({"open": 100.0, "high": 100.8, "low": 99.2, "close": 100.5, "volume": 2500})
    df = make_frame(rows)
    assert detect_breakout("TEST", df, {}, "consolidation_breakout_v1") == []


# ---------------------------------------------------------------------------
# squeeze.py — vol_squeeze_v1
# ---------------------------------------------------------------------------
# 99 bars with true range shrinking ~linearly from 10.0 down to 1.0 (close
# pinned at 100 the whole time so true range == high-low each day), then one
# final wide up-close bar. ATR (simple rolling mean of TR) is then strictly
# decreasing, so yesterday's ATR is the minimum of its trailing 60-bar
# window -> percentile ~1/60, comfortably inside the lowest 20%.

def _shrinking_tr_rows(n=99, start_amp=5.0, end_amp=0.5):
    rows = []
    for i in range(n):
        amp = start_amp - (start_amp - end_amp) * i / (n - 1)
        rows.append(flat_bar(o=100.0, h=100.0 + amp, l=100.0 - amp, c=100.0, v=1000))
    return rows


def test_squeeze_positive():
    rows = _shrinking_tr_rows()
    rows.append({"open": 107.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1000})
    df = make_frame(rows)

    events = detect_squeeze("TEST", df, {}, "vol_squeeze_v1")

    assert len(events) == 1
    ev = events[0]
    assert ev.date == df.index[-1].date()
    assert ev.trigger_values["atr_percentile"] <= 0.20
    assert ev.trigger_values["true_range_ratio"] >= 1.5
    assert ev.trigger_values["close_pos"] >= 0.6
    assert "swing_low" in ev.trigger_values and "swing_high" in ev.trigger_values


def test_squeeze_negative_weak_close():
    rows = _shrinking_tr_rows()
    # wide bar, expansion holds, but close sits near the bottom of the range
    rows.append({"open": 107.0, "high": 110.0, "low": 95.0, "close": 96.0, "volume": 1000})
    df = make_frame(rows)
    assert detect_squeeze("TEST", df, {}, "vol_squeeze_v1") == []


def test_squeeze_negative_no_squeeze():
    # constant true range -> ATR never dips into its own bottom 20%
    rows = [flat_bar(o=100.0, h=102.0, l=98.0, c=100.0, v=1000) for _ in range(99)]
    rows.append({"open": 107.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1000})
    df = make_frame(rows)
    assert detect_squeeze("TEST", df, {}, "vol_squeeze_v1") == []


# ---------------------------------------------------------------------------
# No-lookahead: truncating the frame must not change past events.
# ---------------------------------------------------------------------------

def _events_by_date(events):
    return {e.date: e.trigger_values for e in events}


def test_breakout_no_lookahead():
    rows = _breakout_base_rows()
    rows.append({"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 2500})
    trigger_idx = len(rows) - 1
    # tack on 5 more bars so the trigger bar isn't the very last session
    for _ in range(5):
        rows.append(flat_bar(o=104.0, h=105.0, l=103.0, c=104.0, v=1000))
    df = make_frame(rows)
    trigger_date = df.index[trigger_idx].date()

    full_events = _events_by_date(detect_breakout("TEST", df, {}, "consolidation_breakout_v1"))
    assert trigger_date in full_events

    for cut in range(1, 6):
        truncated = df.iloc[: len(df) - cut]
        assert truncated.index[-1].date() >= trigger_date
        trunc_events = _events_by_date(
            detect_breakout("TEST", truncated, {}, "consolidation_breakout_v1")
        )
        assert trunc_events == {
            d: v for d, v in full_events.items() if d <= truncated.index[-1].date()
        }


def test_squeeze_no_lookahead():
    rows = _shrinking_tr_rows()
    rows.append({"open": 107.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1000})
    trigger_idx = len(rows) - 1
    for _ in range(5):
        rows.append(flat_bar(o=108.0, h=109.0, l=106.0, c=107.0, v=1000))
    df = make_frame(rows)
    trigger_date = df.index[trigger_idx].date()

    full_events = _events_by_date(detect_squeeze("TEST", df, {}, "vol_squeeze_v1"))
    assert trigger_date in full_events

    for cut in range(1, 6):
        truncated = df.iloc[: len(df) - cut]
        assert truncated.index[-1].date() >= trigger_date
        trunc_events = _events_by_date(
            detect_squeeze("TEST", truncated, {}, "vol_squeeze_v1")
        )
        assert trunc_events == {
            d: v for d, v in full_events.items() if d <= truncated.index[-1].date()
        }


# ---------------------------------------------------------------------------
# squeeze.py — trend_filter param (§5-C1 earned axis, prereg
# .scratch/vol_squeeze_trendfilter_grid_prereg.md)
# ---------------------------------------------------------------------------
# Both state checks compare TODAY's own close against a stat built from
# strictly-prior bars (shift(1)) -- so a state can flip on the very same
# bar a squeeze fires. A genuine squeeze breakout (a sharp move away from a
# quiet range) is almost always itself a fresh BOS bullish break, and
# almost always closes "above" a flat AVWAP baseline -- so to build the
# DROPPED cases (bearish BOS / below-AVWAP) below, each frame plants a
# higher reference point earlier in the lookback window so the trigger's
# own close doesn't re-flip things bullish/above. The BOS reference sits
# inside the detector's own <60-bar warm-up zone (prior_max/prior_min are
# NaN there, so a comparison against them is never True) -- visible to the
# trigger's own trailing window without ever counting as a break itself.

TRIGGER_BAR = {"open": 107.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1000}


def _bos_kept_rows():
    # 65-bar uptrend (90 -> 100 close, comfortably more than the 60-bar BOS
    # window) into the standard squeeze compression + trigger: each day's
    # close tops the prior 60-day max, so the ramp is itself a run of BOS
    # breaks -- state is "bullish" well before the squeeze event and stays
    # that way (the flat compression closes neither make a new high nor
    # drop below the ramp's min).
    rows = []
    n_ramp = 65
    for i in range(n_ramp):
        c = 90.0 + i * (100.0 - 90.0) / (n_ramp - 1)
        rows.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000})
    rows += _shrinking_tr_rows()
    rows.append(dict(TRIGGER_BAR))
    return rows


def _bos_dropped_bearish_rows():
    # Standard squeeze compression, but bar 50 plants a close=115 "ceiling"
    # (inside the <60-bar warm-up, so it's never itself flagged as a break)
    # and bar 65 is a close=90 dip below the local 100 baseline -- its own
    # 60-bar window is fully warm by then, so it IS a definable break,
    # flipping the state bearish. The ceiling at 50 stays inside the
    # trigger's own trailing 60-bar window (bars 39-98 of this 99-bar
    # block), so the trigger's close (108) can't re-flip bullish -- bearish
    # survives, ffilled, through to the event.
    rows = _shrinking_tr_rows()
    rows[50] = {"open": 100.0, "high": 116.0, "low": 99.0, "close": 115.0, "volume": 1000}
    rows[65] = {"open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "volume": 1000}
    rows.append(dict(TRIGGER_BAR))
    return rows


def _bos_dropped_nan_rows():
    # Same "ceiling" trick as above at bar 45, alone: it keeps the trigger's
    # close under the recent max (no same-bar bullish self-flip) and there
    # is no other break of either sign anywhere -- so the state is NaN (no
    # break has ever happened) straight through to the event: "flat then
    # fire".
    rows = _shrinking_tr_rows()
    rows[45] = {"open": 100.0, "high": 116.0, "low": 99.0, "close": 115.0, "volume": 1000}
    rows.append(dict(TRIGGER_BAR))
    return rows


def _avwap_kept_rows():
    # Long uptrend (50 -> 100 close over 200 bars -- with the 99-bar
    # compression + trigger, comfortably more than the 252-bar AVWAP
    # window) into the standard squeeze compression + trigger. The AVWAP
    # anchors near the ramp's lowest low (its start) and averages typical
    # price over the whole rise, which lags a rising market, so the event
    # bar's close sits above it.
    rows = []
    n_ramp = 200
    for i in range(n_ramp):
        c = 50.0 + i * (100.0 - 50.0) / (n_ramp - 1)
        rows.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000})
    rows += _shrinking_tr_rows()
    rows.append(dict(TRIGGER_BAR))
    return rows


def _avwap_dropped_rows():
    # A decline from 300 to a 50 low (40 bars) anchors the AVWAP at that
    # low; a 100-bar hump back up to 250 and a second decline back to the
    # 100 compression baseline (40 bars) keep the running mean typical
    # price (constant volume -> AVWAP == mean typical price since the
    # anchor) elevated well above the compression's own ~100 level. The
    # squeeze compression + trigger then fire at the lower baseline, so the
    # event bar's close (108) sits under the hump-inflated AVWAP.
    rows = []
    n1, n_hump, n2 = 40, 100, 40
    for i in range(n1):
        c = 300.0 - i * (300.0 - 50.0) / (n1 - 1)
        rows.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000})
    for i in range(n_hump):
        c = 50.0 + i * (250.0 - 50.0) / (n_hump - 1)
        rows.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000})
    for i in range(n2):
        c = 250.0 - i * (250.0 - 100.0) / (n2 - 1)
        rows.append({"open": c, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000})
    rows += _shrinking_tr_rows()
    rows.append(dict(TRIGGER_BAR))
    return rows


def test_squeeze_trend_filter_none_is_byte_identical():
    """Default ("none"), an explicit "none", and an unrecognized value must
    all apply no filter -- pins default-inert AND fail-open together."""
    rows = _shrinking_tr_rows()
    rows.append(dict(TRIGGER_BAR))
    df = make_frame(rows)

    base = _events_by_date(detect_squeeze("TEST", df, {}, "vol_squeeze_v1"))
    explicit_none = _events_by_date(
        detect_squeeze("TEST", df, {"trend_filter": "none"}, "vol_squeeze_v1")
    )
    unknown = _events_by_date(
        detect_squeeze("TEST", df, {"trend_filter": "bogus"}, "vol_squeeze_v1")
    )

    assert base  # sanity: the recipe fires
    assert base == explicit_none == unknown


def test_squeeze_trend_filter_bos():
    # (a) KEPT: the ramp's bullish break predates the event and nothing
    # since flips it.
    df_kept = make_frame(_bos_kept_rows())
    unfiltered_kept = detect_squeeze("TEST", df_kept, {}, "vol_squeeze_v1")
    assert len(unfiltered_kept) == 1 and unfiltered_kept[0].date == df_kept.index[-1].date()
    filtered_kept = detect_squeeze("TEST", df_kept, {"trend_filter": "bos_bullish"}, "vol_squeeze_v1")
    assert _events_by_date(filtered_kept) == _events_by_date(unfiltered_kept)

    # (b) DROPPED: the most recent break before the event is bearish.
    df_bearish = make_frame(_bos_dropped_bearish_rows())
    unfiltered_bearish = detect_squeeze("TEST", df_bearish, {}, "vol_squeeze_v1")
    assert len(unfiltered_bearish) == 1 and unfiltered_bearish[0].date == df_bearish.index[-1].date()
    filtered_bearish = detect_squeeze(
        "TEST", df_bearish, {"trend_filter": "bos_bullish"}, "vol_squeeze_v1"
    )
    assert filtered_bearish == []

    # (c) DROPPED: no break has ever happened (NaN state) -- flat then fire.
    df_nan = make_frame(_bos_dropped_nan_rows())
    unfiltered_nan = detect_squeeze("TEST", df_nan, {}, "vol_squeeze_v1")
    assert len(unfiltered_nan) == 1 and unfiltered_nan[0].date == df_nan.index[-1].date()
    filtered_nan = detect_squeeze("TEST", df_nan, {"trend_filter": "bos_bullish"}, "vol_squeeze_v1")
    assert filtered_nan == []


def test_squeeze_trend_filter_avwap():
    # (a) KEPT: event bar's close above the anchored VWAP.
    df_kept = make_frame(_avwap_kept_rows())
    unfiltered_kept = detect_squeeze("TEST", df_kept, {}, "vol_squeeze_v1")
    assert len(unfiltered_kept) == 1 and unfiltered_kept[0].date == df_kept.index[-1].date()
    filtered_kept = detect_squeeze(
        "TEST", df_kept, {"trend_filter": "avwap_252_above"}, "vol_squeeze_v1"
    )
    assert _events_by_date(filtered_kept) == _events_by_date(unfiltered_kept)

    # (b) DROPPED: event bar's close below the anchored VWAP.
    df_dropped = make_frame(_avwap_dropped_rows())
    unfiltered_dropped = detect_squeeze("TEST", df_dropped, {}, "vol_squeeze_v1")
    assert len(unfiltered_dropped) == 1 and unfiltered_dropped[0].date == df_dropped.index[-1].date()
    filtered_dropped = detect_squeeze(
        "TEST", df_dropped, {"trend_filter": "avwap_252_above"}, "vol_squeeze_v1"
    )
    assert filtered_dropped == []


def test_squeeze_trend_filter_no_lookahead():
    for rows_fn, trend_filter in (
        (_bos_kept_rows, "bos_bullish"),
        (_avwap_kept_rows, "avwap_252_above"),
    ):
        rows = rows_fn()
        trigger_idx = len(rows) - 1
        for _ in range(5):
            rows.append(flat_bar(o=108.0, h=109.0, l=106.0, c=107.0, v=1000))
        df = make_frame(rows)
        trigger_date = df.index[trigger_idx].date()

        params = {"trend_filter": trend_filter}
        full_events = _events_by_date(detect_squeeze("TEST", df, params, "vol_squeeze_v1"))
        assert trigger_date in full_events

        for cut in range(1, 6):
            truncated = df.iloc[: len(df) - cut]
            assert truncated.index[-1].date() >= trigger_date
            trunc_events = _events_by_date(
                detect_squeeze("TEST", truncated, params, "vol_squeeze_v1")
            )
            assert trunc_events == {
                d: v for d, v in full_events.items() if d <= truncated.index[-1].date()
            }


# ---------------------------------------------------------------------------
# Shift-guard: today's own bar must never leak into any "prior" stat.
# ---------------------------------------------------------------------------

def test_current_bar_excluded_from_prior_stats():
    """For both detectors, making the final (trigger) bar more extreme --
    high +50%, volume x3 -- must not move any trigger_values field that's
    documented as prior-window (shift(1)) only. If a shift(1) is ever
    dropped, the extreme bar leaks into that stat and this test goes red.

    Verified by hand: temporarily changing breakout.py's
    `high.shift(1).rolling(swing_window)` to `high.rolling(swing_window)`
    made the breakout half of this test fail (swing_high differed between
    variants) before the shift(1) was restored.
    """
    # -- breakout: consolidation_breakout_v1 --------------------------------
    base_rows = _breakout_base_rows()
    trigger_a = {"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 2500}
    trigger_b = {**trigger_a, "high": trigger_a["high"] * 1.5, "volume": trigger_a["volume"] * 3}

    events_a = detect_breakout("TEST", make_frame(base_rows + [trigger_a]), {}, "consolidation_breakout_v1")
    events_b = detect_breakout("TEST", make_frame(base_rows + [trigger_b]), {}, "consolidation_breakout_v1")
    assert len(events_a) == 1 and len(events_b) == 1  # more extreme bar still fires

    tv_a, tv_b = events_a[0].trigger_values, events_b[0].trigger_values
    assert tv_a["swing_low"] == pytest.approx(tv_b["swing_low"])
    assert tv_a["swing_high"] == pytest.approx(tv_b["swing_high"])
    assert tv_a["range_pct"] == pytest.approx(tv_b["range_pct"])

    # -- squeeze: vol_squeeze_v1 ----------------------------------------------
    squeeze_rows = _shrinking_tr_rows()
    sq_a = {"open": 107.0, "high": 110.0, "low": 95.0, "close": 108.0, "volume": 1000}
    high_b = sq_a["high"] * 1.5
    close_pos_a = (sq_a["close"] - sq_a["low"]) / (sq_a["high"] - sq_a["low"])
    sq_b = {
        "open": 107.0,
        "high": high_b,
        "low": 95.0,
        # Preserve close_pos so strong_close/expansion still fire despite
        # the wider high -- isolates "does today leak into prior stats?"
        # from "does a wider bar still satisfy today's own conditions?".
        "close": sq_a["low"] + close_pos_a * (high_b - sq_a["low"]),
        "volume": sq_a["volume"] * 3,
    }

    events_sq_a = detect_squeeze("TEST", make_frame(squeeze_rows + [sq_a]), {}, "vol_squeeze_v1")
    events_sq_b = detect_squeeze("TEST", make_frame(squeeze_rows + [sq_b]), {}, "vol_squeeze_v1")
    assert len(events_sq_a) == 1 and len(events_sq_b) == 1  # more extreme bar still fires

    tv_sq_a, tv_sq_b = events_sq_a[0].trigger_values, events_sq_b[0].trigger_values
    assert tv_sq_a["swing_low"] == pytest.approx(tv_sq_b["swing_low"])
    assert tv_sq_a["swing_high"] == pytest.approx(tv_sq_b["swing_high"])
    assert tv_sq_a["atr"] == pytest.approx(tv_sq_b["atr"])
    assert tv_sq_a["atr_percentile"] == pytest.approx(tv_sq_b["atr_percentile"])


# ---------------------------------------------------------------------------
# detect_all
# ---------------------------------------------------------------------------

def test_detect_all_combines_and_validates_config_names():
    rows = _breakout_base_rows()
    rows.append({"open": 102.0, "high": 105.0, "low": 101.5, "close": 101.0 * 1.03, "volume": 2500})
    df = make_frame(rows)

    configs = {"consolidation_breakout_v1": {}}
    events = detect_all("TEST", df, configs)
    assert len(events) == 1
    assert all(isinstance(e, SignalEvent) for e in events)

    with pytest.raises(KeyError):
        detect_all("TEST", df, {"not_a_real_config": {}})


def test_registry_has_all_detector_families():
    assert set(DETECTORS) == {
        "consolidation_breakout", "vol_squeeze", "markov_state", "sweep_reclaim",
        "deep_pullback",
    }


def test_versioned_config_names_resolve_to_family():
    from sts.signals import resolve_detector
    from sts.signals.breakout import detect as detect_breakout
    from sts.signals.squeeze import detect as detect_squeeze

    assert resolve_detector("consolidation_breakout_v1") is detect_breakout
    assert resolve_detector("consolidation_breakout_v2") is detect_breakout
    assert resolve_detector("vol_squeeze_v7") is detect_squeeze
    with pytest.raises(KeyError):
        resolve_detector("nonexistent_v1")


# ---------------------------------------------------------------------------
# markov.py — markov_state_v1
# ---------------------------------------------------------------------------
# Synthetic helpers: a seeded random-walk-ish series (for negative/robustness
# tests) and a series engineered so "down move on high volume" is reliably
# followed by several strong up days (for the learned-edge test).

def _random_walk_rows(n=500, seed=0, drift=0.0, vol=0.01):
    rng = np.random.default_rng(seed)
    rows = []
    price = 100.0
    for _ in range(n):
        ret = rng.normal(drift, vol)
        o = price
        c = price * (1 + ret)
        h = max(o, c) * (1 + abs(rng.normal(0, vol / 4)))
        l = min(o, c) * (1 - abs(rng.normal(0, vol / 4)))
        v = int(rng.integers(500, 1500))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    return rows


def _down_loud_then_up_rows(n=420, seed=1):
    """Build a series where a big down move on high volume ('down/loud')
    is reliably followed by a run of strong up days -- a learnable edge for
    the state that pairs ret_bucket=0 (down) with vol_bucket=1 (loud)."""
    rng = np.random.default_rng(seed)
    rows = []
    price = 100.0
    i = 0
    while len(rows) < n:
        if i % 15 == 0:
            # Down/loud trigger bar: sharp drop on heavy volume.
            c = price * 0.90
            rows.append({"open": price, "high": price * 1.005, "low": c * 0.995, "close": c, "volume": 5000})
            price = c
            # Followed by several strong, quiet up days.
            for _ in range(4):
                c2 = price * 1.03
                rows.append({"open": price, "high": c2 * 1.005, "low": price * 0.998, "close": c2, "volume": 700})
                price = c2
        else:
            ret = rng.normal(0.0, 0.004)
            c2 = price * (1 + ret)
            rows.append({
                "open": price,
                "high": max(price, c2) * 1.002,
                "low": min(price, c2) * 0.998,
                "close": c2,
                "volume": int(rng.integers(600, 900)),
            })
            price = c2
        i += 1
    return rows[:n]


def test_markov_deterministic():
    rows = _down_loud_then_up_rows()
    df = make_frame(rows)
    events_a = detect_markov("TEST", df, {}, "markov_state_v1")
    events_b = detect_markov("TEST", df, {}, "markov_state_v1")
    assert events_a == events_b


def test_markov_no_lookahead():
    rows = _down_loud_then_up_rows()
    df = make_frame(rows)
    full_events = _events_by_date(detect_markov("TEST", df, {}, "markov_state_v1"))
    assert full_events  # sanity: the engineered series should fire something

    mutated_rows = list(rows)
    last = mutated_rows[-1]
    mutated_rows[-1] = {**last, "close": last["close"] * 3.0, "volume": last["volume"] * 50}
    mutated_df = make_frame(mutated_rows)
    mutated_events = _events_by_date(detect_markov("TEST", mutated_df, {}, "markov_state_v1"))

    last_date = df.index[-1].date()
    prior_full = {d: v for d, v in full_events.items() if d < last_date}
    prior_mutated = {d: v for d, v in mutated_events.items() if d < last_date}
    assert prior_full == prior_mutated


def test_markov_replay_equals_full():
    rows = _down_loud_then_up_rows()
    df = make_frame(rows)
    full_events = _events_by_date(detect_markov("TEST", df, {}, "markov_state_v1"))
    assert full_events

    # Pick a cut past warmup: min_train + swing_window bars, plus a margin.
    cut = MARKOV_DEFAULTS["min_train"] + MARKOV_DEFAULTS["swing_window"] + 20
    assert cut < len(df)
    truncated = df.iloc[:cut]
    truncated_events = _events_by_date(detect_markov("TEST", truncated, {}, "markov_state_v1"))
    cutoff_date = truncated.index[-1].date()
    assert truncated_events == {d: v for d, v in full_events.items() if d <= cutoff_date}


def test_markov_suppressed_until_min_train():
    # Well under min_train recorded transitions (state only becomes defined
    # after ~atr_window/vol_window warmup, so usable transitions are fewer
    # than the raw bar count) -- must yield nothing despite the strongly
    # trending down/loud-then-up tail baked into every 15-bar cycle.
    n = 200
    assert n < MARKOV_DEFAULTS["min_train"]
    rows = _down_loud_then_up_rows(n=n)
    df = make_frame(rows)
    events = detect_markov("TEST", df, {}, "markov_state_v1")
    assert events == []


def test_markov_fires_on_learned_edge():
    rows = _down_loud_then_up_rows(n=450)
    df = make_frame(rows)
    permissive = {"min_exp_ret": 0.0005, "min_lift": 0.0001}
    events = detect_markov("TEST", df, permissive, "markov_state_v1")
    assert len(events) > 0
    for ev in events:
        tv = ev.trigger_values
        assert tv["ret_bucket"] in (0.0, 1.0, 2.0)
        assert tv["vol_bucket"] in (0.0, 1.0)
        assert np.isfinite(tv["swing_low"])
        assert np.isfinite(tv["swing_high"])
        assert np.isfinite(tv["exp_ret_h"])
        assert np.isfinite(tv["lift"])
    # The engineered edge is the down/loud state -- confirm it's represented.
    assert any(tv["ret_bucket"] == 0.0 and tv["vol_bucket"] == 1.0 for tv in (e.trigger_values for e in events))


def test_markov_negative_no_edge():
    rows = _random_walk_rows(n=500, seed=42, drift=0.0, vol=0.01)
    df = make_frame(rows)
    events = detect_markov("TEST", df, {}, "markov_state_v1")
    for ev in events:
        tv = ev.trigger_values
        assert tv["exp_ret_h"] >= MARKOV_DEFAULTS["min_exp_ret"]
        assert tv["lift"] >= MARKOV_DEFAULTS["min_lift"]

    strict = {"min_exp_ret": 0.5, "min_lift": 0.5}
    assert detect_markov("TEST", df, strict, "markov_state_v1") == []


def test_markov_zero_volume_robustness():
    rows = _random_walk_rows(n=350, seed=7)
    for i in (5, 40, 41, 42, 200):
        rows[i] = {**rows[i], "volume": 0}
    df = make_frame(rows)
    events_a = detect_markov("TEST", df, {}, "markov_state_v1")
    events_b = detect_markov("TEST", df, {}, "markov_state_v1")
    assert events_a == events_b  # no exception, deterministic


# ---------------------------------------------------------------------------
# sweep_reclaim.py — sweep_reclaim_v1
# ---------------------------------------------------------------------------
# Synthetic structure: 60+ warm bars with one peak (high 110) and one trough
# (low 90) so swing_high=110, swing_low=90, and the 0.618 retracement level
# is 110 - 0.618*20 = 97.64. Flat bars (h=101/l=99/c=100) never pierce it.

def _sweep_base_rows(n=63, peak_at=30, trough_at=32):
    rows = [flat_bar() for _ in range(n)]
    rows[peak_at] = flat_bar(h=110.0)
    rows[trough_at] = flat_bar(l=90.0)
    return rows


LEVEL = 110.0 - 0.618 * (110.0 - 90.0)  # 97.64


def test_sweep_reclaim_positive_multibar():
    rows = _sweep_base_rows()
    # sweep day: pierces the level and closes below it -> must NOT fire
    rows.append({"open": 100.0, "high": 100.5, "low": 96.0, "close": 97.0, "volume": 1000})
    # reclaim day: first close back above the level -> fires
    rows.append({"open": 97.5, "high": 99.5, "low": 98.0 - 0.5, "close": 99.0, "volume": 1000})
    df = make_frame(rows)

    events = detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1")
    assert len(events) == 1
    ev = events[0]
    assert ev.date == df.index[-1].date()
    tv = ev.trigger_values
    assert tv["swing_low"] == 90.0
    assert tv["swing_high"] == 110.0
    assert abs(tv["level"] - LEVEL) < 1e-9
    assert tv["sweep_low"] == 96.0  # the sweep day's low, seen through the pierce window
    assert tv["close"] == 99.0


def test_sweep_reclaim_positive_same_bar_hammer():
    rows = _sweep_base_rows()
    # hammer: pierces intraday and closes back above on the same bar
    rows.append({"open": 100.0, "high": 100.5, "low": 96.0, "close": 99.0, "volume": 1000})
    df = make_frame(rows)

    events = detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1")
    assert len(events) == 1
    assert events[0].date == df.index[-1].date()
    assert events[0].trigger_values["sweep_low"] == 96.0


def test_sweep_reclaim_negative_no_reclaim():
    rows = _sweep_base_rows()
    # pierces and STAYS below the level: no reclaim, no event
    rows.append({"open": 100.0, "high": 100.5, "low": 96.0, "close": 97.0, "volume": 1000})
    rows.append({"open": 97.0, "high": 97.5, "low": 96.5, "close": 97.2, "volume": 1000})
    df = make_frame(rows)
    assert detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1") == []


def test_sweep_reclaim_negative_no_pierce():
    rows = _sweep_base_rows()
    # normal up day far above the level: nothing was swept
    rows.append({"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.0, "volume": 1000})
    df = make_frame(rows)
    assert detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1") == []


def test_sweep_reclaim_suppressed_while_swing_window_cold():
    # same sweep+reclaim shape but only 40 bars of history: swing window
    # (60) never warms, so nothing may fire
    rows = _sweep_base_rows(n=38, peak_at=10, trough_at=12)
    rows.append({"open": 100.0, "high": 100.5, "low": 96.0, "close": 97.0, "volume": 1000})
    rows.append({"open": 97.5, "high": 99.5, "low": 97.5, "close": 99.0, "volume": 1000})
    df = make_frame(rows)
    assert detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1") == []


def test_sweep_reclaim_suppressed_on_flat_swing():
    # degenerate structure: every bar identical high==low so swing_high ==
    # swing_low once warm -> no retracement level, must stay silent
    rows = [{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000}
            for _ in range(80)]
    df = make_frame(rows)
    assert detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1") == []


def test_sweep_reclaim_no_lookahead():
    rows = _sweep_base_rows()
    rows.append({"open": 100.0, "high": 100.5, "low": 96.0, "close": 97.0, "volume": 1000})
    rows.append({"open": 97.5, "high": 99.5, "low": 97.5, "close": 99.0, "volume": 1000})
    rows.extend(flat_bar() for _ in range(5))
    df = make_frame(rows)
    full_events = _events_by_date(detect_sweep_reclaim("TEST", df, {}, "sweep_reclaim_v1"))

    # Spiking a FUTURE bar must not change any earlier event.
    mutated = df.copy()
    mutated.iloc[-1, mutated.columns.get_loc("low")] = 1.0
    mutated.iloc[-1, mutated.columns.get_loc("close")] = 200.0
    mutated.iloc[-1, mutated.columns.get_loc("high")] = 200.0
    mutated_events = _events_by_date(detect_sweep_reclaim("TEST", mutated, {}, "sweep_reclaim_v1"))

    cutoff = df.index[-1].date()
    assert {d: v for d, v in full_events.items() if d < cutoff} == \
           {d: v for d, v in mutated_events.items() if d < cutoff}

    # Truncated replay (session-by-session) equals the full-history run.
    truncated = df.iloc[:-5]
    truncated_events = _events_by_date(
        detect_sweep_reclaim("TEST", truncated, {}, "sweep_reclaim_v1")
    )
    assert truncated_events == full_events


# ---------------------------------------------------------------------------
# deep_pullback.py — deep_pullback_v1
# ---------------------------------------------------------------------------
# Same 60+ warm-bar swing structure as sweep_reclaim (peak 110, trough 90),
# so swing_high=110, swing_low=90, and the 0.618+ ("deep") retracement level
# is 110 - 0.618*20 = 97.64. The tail shapes a dry-up (volume well under the
# 20-bar prior median of 1000) then a volume-surge up day whose low still
# reaches the deep zone and whose close stays above swing_low (held).

def _deep_pullback_base_rows(n=63, peak_at=30, trough_at=32):
    rows = [flat_bar() for _ in range(n)]
    rows[peak_at] = flat_bar(h=110.0)
    rows[trough_at] = flat_bar(l=90.0)
    return rows


DEEP_LEVEL = 110.0 - 0.618 * (110.0 - 90.0)  # 97.64


def _deep_pullback_positive_tail():
    # 5 dry-volume bars (500/480/460/450/440, each well under 0.8*1000) whose
    # lows drift down to 94 (<=97.64, satisfying "deep"), then a volume-surge
    # (2000 >= 1.5*1000) up day that closes above swing_low=90.
    return [
        {"open": 100.0, "high": 101.0, "low": 96.0, "close": 98.0, "volume": 500},
        {"open": 98.0, "high": 99.0, "low": 95.0, "close": 97.0, "volume": 480},
        {"open": 97.0, "high": 98.0, "low": 94.0, "close": 96.5, "volume": 460},
        {"open": 96.5, "high": 97.5, "low": 95.0, "close": 96.0, "volume": 450},
        {"open": 96.0, "high": 97.0, "low": 95.5, "close": 95.8, "volume": 440},
        {"open": 95.8, "high": 99.0, "low": 95.0, "close": 98.0, "volume": 2000},
    ]


def test_deep_pullback_positive():
    rows = _deep_pullback_base_rows() + _deep_pullback_positive_tail()
    df = make_frame(rows)

    events = detect_deep_pullback("TEST", df, {}, "deep_pullback_v1")
    assert len(events) == 1
    ev = events[0]
    assert ev.date == df.index[-1].date()
    tv = ev.trigger_values
    assert tv["swing_low"] == 90.0
    assert tv["swing_high"] == 110.0
    assert abs(tv["level"] - DEEP_LEVEL) < 1e-9
    assert tv["pullback_low"] == 94.0  # deepest low of the last 5 bars incl. today
    assert tv["close"] == 98.0
    assert abs(tv["vol_ratio"] - 2.0) < 1e-9


def test_deep_pullback_negative_no_surge():
    rows = _deep_pullback_base_rows() + _deep_pullback_positive_tail()
    rows[-1] = {**rows[-1], "volume": 1000}  # no surge (needs >= 1500)
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_negative_no_dryup():
    rows = _deep_pullback_base_rows()
    tail = _deep_pullback_positive_tail()
    rows += [{**r, "volume": 1000} for r in tail[:-1]] + [tail[-1]]  # no dry-up
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_negative_shallow_pullback():
    # dry-up + surge shape intact, but lows never reach the 97.64 deep zone
    rows = _deep_pullback_base_rows() + [
        {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.0, "volume": 500},
        {"open": 100.0, "high": 101.0, "low": 99.3, "close": 99.8, "volume": 480},
        {"open": 99.8, "high": 100.5, "low": 99.2, "close": 99.6, "volume": 460},
        {"open": 99.6, "high": 100.3, "low": 99.4, "close": 99.5, "volume": 450},
        {"open": 99.5, "high": 100.2, "low": 99.6, "close": 99.4, "volume": 440},
        {"open": 99.4, "high": 100.0, "low": 99.0, "close": 99.7, "volume": 2000},
    ]
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_negative_breakdown():
    # dry-up + surge + deep intact, but the surge-day close (89) is below
    # swing_low (90) -- a breakdown, not a held pullback -- so "held" fails.
    rows = _deep_pullback_base_rows() + [
        {"open": 100.0, "high": 101.0, "low": 96.0, "close": 97.0, "volume": 500},
        {"open": 97.0, "high": 98.0, "low": 95.0, "close": 95.5, "volume": 480},
        {"open": 95.5, "high": 96.0, "low": 94.0, "close": 93.0, "volume": 460},
        {"open": 93.0, "high": 93.5, "low": 92.0, "close": 91.0, "volume": 450},
        {"open": 91.0, "high": 91.5, "low": 90.5, "close": 88.0, "volume": 440},
        {"open": 88.0, "high": 90.0, "low": 87.0, "close": 89.0, "volume": 2000},
    ]
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_suppressed_while_swing_window_cold():
    # same positive shape but only ~40 bars of history: swing window (60)
    # never warms, so nothing may fire
    rows = _deep_pullback_base_rows(n=38, peak_at=10, trough_at=12)
    rows += _deep_pullback_positive_tail()
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_suppressed_on_flat_swing():
    # degenerate structure: every bar identical high==low so swing_high ==
    # swing_low once warm -> no retracement level, must stay silent even
    # though the tail volumes are shaped like a valid dry-up-then-surge
    rows = [{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000}
            for _ in range(74)]
    for v in (500, 480, 460, 450, 440, 2000):
        rows.append({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": v})
    df = make_frame(rows)
    assert detect_deep_pullback("TEST", df, {}, "deep_pullback_v1") == []


def test_deep_pullback_no_lookahead():
    rows = _deep_pullback_base_rows() + _deep_pullback_positive_tail()
    rows.extend(flat_bar() for _ in range(5))
    df = make_frame(rows)
    full_events = _events_by_date(detect_deep_pullback("TEST", df, {}, "deep_pullback_v1"))
    assert full_events  # sanity: the shaped tail should fire something

    # Spiking a FUTURE bar must not change any earlier event.
    mutated = df.copy()
    mutated.iloc[-1, mutated.columns.get_loc("low")] = 1.0
    mutated.iloc[-1, mutated.columns.get_loc("close")] = 200.0
    mutated.iloc[-1, mutated.columns.get_loc("high")] = 200.0
    mutated.iloc[-1, mutated.columns.get_loc("volume")] = 500000
    mutated_events = _events_by_date(detect_deep_pullback("TEST", mutated, {}, "deep_pullback_v1"))

    cutoff = df.index[-1].date()
    assert {d: v for d, v in full_events.items() if d < cutoff} == \
           {d: v for d, v in mutated_events.items() if d < cutoff}

    # Truncated replay (session-by-session) equals the full-history run.
    truncated = df.iloc[:-5]
    truncated_events = _events_by_date(
        detect_deep_pullback("TEST", truncated, {}, "deep_pullback_v1")
    )
    assert truncated_events == full_events


# ---------------------------------------------------------------------------
# resolve_detector — Phase 9 `_catalyst` suffix resolution
# ---------------------------------------------------------------------------

def test_resolve_detector_catalyst_suffix_resolves_to_versioned_family():
    assert resolve_detector("consolidation_breakout_v3_catalyst") is detect_breakout
    assert resolve_detector("vol_squeeze_catalyst") is detect_squeeze


def test_resolve_detector_catalyst_suffix_resolves_other_families():
    assert resolve_detector("sweep_reclaim_v1_catalyst") is detect_sweep_reclaim
    assert resolve_detector("deep_pullback_v1_catalyst") is detect_deep_pullback
    assert resolve_detector("markov_state_catalyst") is detect_markov


def test_resolve_detector_unknown_family_with_catalyst_suffix_raises_keyerror():
    with pytest.raises(KeyError):
        resolve_detector("totally_unknown_family_v1_catalyst")


# ---------------------------------------------------------------------------
# resolve_family — display-only family lookup shared with the dashboard
# ---------------------------------------------------------------------------

def test_resolve_family_strips_version_and_catalyst_suffixes():
    from sts.signals import resolve_family

    assert resolve_family("consolidation_breakout_v1") == "consolidation_breakout"
    assert resolve_family("vol_squeeze_v7") == "vol_squeeze"
    assert resolve_family("sweep_reclaim_v1_catalyst") == "sweep_reclaim"
    assert resolve_family("markov_state_catalyst") == "markov_state"


def test_resolve_family_does_not_validate_known_families():
    from sts.signals import resolve_family

    # Unlike resolve_detector, this never raises — callers that just want a
    # display key (e.g. the dashboard) handle an unknown result themselves.
    assert resolve_family("totally_unknown_family_v1_catalyst") == "totally_unknown_family"
