"""Tests for sts.portfolio.simulate_portfolio (Phase 4 Task 1)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from sts import risk
from sts.portfolio import simulate_portfolio


def _df(rows: dict[str, tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows: {iso_date: (open, high, low, close)}"""
    idx = pd.to_datetime(sorted(rows))
    data = [rows[d] for d in sorted(rows)]
    return pd.DataFrame(data, index=idx, columns=["open", "high", "low", "close"])


def _cost(notional: float, bps: float = 5.0, per_order: float = 1.0) -> float:
    return notional * bps / 10_000 + per_order


def test_single_candidate_stop_out_penny_exact():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),   # entry bar
                "2024-01-03": (95.0, 96.0, 89.0, 90.0),       # stop hit, no gap
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4)
    )
    shares = risk.position_size(risk.START_CAPITAL, 100.0, 90.0)
    assert shares == 75  # by_risk binds: 0.0075*100000/10
    entry_cost = _cost(shares * 100.0)
    exit_cost = _cost(shares * 90.0)
    expected_cash = risk.START_CAPITAL - (shares * 100.0 + entry_cost) + (shares * 90.0 - exit_cost)
    assert result["summary"]["n_trades"] == 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "stop"
    assert trade["shares"] == shares
    assert result["equity"]["2024-01-03"] == pytest.approx(expected_cash, abs=1e-6)
    entry_cost_per_share = entry_cost / shares
    exit_cost_per_share = exit_cost / shares
    expected_r_net = ((90.0 - exit_cost_per_share) - (100.0 + entry_cost_per_share)) / 10.0
    assert trade["r_net"] == pytest.approx(expected_r_net)
    expected_pnl_net = (shares * 90.0 - exit_cost) - (shares * 100.0 + entry_cost)
    assert trade["pnl_net"] == pytest.approx(expected_pnl_net)


def test_slot_contention_max_positions():
    # 9 same-day candidates on distinct symbols; only MAX_POSITIONS=8 fit.
    symbols = [f"S{i}" for i in range(9)]
    prices = {}
    for sym in symbols:
        prices[sym] = _df(
            {
                "2024-01-02": (100.0, 105.0, 95.0, 102.0),
                "2024-01-03": (102.0, 106.0, 96.0, 103.0),
            }
        )
    candidates = [
        {
            "symbol": sym,
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
        for sym in symbols
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4)
    )
    # 8 fit under MAX_POSITIONS=8; the 9th is skipped for slot contention.
    assert result["summary"]["n_slot_skipped"] == 1


def test_duplicate_symbol_skipped():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),
                "2024-01-03": (100.0, 101.0, 99.0, 100.0),
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        },
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        },
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4)
    )
    assert result["summary"]["n_dup_symbol"] == 1


def test_same_day_entry_bar_stop_resolves_as_loss():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 100.5, 89.0, 90.0),  # entry bar itself breaches stop
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 3)
    )
    assert result["summary"]["n_trades"] == 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "stop"
    assert trade["exit_date"] == dt.date(2024, 1, 2)


def test_censoring_at_end():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),
                "2024-01-03": (100.0, 102.0, 99.0, 101.0),
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4)
    )
    assert result["summary"]["n_trades"] == 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "censored"
    assert trade["exit"] == 101.0
    assert trade["exit_date"] == dt.date(2024, 1, 3)


def test_equity_marking_with_missing_bar():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),
                "2024-01-04": (100.0, 102.0, 99.0, 101.0),
            }
        ),
        "SPY": _df(
            {
                "2024-01-02": (10.0, 10.0, 10.0, 10.0),
                "2024-01-03": (10.0, 10.0, 10.0, 10.0),
                "2024-01-04": (10.0, 10.0, 10.0, 10.0),
            }
        ),
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
    ]
    result = simulate_portfolio(
        prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 5)
    )
    # 2024-01-03 has no AAA bar: equity must use last known close (100.0), not fail.
    assert "2024-01-03" in result["equity"]
    shares = risk.position_size(risk.START_CAPITAL, 100.0, 90.0)
    entry_cost = _cost(shares * 100.0)
    cash_after_entry = risk.START_CAPITAL - (shares * 100.0 + entry_cost)
    expected_equity_0103 = cash_after_entry + shares * 100.0
    assert result["equity"]["2024-01-03"] == pytest.approx(expected_equity_0103)


def test_determinism():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),
                "2024-01-03": (95.0, 96.0, 89.0, 90.0),
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
    ]
    r1 = simulate_portfolio(prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4))
    r2 = simulate_portfolio(prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4))
    assert r1 == r2


def test_invalid_candidate_skipped():
    prices = {
        "AAA": _df(
            {
                "2024-01-02": (100.0, 101.0, 99.0, 100.0),
            }
        )
    }
    candidates = [
        {
            "symbol": "AAA",
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 100.0,  # invalid: stop == entry
            "target": None,
            "family": "h1",
        }
    ]
    result = simulate_portfolio(prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 3))
    assert result["summary"]["n_invalid"] == 1
    assert result["summary"]["n_trades"] == 0
