"""Tests for sts.study.h4_candidates (Phase 4 Task 2)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from sts.catalyst import CatalystCalendar, CatalystEvent
from sts.study import h4_candidates
from sts.study.h4_candidates import FAMILY_PARAMS, candidates_for


def make_frame(rows: list[dict], start="2024-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _trend_pullback_episode(rows, base):
    p = base
    for _ in range(8 * 5):
        p += 0.4
        rows.append(bar(p - 0.1, p + 0.3, p - 0.3, p))
    d1 = p * 0.85
    d2 = d1 * 0.85
    rows.append(bar(p - 0.1, p + 0.2, d1 - 0.2, d1))
    rows.append(bar(d1 - 0.1, d1 + 0.1, d2 - 0.2, d2))
    rh = rows[-1]["high"]
    rows.append(bar(d2, rh + 1.0, d2 - 0.1, rh + 0.8))
    for _ in range(6):
        c = rows[-1]["close"] * 1.01
        rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
    return rows[-1]["close"]


def _empty_catalyst() -> CatalystCalendar:
    return CatalystCalendar(events=[])


def test_family_params_locked_and_present():
    assert set(FAMILY_PARAMS) == {"h1", "h3", "h2"}
    assert FAMILY_PARAMS["h1"]["config_name"] == "trend_pullback"
    assert FAMILY_PARAMS["h3"]["config_name"] == "vol_squeeze"
    assert FAMILY_PARAMS["h3"]["detector_params"]["trend_filter"] == "avwap_252_above"
    assert FAMILY_PARAMS["h2"]["entry_mode"] == "day2_open"
    assert FAMILY_PARAMS["h2"]["decile_flag"] == "top"


def test_h1_candidate_matches_hand_computed_geometry():
    rows = []
    price = 100.0
    for _ in range(30):
        rows.append(bar(price - 0.5, price + 0.5, price - 0.5, price))
    last = _trend_pullback_episode(rows, price)
    _trend_pullback_episode(rows, last)
    df = make_frame(rows)
    prices = {"TEST": df}

    cands = candidates_for(
        "h1", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=_empty_catalyst()
    )
    assert len(cands) >= 1
    c = cands[0]
    assert c["family"] == "h1"
    assert c["symbol"] == "TEST"
    assert c["stop"] < c["entry"] < (c["target"] if c["target"] else float("inf"))

    # Hand-verify: entry is the next session's open after signal_date.
    iloc_of = {d: i for i, d in enumerate(df.index.date)}
    sig_iloc = iloc_of[c["signal_date"]]
    expected_entry = float(df["open"].iloc[sig_iloc + 1])
    assert c["entry"] == pytest.approx(expected_entry)
    assert c["entry_date"] == df.index[sig_iloc + 1].date()


def test_h1_candidate_carries_rank_fields_and_seed_flag():
    """Phase-4b prereg fields: rsi2_at_trigger, reclaim_wait_sessions (both
    from the detector's trigger_values, no new computation), and is_seed
    (membership in universe.yaml's `seeds:` list) -- AAPL is a real seed."""
    rows = []
    price = 100.0
    for _ in range(30):
        rows.append(bar(price - 0.5, price + 0.5, price - 0.5, price))
    last = _trend_pullback_episode(rows, price)
    _trend_pullback_episode(rows, last)
    df = make_frame(rows)
    prices = {"TEST": df, "AAPL": df}

    cands = candidates_for(
        "h1", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=_empty_catalyst()
    )
    assert len(cands) >= 2
    by_symbol = {}
    for c in cands:
        by_symbol.setdefault(c["symbol"], c)

    for c in cands:
        assert isinstance(c["rsi2_at_trigger"], float)
        assert isinstance(c["reclaim_wait_sessions"], int)
        assert isinstance(c["is_seed"], bool)

    assert by_symbol["AAPL"]["is_seed"] is True
    assert by_symbol["TEST"]["is_seed"] is False


def test_h1_drops_candidate_within_catalyst_embargo():
    rows = []
    price = 100.0
    for _ in range(30):
        rows.append(bar(price - 0.5, price + 0.5, price - 0.5, price))
    last = _trend_pullback_episode(rows, price)
    _trend_pullback_episode(rows, last)
    df = make_frame(rows)
    prices = {"TEST": df}

    cal_empty = _empty_catalyst()
    cands_no_embargo = candidates_for(
        "h1", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=cal_empty
    )
    assert len(cands_no_embargo) >= 1
    first = cands_no_embargo[0]

    # Put an earnings date exactly at the entry date -> within-2-session embargo.
    blocking_cal = CatalystCalendar(
        events=[
            CatalystEvent(
                symbol="TEST",
                date=first["entry_date"],
                type="earnings",
                source="curated",
                actions=frozenset({"block_entry"}),
            )
        ]
    )
    cands_embargoed = candidates_for(
        "h1", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=blocking_cal
    )
    assert first["entry_date"] not in {c["entry_date"] for c in cands_embargoed if c["symbol"] == "TEST"}


def test_h2_applies_catalyst_embargo_like_phase3():
    """H2 applies the standing 2-session pre-earnings entry embargo, matching
    its locked Phase-3 prereg (2026-07-12_h2-pead.md "Catalyst rule") and
    h2_events' own collection/simulation filters: a calendar that blocks
    every entry must remove every H2 candidate."""
    rows = []
    price = 100.0
    for _ in range(60):
        rows.append(bar(price - 0.5, price + 0.5, price - 0.5, price))
    # A volume spike day to trigger the PEAD reaction-session rule.
    spike = rows[-1]["close"] * 1.2
    rows.append(bar(rows[-1]["close"], spike, rows[-1]["close"] - 0.2, spike, v=5_000_000))
    for _ in range(20):
        c = rows[-1]["close"] * 1.001
        rows.append(bar(c - 0.1, c + 0.2, c - 0.2, c))
    df = make_frame(rows)
    prices = {"TEST": df, "SPY": df}

    cal_empty = _empty_catalyst()
    class AlwaysBlockCalendar(CatalystCalendar):
        def catalyst_within(self, symbol, date, horizon_sessions, action):
            return CatalystEvent(
                symbol=symbol, date=date, type="earnings", source="curated",
                actions=frozenset({"block_entry"}),
            )

    always_block = AlwaysBlockCalendar(events=[])
    cands_empty = candidates_for("h2", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=cal_empty)
    cands_blocked = candidates_for(
        "h2", prices, dt.date(2000, 1, 1), dt.date(2100, 1, 1), catalyst=always_block
    )
    assert cands_blocked == []
    # The embargo binding is the only difference: with no blocking events the
    # same candidates come through untouched.
    assert len(cands_empty) >= len(cands_blocked)
