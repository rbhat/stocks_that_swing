import datetime as dt
import math

import pandas as pd
import pytest

from sts import risk


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """Build an OHLCV frame like sts.data.store: lowercase columns, tz-naive
    DatetimeIndex named "date" (same convention as tests/test_signals.py)."""
    idx = pd.bdate_range("2024-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def bar(o=100.0, h=101.0, l=99.0, c=100.0, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# atr()
# ---------------------------------------------------------------------------
# Hand-computed: 5 bars, window=3.
#   row0: h=10,l=8,c=9   -> no prev_close -> TR = 10-8 = 2
#   row1: h=11,l=9,c=10  -> prev_close=9  -> TR = max(2, 2, 0) = 2
#   row2: h=12,l=10,c=11 -> prev_close=10 -> TR = max(2, 2, 0) = 2
#   row3: h=13,l=11,c=12 -> prev_close=11 -> TR = max(2, 2, 0) = 2
#   row4: h=9,l=7,c=8    -> prev_close=12 -> TR = max(2, |9-12|=3, |7-12|=5) = 5
# ATR (rolling mean, window=3, min_periods=3):
#   row0,row1: NaN (not warm)
#   row2: mean(2,2,2) = 2.0
#   row3: mean(2,2,2) = 2.0
#   row4: mean(2,2,5) = 3.0

def test_atr_hand_computed():
    rows = [
        bar(h=10, l=8, c=9),
        bar(h=11, l=9, c=10),
        bar(h=12, l=10, c=11),
        bar(h=13, l=11, c=12),
        bar(h=9, l=7, c=8),
    ]
    df = make_frame(rows)
    result = risk.atr(df, window=3)

    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(3.0)


def test_atr_default_window_warmup():
    # Fewer than DEFAULT_ATR_WINDOW bars -> entirely NaN (no partial-window
    # leakage: min_periods=window, not a shorter effective window).
    rows = [bar() for _ in range(10)]
    df = make_frame(rows)
    result = risk.atr(df)
    assert result.isna().all()


# ---------------------------------------------------------------------------
# atr_stop / structure_stop — shared 12% bound
# ---------------------------------------------------------------------------

def test_atr_stop_unclamped_when_within_bound():
    # candidate = 100 - 2*3 = 94 -> 6% below entry, tighter than 12% bound
    assert risk.atr_stop(100.0, 3.0, multiple=2.0) == pytest.approx(94.0)


def test_atr_stop_clamped_when_beyond_bound():
    # candidate = 100 - 2*10 = 80 -> 20% below entry, clamp to 88 (12% bound)
    assert risk.atr_stop(100.0, 10.0, multiple=2.0) == pytest.approx(88.0)


def test_atr_stop_invalid_inputs_raise():
    with pytest.raises(ValueError):
        risk.atr_stop(0.0, 3.0)
    with pytest.raises(ValueError):
        risk.atr_stop(-5.0, 3.0)
    with pytest.raises(ValueError):
        risk.atr_stop(100.0, 0.0)
    with pytest.raises(ValueError):
        risk.atr_stop(100.0, float("nan"))
    with pytest.raises(ValueError):
        risk.atr_stop(100.0, float("inf"))
    with pytest.raises(ValueError):
        risk.atr_stop(100.0, 3.0, multiple=0.0)
    with pytest.raises(ValueError):
        risk.atr_stop(100.0, 3.0, multiple=-1.0)


def test_structure_stop_unclamped_when_within_bound():
    # level=90 -> 10% below entry, tighter than 12% bound -> passes through
    assert risk.structure_stop(100.0, 90.0) == pytest.approx(90.0)


def test_structure_stop_clamped_when_beyond_bound():
    # level=80 -> 20% below entry, clamp to 88
    assert risk.structure_stop(100.0, 80.0) == pytest.approx(88.0)


def test_structure_stop_invalid_inputs_raise():
    with pytest.raises(ValueError):
        risk.structure_stop(0.0, 50.0)
    with pytest.raises(ValueError):
        risk.structure_stop(100.0, 100.0)   # level must be < entry
    with pytest.raises(ValueError):
        risk.structure_stop(100.0, 110.0)   # level above entry
    with pytest.raises(ValueError):
        risk.structure_stop(100.0, 0.0)     # level must be > 0
    with pytest.raises(ValueError):
        risk.structure_stop(100.0, -10.0)
    with pytest.raises(ValueError):
        risk.structure_stop(100.0, float("nan"))


# ---------------------------------------------------------------------------
# atr_target / structure_target — no bound
# ---------------------------------------------------------------------------

def test_atr_target_basic():
    assert risk.atr_target(100.0, 3.0, multiple=2.0) == pytest.approx(106.0)


def test_atr_target_no_bound_even_when_far():
    # multiple*atr can push the target arbitrarily far -- no R:R floor/ceiling
    assert risk.atr_target(100.0, 50.0, multiple=5.0) == pytest.approx(350.0)


def test_atr_target_invalid_inputs_raise():
    with pytest.raises(ValueError):
        risk.atr_target(0.0, 3.0)
    with pytest.raises(ValueError):
        risk.atr_target(100.0, 0.0)
    with pytest.raises(ValueError):
        risk.atr_target(100.0, float("nan"))
    with pytest.raises(ValueError):
        risk.atr_target(100.0, 3.0, multiple=0.0)


def test_structure_target_basic():
    assert risk.structure_target(120.0) == pytest.approx(120.0)


def test_structure_target_invalid_inputs_raise():
    with pytest.raises(ValueError):
        risk.structure_target(0.0)
    with pytest.raises(ValueError):
        risk.structure_target(-5.0)
    with pytest.raises(ValueError):
        risk.structure_target(float("nan"))
    with pytest.raises(ValueError):
        risk.structure_target(float("inf"))


# ---------------------------------------------------------------------------
# r_multiple
# ---------------------------------------------------------------------------

def test_r_multiple():
    # entry=100, stop=90 -> initial risk = 10
    assert risk.r_multiple(100.0, 110.0, 90.0) == pytest.approx(1.0)
    assert risk.r_multiple(100.0, 95.0, 90.0) == pytest.approx(-0.5)
    assert risk.r_multiple(100.0, 90.0, 90.0) == pytest.approx(-1.0)
    assert risk.r_multiple(100.0, 100.0, 90.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# position_size — one test per binding constraint
# ---------------------------------------------------------------------------
# equity = 100_000 throughout.
#   by_risk     = 750 / stop_distance
#   by_notional = 15_000 / entry
#   by_deployed = max(0, 80_000 - deployed) / entry
#   by_cash     = cash / entry

def test_position_size_risk_bound_binds():
    # entry=100, stop=50 -> stop_distance=50 -> by_risk=750/50=15 (smallest)
    shares = risk.position_size(100_000.0, entry=100.0, stop=50.0)
    assert shares == 15


def test_position_size_notional_bound_binds():
    # entry=100, stop=99 -> stop_distance=1 -> by_risk=750 (huge);
    # by_notional=15_000/100=150 (smallest of the four)
    shares = risk.position_size(100_000.0, entry=100.0, stop=99.0)
    assert shares == 150


def test_position_size_deployed_bound_binds():
    # entry=100, stop=99 -> by_risk=750, by_notional=150;
    # deployed=79_900 -> by_deployed=(80_000-79_900)/100=1 (smallest)
    shares = risk.position_size(100_000.0, entry=100.0, stop=99.0, deployed=79_900.0)
    assert shares == 1


def test_position_size_cash_bound_binds():
    # entry=100, stop=99 -> by_risk=750, by_notional=150, by_deployed=800;
    # cash=250 -> by_cash=2.5 (smallest) -> floor -> 2
    shares = risk.position_size(100_000.0, entry=100.0, stop=99.0, cash=250.0)
    assert shares == 2


def test_position_size_zero_when_max_positions_reached():
    shares = risk.position_size(
        100_000.0, entry=100.0, stop=50.0, open_positions=risk.MAX_POSITIONS
    )
    assert shares == 0
    shares_over = risk.position_size(
        100_000.0, entry=100.0, stop=50.0, open_positions=risk.MAX_POSITIONS + 1
    )
    assert shares_over == 0


def test_position_size_raises_when_stop_not_below_entry():
    with pytest.raises(ValueError):
        risk.position_size(100_000.0, entry=100.0, stop=100.0)
    with pytest.raises(ValueError):
        risk.position_size(100_000.0, entry=100.0, stop=105.0)


# ---------------------------------------------------------------------------
# Position.__post_init__
# ---------------------------------------------------------------------------

def _valid_kwargs(**overrides):
    kwargs = dict(
        symbol="TEST", entry=100.0, shares=10, stop=95.0, target=110.0,
        opened=dt.date(2024, 1, 2), config="test_cfg",
    )
    kwargs.update(overrides)
    return kwargs


def test_position_valid_construction():
    pos = risk.Position(**_valid_kwargs())
    assert pos.bars_held == 0


def test_position_rejects_shares_below_one():
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(shares=0))


def test_position_rejects_stop_at_or_above_entry():
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(stop=100.0))
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(stop=105.0))


