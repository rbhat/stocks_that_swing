import datetime as dt

import numpy as np
import pandas as pd
import pytest

from sts import eventsim, risk
from sts.models import SignalEvent


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """Build an OHLCV frame like sts.data.store: lowercase columns, tz-naive
    DatetimeIndex named "date" (same convention as tests/test_signals.py)."""
    idx = pd.bdate_range("2024-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def flat_bar(o=100.0, h=101.0, l=99.0, c=100.0, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _fixed_date_detector(signal_date: dt.date):
    """A local, unregistered detector that fires a single event on a fixed
    calendar date -- lets a test drive `simulate_events`/`raw_forward_returns`
    via the `detector=` override without touching sts.signals.DETECTORS."""

    def _detect(symbol, df, params, config_name):
        if signal_date not in set(df.index.date):
            return []
        return [
            SignalEvent(
                symbol=symbol,
                date=signal_date,
                config_name=config_name,
                params=dict(params),
                trigger_values={},
            )
        ]

    return _detect


# ---------------------------------------------------------------------------
# 1. Basic sanity: one hand-traced event, ATR-mode stop/target, target hit.
# ---------------------------------------------------------------------------
# 25 flat warmup bars (idx 0-24): true range is constant at 2.0 every bar
# (high=101/low=99/close=100, and the very first bar's TR = high-low = 2
# too, so there's no discontinuity), so ATR(14) settles to exactly 2.0 by
# idx 13 and stays there through idx 24 -- the signal bar.
#   entry (idx 25 open) = 100.0
#   atr_stop:   100 - 2*2.0 = 96.0  (4% below entry, well inside the 12% bound)
#   atr_target: 100 + 2*2.0 = 104.0
# idx 26: open=100, high=105 (>= target 104), low=99 (> stop 96) -> target
# hit, fill = max(104, 100) = 104 -> r = (104-100)/(100-96) = 1.0
# hold = exit_iloc(26) - entry_iloc(25) = 1 session.

def test_simulate_events_basic_target_hit():
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())  # idx 25: entry bar, open=100
    rows.append({"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000})
    df = make_frame(rows)
    signal_date = df.index[24].date()

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )

    assert result["n"] == 1
    assert result["expectancy_r"] == pytest.approx(1.0)
    assert result["expectancy_r_lower90"] is None  # n < 2
    assert result["n_skipped"] == 0
    assert result["n_censored"] == 0
    assert result["median_hold_sessions"] == pytest.approx(1.0)
    assert result["by_year"] == {"2024": {"n": 1, "expectancy_r": pytest.approx(1.0)}}


def test_simulate_events_structure_mode_stop_out():
    # Same warmup shape, but structure stop/target read from trigger_values,
    # and the next bar gaps down through the stop.
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())  # idx 25: entry bar, open=100
    rows.append({"open": 92.0, "high": 93.0, "low": 90.0, "close": 91.0, "volume": 1000})
    df = make_frame(rows)
    signal_date = df.index[24].date()

    def _detector(symbol, d, params, config_name):
        base = _fixed_date_detector(signal_date)(symbol, d, params, config_name)
        for ev in base:
            ev.trigger_values["stop_level"] = 95.0   # 5% below entry (100)
            ev.trigger_values["target_level"] = 130.0
        return base

    params = {"stop_mode": "structure", "target_mode": "structure"}
    result = eventsim.simulate_events({"TEST": df}, "fixed_v1", params, detector=_detector)

    assert result["n"] == 1
    # entry=100, stop=95 (structure level, within 12% bound) -> gap open 92 < stop
    # -> "stop_gap", fill at open (92) -> r = (92-100)/(100-95) = -1.6
    assert result["expectancy_r"] == pytest.approx(-1.6)
    assert result["n_skipped"] == 0


