from __future__ import annotations

import datetime as dt
import hashlib
import random
from dataclasses import replace
from decimal import Decimal

import pytest

from sts.ml_v2.contracts import (
    REQUIRED_AS_OF_FACTS,
    REQUIRED_SOURCE_KINDS,
    Bar,
    Candidate,
    CashDistribution,
    ContractViolation,
    Delisting,
    PointInTimeManifest,
    SessionFrame,
    SourceRecord,
    Split,
    locked_setup_contract,
)
from sts.ml_v2.controls import rank_all_dates
from sts.ml_v2.identity import tie_breaker
from sts.ml_v2.portfolio import SimulatedCrash, simulate


def _manifest(
    start: dt.date = dt.date(2023, 1, 1),
    end: dt.date = dt.date(2025, 1, 1),
) -> PointInTimeManifest:
    return PointInTimeManifest(
        start,
        end,
        tuple(
            SourceRecord(
                kind,
                hashlib.sha256(kind.encode()).hexdigest(),
                "synthetic-v1",
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
    )


def _candidate(
    manifest: PointInTimeManifest,
    permanent_id: str,
    signal: dt.date,
    entry: dt.date,
    *,
    symbol: str | None = None,
    score: str = "1",
    signal_close: str = "100",
    atr: str = "2",
    mdv: str = "100000000",
    split_ratio: str = "1",
) -> Candidate:
    return Candidate(
        "P-D",
        "F1",
        permanent_id,
        symbol or permanent_id.upper(),
        signal,
        entry,
        Decimal(score),
        Decimal(signal_close),
        Decimal(atr),
        Decimal(mdv),
        manifest.identity,
        {name: signal for name in REQUIRED_AS_OF_FACTS},
        {
            "adjusted_return_20": Decimal(score),
            "adjusted_return_5": Decimal(score),
            "volume_to_median_20": Decimal(score),
        },
        Decimal(split_ratio),
    )


def _bar(
    permanent_id: str,
    *,
    symbol: str | None = None,
    open: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100",
) -> Bar:
    return Bar(
        permanent_id,
        symbol or permanent_id.upper(),
        Decimal(open),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def _run(
    manifest: PointInTimeManifest,
    sessions: tuple[SessionFrame, ...],
    candidates: tuple[Candidate, ...],
    **kwargs,
):
    return simulate(
        setup=locked_setup_contract("P-D"),
        manifest=manifest,
        sessions=sessions,
        candidates=candidates,
        **kwargs,
    )


def test_partial_capacity_commission_slippage_and_doubled_friction_hand_calc():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    candidate = _candidate(
        manifest, "p1", dt.date(2024, 1, 1), day
    )
    result = _run(
        manifest,
        (SessionFrame(day, (_bar("p1"),)),),
        (candidate,),
    )
    trade = result.trades[0]
    assert trade.shares < 1000
    entry_cash_cost = (
        trade.entry_notional_2x + trade.entry_commission_2x
    )
    assert entry_cash_cost <= Decimal(100000)
    assert trade.entry_fill_2x > trade.next_open
    assert trade.exit_fill_2x < trade.exit_reference
    assert trade.net_pnl_2x < trade.net_pnl_base
    assert trade.entry_commission_2x == (
        trade.entry_notional_2x * Decimal("0.001") + Decimal(2)
    )
    assert trade.gross_pnl == (
        trade.shares * (trade.exit_reference - trade.next_open)
    )
    assert trade.net_r_2x == trade.net_pnl_2x / trade.initial_risk_dollars


def test_three_entry_throttle_and_equal_score_hash_tie():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    candidates = tuple(
        _candidate(
            manifest,
            permanent_id,
            dt.date(2024, 1, 1),
            day,
            symbol=symbol,
        )
        for permanent_id, symbol in (
            ("p-z", "AAA"),
            ("p-y", "ZZZ"),
            ("p-x", "MMM"),
            ("p-w", "BBB"),
        )
    )
    result = _run(
        manifest,
        (SessionFrame(day, tuple(_bar(item.permanent_id) for item in candidates)),),
        candidates,
    )
    quota_rejections = [
        rejection
        for rejection in result.rejections
        if rejection.reason == "daily_entry_quota"
    ]
    assert len(result.trades) == 3
    assert len(quota_rejections) == 1
    expected_last = max(
        candidates,
        key=lambda item: tie_breaker(
            item.setup_id,
            item.signal_session,
            item.permanent_id,
        ),
    )
    assert quota_rejections[0].permanent_id == expected_last.permanent_id


def test_eight_slot_contention_across_three_openings():
    manifest = _manifest()
    days = tuple(dt.date(2024, 1, day) for day in (2, 3, 4))
    candidates = []
    frames = []
    all_ids: list[str] = []
    for day_index, day in enumerate(days):
        todays_ids = [f"p{day_index * 3 + offset}" for offset in range(3)]
        all_ids.extend(todays_ids)
        candidates.extend(
            _candidate(
                manifest,
                permanent_id,
                day - dt.timedelta(days=1),
                day,
                score=str(10 - offset),
            )
            for offset, permanent_id in enumerate(todays_ids)
        )
        frames.append(
            SessionFrame(day, tuple(_bar(permanent_id) for permanent_id in all_ids))
        )
    result = _run(manifest, tuple(frames), tuple(candidates))
    assert sum(item.reason == "slot_limit" for item in result.rejections) == 1
    assert result.metrics.concurrency["max"] == 6
    assert len(result.trades) == 8


def test_cash_contention_after_three_zero_recovery_delistings():
    manifest = _manifest()
    days = tuple(dt.date(2024, 1, day) for day in (2, 3, 4, 5))
    original_ids = [f"old-{index}" for index in range(8)]
    candidates: list[Candidate] = []
    for index, permanent_id in enumerate(original_ids):
        entry_index = min(index // 3, 2)
        entry = days[entry_index]
        candidates.append(
            _candidate(
                manifest,
                permanent_id,
                entry - dt.timedelta(days=1),
                entry,
                score=str(20 - index),
            )
        )
    new_ids = [f"new-{index}" for index in range(3)]
    candidates.extend(
        _candidate(
            manifest,
            permanent_id,
            days[3] - dt.timedelta(days=1),
            days[3],
            score=str(10 - index),
            signal_close="2000" if index == 2 else "100",
            atr="40" if index == 2 else "2",
        )
        for index, permanent_id in enumerate(new_ids)
    )
    frames = (
        SessionFrame(days[0], tuple(_bar(item) for item in original_ids[:3])),
        SessionFrame(days[1], tuple(_bar(item) for item in original_ids[:6])),
        SessionFrame(days[2], tuple(_bar(item) for item in original_ids)),
        SessionFrame(
            days[3],
            tuple(_bar(item) for item in original_ids[3:] + new_ids[:2])
            + (
                _bar(
                    new_ids[2],
                    open="2000",
                    high="2020",
                    low="1980",
                    close="2000",
                ),
            ),
            delistings=tuple(
                Delisting(permanent_id, None)
                for permanent_id in original_ids[:3]
            ),
        ),
    )
    result = _run(manifest, frames, tuple(candidates))
    assert sum(item.reason == "cash_limit" for item in result.rejections) == 1
    assert all(mark.cash >= 0 for mark in result.daily_marks)
    assert len(
        [
            event
            for event in result.ledger
            if event.event_type == "entry_filled"
            and event.payload["entry_session"] == days[3]
        ]
    ) == 2


def test_opening_gap_exits_precede_entries_and_block_same_session_reentry():
    manifest = _manifest()
    first = dt.date(2024, 1, 2)
    second = dt.date(2024, 1, 3)
    candidates = (
        _candidate(manifest, "p1", dt.date(2024, 1, 1), first),
        _candidate(manifest, "p1", dt.date(2024, 1, 2), second),
    )
    sessions = (
        SessionFrame(first, (_bar("p1"),)),
        SessionFrame(
            second,
            (_bar("p1", open="90", high="91", low="89", close="90"),),
        ),
    )
    result = _run(manifest, sessions, candidates)
    assert result.trades[0].exit_reason == "stop_gap"
    assert result.trades[0].exit_reference == Decimal(90)
    assert [item.reason for item in result.rejections] == [
        "same_session_reentry"
    ]


def test_target_gap_caps_improvement_and_symbol_change_uses_permanent_id():
    manifest = _manifest()
    first = dt.date(2024, 1, 2)
    second = dt.date(2024, 1, 3)
    candidate = _candidate(
        manifest,
        "permanent",
        dt.date(2024, 1, 1),
        first,
        symbol="OLD",
    )
    result = _run(
        manifest,
        (
            SessionFrame(first, (_bar("permanent", symbol="OLD"),)),
            SessionFrame(
                second,
                (
                    _bar(
                        "permanent",
                        symbol="NEW",
                        open="110",
                        high="111",
                        low="109",
                        close="110",
                    ),
                ),
            ),
        ),
        (candidate,),
    )
    trade = result.trades[0]
    assert trade.exit_reason == "target_gap"
    assert trade.exit_reference == trade.target_initial
    assert trade.exit_reference < Decimal(110)
    assert trade.entry_symbol == "OLD"
    assert trade.exit_symbol == "NEW"


def test_ambiguous_entry_bar_is_stop_first():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    result = _run(
        manifest,
        (
            SessionFrame(
                day,
                (_bar("p1", high="120", low="90", close="100"),),
            ),
        ),
        (_candidate(manifest, "p1", dt.date(2024, 1, 1), day),),
    )
    assert result.trades[0].exit_reason == "stop"
    assert result.trades[0].exit_session == day
    assert result.trades[0].exit_reference == result.trades[0].stop_initial


def test_time_exit_is_fifteenth_session_and_terminal_is_not_time():
    manifest = _manifest()
    start = dt.date(2024, 1, 2)
    days = tuple(start + dt.timedelta(days=offset) for offset in range(15))
    sessions = tuple(
        SessionFrame(day, (_bar("p1"),))
        for day in days
    )
    candidate = _candidate(
        manifest, "p1", dt.date(2024, 1, 1), days[0]
    )
    result = _run(manifest, sessions, (candidate,))
    assert result.trades[0].exit_reason == "time"
    assert result.trades[0].holding_sessions == 15

    short_result = _run(manifest, sessions[:2], (candidate,))
    assert short_result.trades[0].exit_reason == "terminal_liquidation"
    assert short_result.trades[0].holding_sessions == 2


def test_split_preserves_economic_exposure_and_cash_distribution_accrues():
    manifest = _manifest()
    first = dt.date(2024, 1, 2)
    second = dt.date(2024, 1, 3)
    candidate = _candidate(manifest, "p1", dt.date(2024, 1, 1), first)
    result = _run(
        manifest,
        (
            SessionFrame(first, (_bar("p1"),)),
            SessionFrame(
                second,
                (_bar("p1", open="50", high="51", low="49", close="50"),),
                splits=(Split("p1", Decimal(2)),),
                distributions=(
                    CashDistribution("p1", Decimal("0.50"), second),
                ),
            ),
        ),
        (candidate,),
    )
    trade = result.trades[0]
    assert trade.shares % 2 == 0
    assert trade.entry_notional_2x == (
        trade.shares * trade.entry_fill_2x
    )
    assert trade.cash_distributions == Decimal(trade.shares) * Decimal("0.50")
    assert result.daily_marks[-1].receivables == 0
    assert any(event.event_type == "split_applied" for event in result.ledger)
    assert any(
        event.event_type == "distribution_accrued" for event in result.ledger
    )


@pytest.mark.parametrize(
    ("recovery", "reason"),
    (
        (Decimal(25), "delisting_recovery"),
        (None, "delisting_zero_recovery"),
    ),
)
def test_delisting_recovery_and_zero_recovery_are_conservative(recovery, reason):
    manifest = _manifest()
    first = dt.date(2024, 1, 2)
    second = dt.date(2024, 1, 3)
    result = _run(
        manifest,
        (
            SessionFrame(first, (_bar("p1"),)),
            SessionFrame(
                second,
                (),
                delistings=(Delisting("p1", recovery),),
            ),
        ),
        (_candidate(manifest, "p1", dt.date(2024, 1, 1), first),),
    )
    trade = result.trades[0]
    assert trade.exit_reason == reason
    assert trade.exit_fill_2x == (recovery or Decimal(0))
    assert trade.exit_commission_2x == 0


def test_halt_and_gap_rejections_advance_to_next_frozen_candidates():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    candidates = (
        _candidate(manifest, "halt", dt.date(2024, 1, 1), day, score="3"),
        _candidate(manifest, "gap", dt.date(2024, 1, 1), day, score="2"),
        _candidate(manifest, "ok", dt.date(2024, 1, 1), day, score="1"),
    )
    halted = Bar(
        "halt",
        "HALT",
        None,
        None,
        None,
        None,
        executable_open=False,
        documented_halt=True,
    )
    result = _run(
        manifest,
        (
            SessionFrame(
                day,
                (
                    halted,
                    _bar("gap", open="104", high="105", low="103", close="104"),
                    _bar("ok"),
                ),
            ),
        ),
        candidates,
    )
    assert [item.reason for item in result.rejections] == [
        "halt_no_open",
        "excessive_gap",
    ]
    assert [trade.permanent_id for trade in result.trades] == ["ok"]


def test_control_parity_and_byte_identical_crash_retry():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    candidates = tuple(
        _candidate(
            manifest,
            f"p{index}",
            dt.date(2024, 1, 1),
            day,
            score=str(index),
        )
        for index in range(4)
    )
    sessions = (
        SessionFrame(day, tuple(_bar(item.permanent_id) for item in candidates)),
    )
    clean_one = _run(manifest, sessions, candidates)
    clean_two = _run(manifest, sessions, tuple(reversed(candidates)))
    assert clean_one.canonical_bytes() == clean_two.canonical_bytes()

    controlled = _run(
        manifest,
        sessions,
        rank_all_dates(candidates, control_id="random", replicate=9),
    )
    assert len(controlled.trades) == len(clean_one.trades)
    assert len(controlled.rejections) == len(clean_one.rejections)
    assert [event.event_type for event in controlled.ledger] == [
        event.event_type for event in clean_one.ledger
    ]

    with pytest.raises(SimulatedCrash) as caught:
        _run(manifest, sessions, candidates, crash_after_events=2)
    resumed = _run(
        manifest,
        sessions,
        candidates,
        resume_events=caught.value.events,
    )
    assert resumed.canonical_bytes() == clean_one.canonical_bytes()
    assert len({event.event_hash for event in resumed.ledger}) == len(
        resumed.ledger
    )
    assert all(
        {"study_id", "book_id", "setup_id", "fold_id", "source_identity"}
        <= set(event.payload)
        for event in resumed.ledger
    )
    with pytest.raises(TypeError):
        resumed.ledger[0].payload["cash_after"] = Decimal(0)
    with pytest.raises(TypeError):
        resumed.metrics.concurrency["max"] = 99
    assert {
        event.payload["slot"]
        for event in resumed.ledger
        if event.event_type == "entry_filled"
    } == {0, 1, 2}
    for boundary in range(len(clean_one.ledger) + 1):
        with pytest.raises(SimulatedCrash) as every_crash:
            _run(
                manifest,
                sessions,
                candidates,
                crash_after_events=boundary,
            )
        every_resume = _run(
            manifest,
            sessions,
            candidates,
            resume_events=every_crash.value.events,
        )
        assert every_resume.canonical_bytes() == clean_one.canonical_bytes()
    corrupted = replace(caught.value.events[0], event_type="corrupt")
    with pytest.raises(ContractViolation, match="diverges"):
        _run(
            manifest,
            sessions,
            candidates,
            resume_events=(corrupted,),
        )


def test_empty_book_requires_explicit_fold_identity():
    manifest = _manifest()
    session = SessionFrame(dt.date(2024, 1, 2), ())
    with pytest.raises(ContractViolation, match="empty candidate books"):
        _run(manifest, (session,), ())
    result = simulate(
        setup=locked_setup_contract("P-D"),
        manifest=manifest,
        sessions=(session,),
        candidates=(),
        fold_id="F3",
        book_id="random-17",
    )
    assert result.fold_id == "F3"
    assert result.book_id == "random-17"
    assert result.metrics.nrocc_2x is None


def test_stale_missing_invalid_geometry_and_existing_position_rejections():
    manifest = _manifest()
    first = dt.date(2024, 1, 2)
    second = dt.date(2024, 1, 3)
    stale = replace(
        _candidate(
            manifest,
            "stale",
            dt.date(2024, 1, 1),
            first,
            score="4",
        ),
        stale=True,
    )
    missing = _candidate(
        manifest,
        "missing",
        dt.date(2024, 1, 1),
        first,
        score="3",
    )
    invalid = _candidate(
        manifest,
        "invalid",
        dt.date(2024, 1, 1),
        first,
        score="2",
        atr="6",
    )
    opening = _candidate(
        manifest,
        "held",
        dt.date(2024, 1, 1),
        first,
        score="1",
    )
    duplicate_later = _candidate(
        manifest,
        "held",
        first,
        second,
        score="1",
    )
    result = _run(
        manifest,
        (
            SessionFrame(first, (_bar("invalid"), _bar("held"))),
            SessionFrame(second, (_bar("held"),)),
        ),
        (stale, missing, invalid, opening, duplicate_later),
    )
    assert [item.reason for item in result.rejections] == [
        "stale_input",
        "missing_open",
        "invalid_geometry",
        "existing_position",
    ]


def test_seeded_input_permutations_preserve_byte_identity_and_invariants():
    manifest = _manifest()
    day = dt.date(2024, 1, 2)
    candidates = [
        _candidate(
            manifest,
            f"p{index}",
            dt.date(2024, 1, 1),
            day,
            score=str(index % 3),
        )
        for index in range(12)
    ]
    sessions = (
        SessionFrame(day, tuple(_bar(item.permanent_id) for item in candidates)),
    )
    expected = _run(manifest, sessions, tuple(candidates))
    rng = random.Random(1729)
    for _ in range(25):
        permuted = candidates.copy()
        rng.shuffle(permuted)
        actual = _run(manifest, sessions, tuple(permuted))
        assert actual.canonical_bytes() == expected.canonical_bytes()
        assert all(mark.cash >= 0 for mark in actual.daily_marks)
        assert all(mark.open_positions <= 8 for mark in actual.daily_marks)
        fills_by_day: dict[dt.date, int] = {}
        for event in actual.ledger:
            if event.event_type == "entry_filled":
                entry_day = event.payload["entry_session"]
                fills_by_day[entry_day] = fills_by_day.get(entry_day, 0) + 1
        assert all(count <= 3 for count in fills_by_day.values())
        assert all(
            trade.initial_risk_dollars
            <= Decimal("0.005") * Decimal(1000000)
            for trade in actual.trades
        )


def test_published_gate1_canary_identity():
    manifest = _manifest(
        start=dt.date(2024, 1, 1),
        end=dt.date(2025, 1, 1),
    )
    signal = dt.date(2024, 1, 2)
    entry = dt.date(2024, 1, 3)
    candidate = Candidate(
        "P-D",
        "F1",
        "synthetic-permanent-id",
        "SYN",
        signal,
        entry,
        Decimal(1),
        Decimal(100),
        Decimal(2),
        Decimal(100000000),
        manifest.identity,
        {name: signal for name in REQUIRED_AS_OF_FACTS},
    )
    result = _run(
        manifest,
        (
            SessionFrame(
                entry,
                (
                    Bar(
                        "synthetic-permanent-id",
                        "SYN",
                        Decimal(100),
                        Decimal(101),
                        Decimal(99),
                        Decimal(100),
                    ),
                ),
            ),
        ),
        (candidate,),
    )
    assert result.final_identity == (
        "f06b558e739b1078419ba3491df28fec823409a117ca070844603d7173df5f2d"
    )
    assert hashlib.sha256(result.canonical_bytes()).hexdigest() == (
        "5d33857b80d8f722b65a434108839ee5298496ac925786ccfc9fe2cf85d6f39d"
    )
