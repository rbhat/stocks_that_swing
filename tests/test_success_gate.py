import json
import math

import numpy as np
import pytest

from sts.study.success_gate import (
    STATE_EVALUATED,
    STATE_INADEQUATE,
    STATE_INVALID_GEOMETRY,
    STATE_NOT_RUN,
    build_success_artifact,
    entry_geometry,
    matched_return_bootstrap,
    max_drawdown,
    summarize_events,
    summarize_portfolio,
)


def _event(
    *,
    entry=100.0,
    stop=90.0,
    target=116.0,
    gross=0.0,
    friction=0.0,
    hold=5,
    mae_r=0.5,
):
    return {
        "entry_fill": entry,
        "stop_initial": stop,
        "target_initial": target,
        "gross_profit": gross,
        "friction_base": friction,
        "hold_sessions": hold,
        "mae_r": mae_r,
    }


def test_entry_geometry_hand_calculation_and_strict_boundaries():
    valid = entry_geometry(100.0, 90.0, 116.0)
    assert valid["initial_risk"] == 10.0
    assert valid["planned_r"] == pytest.approx(1.6)
    assert valid["initial_risk_pct"] == pytest.approx(0.10)
    assert valid["valid"] is True

    exactly_1_5r = entry_geometry(100.0, 90.0, 115.0)
    assert exactly_1_5r["planned_r"] == pytest.approx(1.5)
    assert exactly_1_5r["planned_r_pass"] is False
    assert exactly_1_5r["state"] == STATE_INVALID_GEOMETRY

    exactly_25pct = entry_geometry(100.0, 75.0, 140.0)
    assert exactly_25pct["initial_risk_pct"] == pytest.approx(0.25)
    assert exactly_25pct["success_risk_pass"] is False
    assert exactly_25pct["valid"] is False

    exactly_12pct = entry_geometry(100.0, 88.0, 119.2)
    assert exactly_12pct["planned_r"] == pytest.approx(1.6)
    assert exactly_12pct["success_risk_pass"] is True
    assert exactly_12pct["charter_risk_pass"] is False
    assert exactly_12pct["valid"] is False


@pytest.mark.parametrize(
    ("entry", "stop", "target"),
    [
        (0.0, -1.0, 1.0),
        (100.0, 100.0, 120.0),
        (100.0, 101.0, 120.0),
        (100.0, 90.0, 100.0),
        (math.nan, 90.0, 120.0),
    ],
)
def test_entry_geometry_structural_invalid_cases_are_explicit(entry, stop, target):
    result = entry_geometry(entry, stop, target)
    assert result["state"] == STATE_INVALID_GEOMETRY
    assert result["valid"] is False
    assert result["reason"]


def test_event_metrics_hand_calculation():
    events = [
        _event(gross=120.0, friction=20.0, hold=2, mae_r=0.2),
        _event(gross=-40.0, friction=10.0, hold=5, mae_r=0.7),
        _event(gross=30.0, friction=10.0, hold=10, mae_r=0.4),
    ]
    result = summarize_events(
        events,
        raw_h15_returns=[0.10, -0.02, 0.04],
        min_events=3,
    )

    assert result["evaluation_state"] == STATE_EVALUATED
    assert result["passes"] is True
    assert result["metrics"]["net_profit"] == {"base": 70.0, "2x": 30.0}
    assert result["metrics"]["friction"]["base_total"] == 40.0
    assert result["metrics"]["friction"]["2x_total"] == 80.0
    assert result["metrics"]["win_loss"]["wins"] == 2
    assert result["metrics"]["win_loss"]["losses"] == 1
    assert result["metrics"]["profit_factor"]["base"] == pytest.approx(2.4)
    assert result["metrics"]["profit_factor"]["2x"] == pytest.approx(1.5)
    assert result["metrics"]["hold_sessions"]["median"] == 5.0
    assert result["metrics"]["mae_r"]["median"] == 0.4
    assert result["metrics"]["raw_h15_return"]["mean"] == pytest.approx(0.04)


def test_event_states_not_run_inadequate_and_invalid_geometry():
    assert summarize_events(None)["evaluation_state"] == STATE_NOT_RUN
    assert summarize_events([])["evaluation_state"] == STATE_INADEQUATE

    invalid = summarize_events(
        [_event(target=115.0)],
        raw_h15_returns=[0.01],
        min_events=1,
    )
    assert invalid["evaluation_state"] == STATE_INVALID_GEOMETRY
    assert invalid["passes"] is False
    assert invalid["geometry"]["invalid"] == 1


def test_random_entry_negative_control_is_near_zero_gross_and_negative_after_costs():
    rng = np.random.default_rng(20260726)
    draws = rng.normal(0.0, 1.0, size=2_500)
    gross = np.concatenate([draws, -draws])
    events = [_event(gross=value, friction=0.05) for value in gross]

    result = summarize_events(events, raw_h15_returns=gross, min_events=100)

    assert float(np.mean(gross)) == pytest.approx(0.0, abs=1e-12)
    assert result["metrics"]["net_profit"]["base"] < 0
    assert result["metrics"]["net_profit"]["2x"] < result["metrics"]["net_profit"]["base"]
    assert result["metrics"]["profit_factor"]["base"] < 1
    assert result["metrics"]["profit_factor"]["2x"] < result["metrics"]["profit_factor"]["base"]