def test_simulate_events_entry_bar_stop_beats_later_target():
    # Regression (codex_review Fix-1): risk must be live AT entry. The entry
    # bar (idx25) itself crosses the stop, then the NEXT bar (idx26) reaches
    # the target. If the entry bar were skipped, this would wrongly report
    # +1R; managed from entry it must resolve to the stop loss (-1R).
    #   entry (idx25 open) = 100, atr_stop = 96, atr_target = 104.
    #   idx25: open=100, low=95 (<= stop 96), high=101 -> stop hit, fill = 96.
    #   idx26 (would-be target): high=105 -> never reached, event already out.
    rows = [flat_bar() for _ in range(25)]
    rows.append({"open": 100.0, "high": 101.0, "low": 95.0, "close": 97.0, "volume": 1000})  # idx25 entry bar crosses stop
    rows.append({"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000})  # idx26 hits target
    df = make_frame(rows)
    signal_date = df.index[24].date()

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )

    assert result["n"] == 1
    # stop fill at 96 -> r = (96-100)/(100-96) = -1.0, NOT +1.0.
    assert result["expectancy_r"] == pytest.approx(-1.0)
    assert result["median_hold_sessions"] == pytest.approx(0.0)  # exited on entry bar
    assert result["n_skipped"] == 0


def test_simulate_events_structure_mode_reads_swing_levels():
    # Adapter (codex_review H3): detectors emit swing_low/swing_high, not
    # stop_level/target_level. Structure mode must read those directly instead
    # of skipping every real structure event.
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())  # idx 25: entry bar, open=100
    rows.append({"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0, "volume": 1000})
    df = make_frame(rows)
    signal_date = df.index[24].date()

    def _detector(symbol, d, params, config_name):
        base = _fixed_date_detector(signal_date)(symbol, d, params, config_name)
        for ev in base:
            ev.trigger_values["swing_low"] = 95.0    # -> structure stop
            ev.trigger_values["swing_high"] = 105.0  # -> structure target
        return base

    params = {"stop_mode": "structure", "target_mode": "structure"}
    result = eventsim.simulate_events({"TEST": df}, "fixed_v1", params, detector=_detector)

    assert result["n"] == 1
    assert result["n_skipped"] == 0
    # target 105 hit at idx26 (high 106) -> fill max(105,100)=105
    # -> r = (105-100)/(100-95) = 1.0
    assert result["expectancy_r"] == pytest.approx(1.0)


def test_simulate_events_rejects_unknown_stop_mode():
    rows = [flat_bar() for _ in range(27)]
    df = make_frame(rows)
    signal_date = df.index[24].date()
    with pytest.raises(ValueError, match="stop_mode"):
        eventsim.simulate_events(
            {"TEST": df}, "fixed_v1", {"stop_mode": "atrr"},
            detector=_fixed_date_detector(signal_date),
        )


def test_simulate_events_structure_mode_skips_missing_level():
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())
    rows.append(flat_bar())
    df = make_frame(rows)
    signal_date = df.index[24].date()

    params = {"stop_mode": "structure", "target_mode": "atr"}
    # trigger_values has no "stop_level" -> event must be skipped, not raise
    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", params, detector=_fixed_date_detector(signal_date)
    )
    assert result["n"] == 0
    assert result["n_skipped"] == 1


def test_simulate_events_skips_when_atr_not_warm():
    # Only 5 bars of warmup: ATR(14) is NaN at the signal bar -> skip.
    rows = [flat_bar() for _ in range(5)]
    rows.append(flat_bar())
    rows.append(flat_bar())
    df = make_frame(rows)
    signal_date = df.index[4].date()

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )
    assert result["n"] == 0
    assert result["n_skipped"] == 1


def test_simulate_events_no_next_bar_skips():
    rows = [flat_bar() for _ in range(25)]
    df = make_frame(rows)
    signal_date = df.index[-1].date()  # signal on the very last bar -> no entry bar

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )
    assert result["n"] == 0
    assert result["n_skipped"] == 1


def test_simulate_events_time_stop_exit_path():
    # 25 warmup bars (idx 0-24) -> ATR(14) settles to 2.0 (see module comment
    # above). Entry at idx25 open=100 -> stop=96, target=104 (2xATR each).
    # Risk is live AT entry, so the entry bar (idx25) is the position's first
    # held session and starts the 15-session clock. With all bars inside
    # (96,104), the hard time stop fires on the 15th managed bar -- idx25+14 =
    # idx39 -- exiting at that bar's close. hold = 39-25 = 14 elapsed sessions.
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())  # idx 25: entry bar, open=100 (managed bar 1)
    rows.extend(flat_bar() for _ in range(15))  # idx 26-40: quiet bars
    df = make_frame(rows)
    signal_date = df.index[24].date()

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )

    assert result["n"] == 1
    # exit at bar_close=100.0 -> r = (100-100)/(100-96) = 0.0
    assert result["expectancy_r"] == pytest.approx(0.0)
    assert result["median_hold_sessions"] == pytest.approx(14.0)
    assert result["n_censored"] == 0
    assert result["n_skipped"] == 0


