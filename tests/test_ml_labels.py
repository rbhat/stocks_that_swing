import datetime as dt

import pandas as pd
import pytest

from sts.ml.contracts import ContractViolation
from sts.ml.labels import (
    Bar,
    calculate_targets,
    fixed_geometry,
    simulate_fixed_policy,
)

SIGNAL = dt.date(2023, 11, 30)


def forward_bars(**first_changes):
    sessions = [
        day.date() for day in pd.bdate_range("2023-12-01", periods=16)
    ]
    first = {
        "session": sessions[0],
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
    }
    first.update(first_changes)
    bars = [Bar(**first)]
    bars.extend(
        Bar(session=day, open=100.0, high=101.0, low=99.0, close=100.0)
        for day in sessions[1:]
    )
    return bars


def test_fixed_geometry_is_exact_and_strict_at_charter_boundary():
    geometry = fixed_geometry(entry_fill=100.0, atr14=2.0)
    assert geometry.stop_initial == 96.0
    assert geometry.target_initial == 108.0
    assert geometry.planned_r == 2.0
    assert geometry.initial_risk_pct == 0.04

    with pytest.raises(ContractViolation, match="strictly below 12%"):
        fixed_geometry(entry_fill=100.0, atr14=6.0)


def test_target_exit_costs_and_all_three_targets():
    outcome = simulate_fixed_policy(
        signal_session=SIGNAL,
        atr14=2.0,
        forward_bars=forward_bars(high=109.0, close=108.0),
    )

    assert outcome.quantity == 150
    assert outcome.exit_reason == "target"
    assert outcome.exit_price == 108.0
    assert outcome.hold_sessions == 1
    assert outcome.friction_base == pytest.approx(17.6)
    assert outcome.friction_2x == pytest.approx(35.2)
    assert outcome.net_r_base == pytest.approx((1200 - 17.6) / 600)
    assert outcome.net_r_2x == pytest.approx((1200 - 35.2) / 600)

    targets = calculate_targets(
        net_r_2x=outcome.net_r_2x,
        track_a_median_net_r_2x=0.5,
        raw_h15_return=0.10,
        spy_h15_return=0.03,
    )
    assert targets.relative_net_r_2x == pytest.approx(outcome.net_r_2x - 0.5)
    assert targets.spy_residual_h15 == pytest.approx(0.07)
    assert targets.useful_opportunity == 1


def test_ambiguous_bar_resolves_stop_before_target():
    outcome = simulate_fixed_policy(
        signal_session=SIGNAL,
        atr14=2.0,
        forward_bars=forward_bars(high=109.0, low=95.0),
    )

    assert outcome.exit_reason == "stop"
    assert outcome.exit_price == 96.0
    assert outcome.net_r_2x < 0


@pytest.mark.parametrize(
    ("net_r_2x", "track_a_median", "raw_h15_return"),
    [
        (0.0, -1.0, 0.1),
        (1.0, 1.0, 0.1),
        (1.0, 0.0, 0.0),
    ],
)
def test_useful_opportunity_requires_all_three_facts_strictly_positive(
    net_r_2x,
    track_a_median,
    raw_h15_return,
):
    targets = calculate_targets(
        net_r_2x=net_r_2x,
        track_a_median_net_r_2x=track_a_median,
        raw_h15_return=raw_h15_return,
        spy_h15_return=0.0,
    )
    assert targets.useful_opportunity == 0


def test_stop_gap_fills_at_open_and_time_stop_is_session_15():
    gap_bars = forward_bars()
    gap_bars[1] = Bar(
        session=gap_bars[1].session,
        open=90.0,
        high=91.0,
        low=89.0,
        close=90.0,
    )
    gap = simulate_fixed_policy(
        signal_session=SIGNAL,
        atr14=2.0,
        forward_bars=gap_bars,
    )
    assert gap.exit_reason == "stop_gap"
    assert gap.exit_price == 90.0

    bars = forward_bars()
    bars[14] = Bar(
        session=bars[14].session,
        open=100.0,
        high=102.0,
        low=99.0,
        close=102.0,
    )
    bars[15] = Bar(
        session=bars[15].session,
        open=103.0,
        high=105.0,
        low=102.0,
        close=105.0,
    )
    timed = simulate_fixed_policy(
        signal_session=SIGNAL,
        atr14=2.0,
        forward_bars=bars,
    )
    assert timed.exit_reason == "time"
    assert timed.hold_sessions == 15
    assert timed.exit_price == 102.0
    assert timed.raw_h15_return == pytest.approx(0.05)


def test_label_path_and_target_missing_facts_fail_closed():
    with pytest.raises(ContractViolation, match="16 forward sessions"):
        simulate_fixed_policy(
            signal_session=SIGNAL,
            atr14=2.0,
            forward_bars=forward_bars()[:15],
        )
    with pytest.raises(ContractViolation, match="track_a_median_net_r_2x"):
        calculate_targets(
            net_r_2x=1.0,
            track_a_median_net_r_2x=None,
            raw_h15_return=0.1,
            spy_h15_return=0.02,
        )