def test_portfolio_drawdown_deployment_and_geometry_hand_calculation():
    sessions = [
        {"equity": 100.0, "deployed_capital": 10.0},
        {"equity": 120.0, "deployed_capital": 24.0},
        {"equity": 90.0, "deployed_capital": 0.0},
        {"equity": 110.0, "deployed_capital": 55.0},
    ]
    result = summarize_portfolio(
        sessions,
        start_capital=100.0,
        fill_geometries=[
            {"entry_fill": 100.0, "stop_initial": 90.0, "target_initial": 116.0}
        ],
    )

    assert result["evaluation_state"] == STATE_EVALUATED
    assert result["metrics"]["net_return"] == pytest.approx(0.10)
    assert result["metrics"]["max_drawdown"] == pytest.approx(0.25)
    assert result["metrics"]["average_deployed_capital"] == pytest.approx(0.20)
    assert result["passes"] is True


def test_portfolio_states_are_explicit():
    assert summarize_portfolio(None, start_capital=100.0)["evaluation_state"] == STATE_NOT_RUN
    inadequate = summarize_portfolio([], start_capital=100.0, fill_geometries=[])
    assert inadequate["evaluation_state"] == STATE_INADEQUATE
    invalid = summarize_portfolio(
        [{"equity": 101.0, "deployed_capital": 20.0}],
        start_capital=100.0,
        fill_geometries=[
            {"entry_fill": 100.0, "stop_initial": 90.0, "target_initial": 115.0}
        ],
    )
    assert invalid["evaluation_state"] == STATE_INVALID_GEOMETRY
    assert invalid["passes"] is False


def test_matched_bootstrap_hand_calculation_constant_path():
    rows = [{"session_return": 0.01, "closed_trades": 1} for _ in range(8)]
    result = matched_return_bootstrap(
        rows,
        closed_trade_count=3,
        elapsed_session_count=3,
        block_size=2,
        n_bootstrap=100,
        seed=7,
    )

    expected = 1.01**3 - 1
    assert result["evaluation_state"] == STATE_EVALUATED
    assert result["accepted_replicates"] == 100
    assert result["interval_90"]["lower"] == pytest.approx(expected)
    assert result["interval_90"]["upper"] == pytest.approx(expected)


def test_matched_bootstrap_reports_inadequate_when_match_is_impossible():
    rows = [{"session_return": 0.01, "closed_trades": 0} for _ in range(5)]
    result = matched_return_bootstrap(
        rows,
        closed_trade_count=1,
        elapsed_session_count=3,
        block_size=2,
        n_bootstrap=10,
        max_attempt_multiplier=2,
    )

    assert result["evaluation_state"] == STATE_INADEQUATE
    assert result["accepted_replicates"] == 0
    assert result["interval_90"] is None


def test_matched_bootstrap_reports_zero_closed_trades_as_inadequate():
    result = matched_return_bootstrap(
        [{"session_return": 0.01, "closed_trades": 0}],
        closed_trade_count=0,
        elapsed_session_count=1,
        block_size=1,
        n_bootstrap=10,
    )
    assert result["evaluation_state"] == STATE_INADEQUATE
    assert result["accepted_replicates"] == 0


def test_geometry_and_drawdown_properties_over_seeded_random_cases():
    rng = np.random.default_rng(42)
    for _ in range(500):
        entry = float(rng.uniform(5.0, 1_000.0))
        risk_pct = float(rng.uniform(0.001, 0.119999))
        planned_r = float(rng.uniform(np.nextafter(1.5, 2.0), 5.0))
        stop = entry * (1.0 - risk_pct)
        target = entry + (entry - stop) * planned_r
        geometry = entry_geometry(entry, stop, target)
        assert geometry["valid"] is True
        assert geometry["planned_r"] > 1.5
        assert geometry["initial_risk_pct"] < 0.12

        path = np.exp(rng.normal(0.0, 0.03, size=30).cumsum()) * entry
        drawdown = max_drawdown(path.tolist())
        assert 0.0 <= drawdown < 1.0
        assert max_drawdown((path * 17.0).tolist()) == pytest.approx(drawdown)


def test_new_artifact_schema_leaves_unrun_sections_explicit():
    artifact = build_success_artifact()
    json.dumps(artifact, allow_nan=False)
    assert artifact["schema_version"] == "success-v2.phase1"
    assert artifact["event_gate"]["evaluation_state"] == STATE_NOT_RUN
    assert artifact["portfolio_gate"]["evaluation_state"] == STATE_NOT_RUN
    assert artifact["matched_oos_band"]["evaluation_state"] == STATE_NOT_RUN
