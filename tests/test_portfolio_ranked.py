"""Tests for the Phase-4b `simulate_portfolio` additions: `entry_rank_key`
and `max_new_entries_per_window` (docs/preregs/2026-07-12_h4b-h1-ranked-
expression.md)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from sts import risk
from sts.portfolio import simulate_portfolio


def _df(rows: dict[str, tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.to_datetime(sorted(rows))
    data = [rows[d] for d in sorted(rows)]
    return pd.DataFrame(data, index=idx, columns=["open", "high", "low", "close"])


def test_default_kwargs_behavior_identical_to_before():
    # Same fixture as test_portfolio.test_slot_contention_max_positions.
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
    result = simulate_portfolio(prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4))
    assert result["summary"]["n_slot_skipped"] == 1
    assert result["summary"]["n_throttle_skipped"] == 0
    # Deterministic (signal_date, symbol) order: S0..S7 fill (alphabetical).
    taken_symbols = {t["symbol"] for t in result["trades"]}
    assert taken_symbols == {f"S{i}" for i in range(8)}


def test_entry_rank_key_prefers_better_ranked_candidates():
    # 9 same-day candidates, 8 slots (MAX_POSITIONS): the worst-ranked
    # candidate (BBB) must be the one bumped, while the two strongest
    # (ZZZ: seed, AAA: lowest rsi2) are always taken.
    symbols = ["ZZZ", "AAA", "BBB"] + [f"F{i}" for i in range(6)]
    prices = {}
    for sym in symbols:
        prices[sym] = _df(
            {
                "2024-01-02": (100.0, 105.0, 95.0, 102.0),
                "2024-01-03": (102.0, 106.0, 96.0, 103.0),
            }
        )
    is_seed = {"ZZZ": True, "AAA": False, "BBB": False}
    rsi2 = {"ZZZ": 50.0, "AAA": 10.0, "BBB": 99.0}
    for i in range(6):
        is_seed[f"F{i}"] = False
        rsi2[f"F{i}"] = 15.0 + i  # better than BBB, worse than AAA
    candidates = [
        {
            "symbol": sym,
            "signal_date": dt.date(2024, 1, 1),
            "entry_date": dt.date(2024, 1, 2),
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
            "is_seed": is_seed[sym],
            "rsi2_at_trigger": rsi2[sym],
        }
        for sym in symbols
    ]

    rank_key = lambda c: (not c["is_seed"], c["rsi2_at_trigger"], c["symbol"])
    result = simulate_portfolio(
        prices,
        candidates,
        dt.date(2024, 1, 2),
        dt.date(2024, 1, 4),
        entry_rank_key=rank_key,
    )
    taken_symbols = {t["symbol"] for t in result["trades"]}
    assert result["summary"]["n_slot_skipped"] == 1
    assert "ZZZ" in taken_symbols
    assert "AAA" in taken_symbols
    assert "BBB" not in taken_symbols


def test_throttle_caps_entries_per_rolling_window_and_admits_after_rollout():
    # 6 symbols, one candidate per trading session (2024-01-02 .. 2024-01-09,
    # 6 bdays). Cap = 2 per rolling 3-session window.
    dates = pd.bdate_range("2024-01-02", periods=8)
    symbols = [f"S{i}" for i in range(6)]
    prices = {}
    for sym in symbols:
        rows = {d.date().isoformat(): (100.0, 105.0, 95.0, 102.0) for d in dates}
        prices[sym] = _df(rows)

    entry_dates = [d.date() for d in dates[:6]]
    candidates = [
        {
            "symbol": sym,
            "signal_date": entry_dates[i],
            "entry_date": entry_dates[i],
            "entry": 100.0,
            "stop": 90.0,
            "target": None,
            "family": "h1",
        }
        for i, sym in enumerate(symbols)
    ]

    result = simulate_portfolio(
        prices,
        candidates,
        entry_dates[0],
        dates[-1].date(),
        max_new_entries_per_window=(2, 3),
    )
    summary = result["summary"]
    taken_symbols = {t["symbol"] for t in result["trades"]}
    # Sessions 0,1: both admitted (S0, S1) -> window count 2.
    # Session 2 (S2): window [0,1,2] already has 2 -> throttled.
    # Session 3 (S3): window [1,2,3]; session 0 rolled off, count=1 (S1) -> admitted.
    # Session 4 (S4): window [2,3,4]; count so far (S3,S4 attempt) = 1 -> admitted.
    # Session 5 (S5): window [3,4,5]; S3,S4 both admitted = 2 -> throttled.
    assert "S0" in taken_symbols
    assert "S1" in taken_symbols
    assert "S2" not in taken_symbols
    assert "S3" in taken_symbols
    assert summary["n_throttle_skipped"] >= 1


def test_throttle_off_by_default_no_field_regression():
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
    result = simulate_portfolio(prices, candidates, dt.date(2024, 1, 2), dt.date(2024, 1, 4))
    assert result["summary"]["n_throttle_skipped"] == 0