def test_position_rejects_target_at_or_below_entry():
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(target=100.0))
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(target=95.0))


def test_position_rejects_stop_distance_beyond_12pct():
    # entry=100, stop=87 -> 13% away -> exceeds MAX_STOP_PCT
    with pytest.raises(risk.RuleViolation):
        risk.Position(**_valid_kwargs(stop=87.0))


def test_position_allows_target_none():
    pos = risk.Position(**_valid_kwargs(target=None))
    assert pos.target is None


# ---------------------------------------------------------------------------
# manage_bar — priority ordering
# ---------------------------------------------------------------------------

def _pos(**overrides):
    kwargs = dict(
        symbol="TEST", entry=100.0, shares=10, stop=95.0, target=110.0,
        opened=dt.date(2024, 1, 2), config="test_cfg",
    )
    kwargs.update(overrides)
    return risk.Position(**kwargs)


def test_manage_bar_stop_before_target_same_bar():
    pos = _pos()
    # bar_low pierces the stop AND bar_high clears the target in one bar
    exits = risk.manage_bar(pos, bar_open=98.0, bar_high=112.0, bar_low=90.0, bar_close=100.0)
    assert len(exits) == 1
    reason, price, shares = exits[0]
    assert reason == "stop"  # open (98) is not below stop (95) -> no gap
    assert price == pytest.approx(95.0)
    assert shares == 10
    assert pos.shares == 0
    assert pos.bars_held == 1