def test_simulate_events_censored_at_end_of_frame():
    # Same entry/stop/target as above, but only 3 quiet bars exist after
    # entry before the frame runs out -- well short of both the target/stop
    # and the 15-session time stop -> must censor at the last available
    # close, not raise or silently drop the event.
    rows = [flat_bar() for _ in range(25)]
    rows.append(flat_bar())  # idx 25: entry bar, open=100
    rows.extend(flat_bar() for _ in range(3))  # idx 26-28: only 3 more bars
    df = make_frame(rows)
    signal_date = df.index[24].date()

    result = eventsim.simulate_events(
        {"TEST": df}, "fixed_v1", {}, detector=_fixed_date_detector(signal_date)
    )

    assert result["n"] == 1
    assert result["n_censored"] == 1
    # censored at the frame's last close (100.0) -> r = (100-100)/(100-96) = 0.0
    assert result["expectancy_r"] == pytest.approx(0.0)
    assert result["median_hold_sessions"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 2. raw_forward_returns basic sanity (layer a, exit-free).
# ---------------------------------------------------------------------------
# 10 bars, open == close == 100+i for bar i (no gap). Signal fires on idx 2
# (open=102) -> entry = idx 3 open = 103.0. horizons=(1,2,3):
#   h=1 -> close[idx4]=104 -> 104/103 - 1
#   h=2 -> close[idx5]=105 -> 105/103 - 1
#   h=3 -> close[idx6]=106 -> 106/103 - 1

def test_raw_forward_returns_basic_sanity():
    rows = []
    for i in range(10):
        v = 100.0 + i
        rows.append({"open": v, "high": v + 1, "low": v - 1, "close": v, "volume": 1000})
    df = make_frame(rows)
    signal_date = df.index[2].date()

    result = eventsim.raw_forward_returns(
        {"TEST": df}, "fixed_v1", {}, horizons=(1, 2, 3),
        detector=_fixed_date_detector(signal_date),
    )

    assert result["n_events"] == 1
    entry = 103.0
    for h, expected_close in ((1, 104.0), (2, 105.0), (3, 106.0)):
        cell = result["by_horizon"][h]
        assert cell["n"] == 1
        expected_ret = expected_close / entry - 1
        assert cell["mean_return"] == pytest.approx(expected_ret)
        assert cell["median_return"] == pytest.approx(expected_ret)


def test_raw_forward_returns_skips_out_of_bounds_horizon():
    rows = []
    for i in range(6):
        v = 100.0 + i
        rows.append({"open": v, "high": v + 1, "low": v - 1, "close": v, "volume": 1000})
    df = make_frame(rows)
    signal_date = df.index[2].date()  # entry at idx3; only idx4,5 exist after

    result = eventsim.raw_forward_returns(
        {"TEST": df}, "fixed_v1", {}, horizons=(1, 2, 5),
        detector=_fixed_date_detector(signal_date),
    )
    assert result["n_events"] == 1
    assert result["by_horizon"][1]["n"] == 1
    assert result["by_horizon"][2]["n"] == 1
    assert result["by_horizon"][5]["n"] == 0
    assert result["by_horizon"][5]["mean_return"] is None
    assert result["by_horizon"][5]["median_return"] is None


def test_raw_forward_returns_empty_when_no_events():
    rows = [flat_bar() for _ in range(20)]
    df = make_frame(rows)

    def _no_events(symbol, d, params, config_name):
        return []

    result = eventsim.raw_forward_returns(
        {"TEST": df}, "fixed_v1", {}, detector=_no_events
    )
    assert result["n_events"] == 0
    for h, cell in result["by_horizon"].items():
        assert cell["n"] == 0
        assert cell["mean_return"] is None
        assert cell["median_return"] is None


# ---------------------------------------------------------------------------
# 3. The Phase-2 gate test -- negative control.
# ---------------------------------------------------------------------------
# A synthetic 20-symbol x 300-session i.i.d. random-walk universe (fixed
# seed, no drift) with a detector that fires on a random ~5% of eligible
# sessions. Random entries through the real ATR stop/target/time-stop
# structure must show ~zero gross expectancy and, more importantly, no
# statistically confident positive edge -- if they did, the harness itself
# would be manufacturing edge out of noise.

def _build_random_universe(n_symbols=20, n_sessions=300, seed=42, fire_frac=0.05, atr_window=14):
    """Deterministic synthetic universe + matching unregistered detector.
    A single rng instance drives both price generation and the fire draws,
    in a fixed sequential order, so the whole fixture is fully reproducible
    under the fixed seed -- not a per-run statistical gamble."""
    rng = np.random.default_rng(seed)
    prices: dict[str, pd.DataFrame] = {}
    fire_dates: dict[str, set] = {}

    for i in range(n_symbols):
        symbol = f"SYM{i:02d}"
        idx = pd.bdate_range("2015-01-02", periods=n_sessions, name="date")
        price = 100.0
        opens, highs, lows, closes, vols = [], [], [], [], []
        for _ in range(n_sessions):
            o = price
            ret = rng.normal(0.0, 0.02)  # mean 0 -> no drift
            c = o * (1 + ret)
            h = max(o, c) * (1 + abs(rng.normal(0, 0.005)))
            l = min(o, c) * (1 - abs(rng.normal(0, 0.005)))
            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(c)
            vols.append(1000)
            price = c
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=idx,
        )
        prices[symbol] = df

        # Eligible sessions: ATR must be warm, and a next bar must exist for
        # the entry fill -- same eligibility the simulator itself applies.
        eligible = range(atr_window - 1, n_sessions - 1)
        dates = {idx[i_bar].date() for i_bar in eligible if rng.random() < fire_frac}
        fire_dates[symbol] = dates

    def _random_detector(symbol, df, params, config_name):
        return [
            SignalEvent(
                symbol=symbol, date=d, config_name=config_name,
                params=dict(params), trigger_values={}, direction="long",
            )
            for d in sorted(fire_dates.get(symbol, set()))
        ]

    return prices, _random_detector


def test_negative_control_random_entries_show_no_edge():
    prices, detector = _build_random_universe()
    result = eventsim.simulate_events(prices, "random_v1", {}, detector=detector)

    # Adequacy: comfortably clears the n>=200 floor this test requires
    # (observed 258 under the fixed seed/params below).
    assert result["n"] >= 200

    # (a) Gross expectancy is close to zero. Calibration: under this fixed
    # seed the observed value is expectancy_r ~= 0.0086R (one-time
    # deterministic measurement, recorded here -- not a statistical
    # gamble, since the seed never changes). 0.10R is a fixed, defensible
    # "near zero" band (~12x the observed magnitude): comfortably clears
    # normal run-to-run arithmetic drift while still rejecting any real
    # edge, which would show up as several tenths of an R or more.
    assert abs(result["expectancy_r"]) < 0.10

    # (b) The lower 90% confidence bound on mean R is not meaningfully
    # positive. A real edge would clear a confident lower bound even after
    # discounting for noise; random entries must not. This is the honest
    # way to state "~zero gross expectancy" for a noisy per-trade
    # distribution -- friction (not modeled in this event-level module)
    # only ever pushes a ~zero edge negative, never positive, so the
    # meaningful pre-friction bar is the absence of any positive edge.
    assert result["expectancy_r_lower90"] is not None
    assert result["expectancy_r_lower90"] < 0.05


def test_negative_control_is_deterministic():
    prices_a, detector_a = _build_random_universe()
    prices_b, detector_b = _build_random_universe()
    result_a = eventsim.simulate_events(prices_a, "random_v1", {}, detector=detector_a)
    result_b = eventsim.simulate_events(prices_b, "random_v1", {}, detector=detector_b)
    assert result_a == result_b


# ---------------------------------------------------------------------------
# 4. No-lookahead sanity: appending future bars must not change an
#    already-resolved past event's R.
# ---------------------------------------------------------------------------

def test_simulate_events_no_lookahead_on_resolved_event():
    rows = [flat_bar() for _ in range(25)]      # idx 0-24: warmup
    rows.append(flat_bar())                      # idx 25: entry bar
    rows.append({"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000})  # idx 26: target hit
    base_df = make_frame(rows)
    signal_date = base_df.index[24].date()

    truncated = {"TEST": base_df}
    extended_rows = rows + [flat_bar(o=104.0, h=105.0, l=103.0, c=104.0) for _ in range(10)]
    extended = {"TEST": make_frame(extended_rows)}

    detector = _fixed_date_detector(signal_date)
    result_truncated = eventsim.simulate_events(truncated, "fixed_v1", {}, detector=detector)
    result_extended = eventsim.simulate_events(extended, "fixed_v1", {}, detector=detector)

    # The event resolves (target hit) at idx 26, well inside the truncated
    # 27-bar frame -- appending 10 more bars afterward must not change it.
    assert result_truncated == result_extended
    assert result_truncated["n"] == 1
    assert result_truncated["n_censored"] == 0


def test_raw_forward_returns_no_lookahead_within_window():
    rows = []
    for i in range(30):
        v = 100.0 + i
        rows.append({"open": v, "high": v + 1, "low": v - 1, "close": v, "volume": 1000})
    base_df = make_frame(rows)
    signal_date = base_df.index[2].date()

    truncated = {"TEST": base_df}
    extended_rows = rows + [{"open": 999.0, "high": 1000.0, "low": 998.0, "close": 999.0, "volume": 1000}
                             for _ in range(5)]
    extended = {"TEST": make_frame(extended_rows)}

    detector = _fixed_date_detector(signal_date)
    result_truncated = eventsim.raw_forward_returns(
        truncated, "fixed_v1", {}, horizons=(1, 2, 3), detector=detector
    )
    result_extended = eventsim.raw_forward_returns(
        extended, "fixed_v1", {}, horizons=(1, 2, 3), detector=detector
    )
    # Horizons 1-3 all resolve well inside the original 30-bar frame.
    assert result_truncated == result_extended