def test_manage_bar_stop_vs_stop_gap():
    # no gap: open above stop, low pierces it -> fills at the stop itself
    pos = _pos()
    exits = risk.manage_bar(pos, bar_open=96.0, bar_high=97.0, bar_low=94.0, bar_close=95.0)
    assert exits[0][0] == "stop"
    assert exits[0][1] == pytest.approx(95.0)

    # gap: bar opens below the stop -> fills at the (worse) open
    pos2 = _pos()
    exits2 = risk.manage_bar(pos2, bar_open=93.0, bar_high=93.5, bar_low=90.0, bar_close=91.0)
    assert exits2[0][0] == "stop_gap"
    assert exits2[0][1] == pytest.approx(93.0)


def test_manage_bar_target_hit_exact_bar():
    pos = _pos()
    exits = risk.manage_bar(pos, bar_open=101.0, bar_high=111.0, bar_low=99.0, bar_close=108.0)
    assert len(exits) == 1
    reason, price, shares = exits[0]
    assert reason == "target"
    assert price == pytest.approx(110.0)  # max(target=110, open=101)
    assert shares == 10
    assert pos.shares == 0


def test_manage_bar_no_exit_returns_empty():
    pos = _pos()
    exits = risk.manage_bar(pos, bar_open=100.0, bar_high=101.0, bar_low=99.0, bar_close=100.0)
    assert exits == []
    assert pos.shares == 10
    assert pos.bars_held == 1


def test_manage_bar_time_stop_fires_exactly_at_15():
    pos = _pos()
    quiet_bar = dict(bar_open=100.0, bar_high=101.0, bar_low=99.0, bar_close=100.0)
    for i in range(14):
        exits = risk.manage_bar(pos, **quiet_bar)
        assert exits == [], f"unexpected exit on bar {i + 1}"
    assert pos.bars_held == 14
    assert pos.shares == 10  # not stopped out by the hard time stop yet

    exits = risk.manage_bar(pos, **quiet_bar)
    assert pos.bars_held == 15
    assert len(exits) == 1
    reason, price, shares = exits[0]
    assert reason == "time"
    assert price == pytest.approx(100.0)
    assert shares == 10
    assert pos.shares == 0


def test_manage_bar_stop_and_target_take_priority_over_time_stop_on_session_15():
    # bars_held already at 14 (session 15 is the NEXT call) -- stop fires on
    # that 15th call and must win over the time-stop reason.
    pos = _pos(bars_held=14)
    exits = risk.manage_bar(pos, bar_open=96.0, bar_high=97.0, bar_low=90.0, bar_close=93.0)
    assert pos.bars_held == 15
    assert exits[0][0] == "stop"

    # Same, but target hit instead of stop.
    pos2 = _pos(bars_held=14)
    exits2 = risk.manage_bar(pos2, bar_open=101.0, bar_high=112.0, bar_low=99.0, bar_close=108.0)
    assert pos2.bars_held == 15
    assert exits2[0][0] == "target"
