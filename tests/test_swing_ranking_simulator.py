from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal

from sts import calendar
from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_LIMITATION_KINDS,
    REQUIRED_SOURCE_KINDS,
    Candidate,
    CandidateGrammar,
    DiscoveryProtocol,
    EntryGeometry,
    GeometryProgram,
    SignalFact,
    SourceFact,
    SourceLimitation,
    StrategyRevision,
    swing_ranking_charter,
)
from sts.swing_ranking.simulator import DailyBar, simulate


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sessions(count: int = 24) -> tuple[dt.date, ...]:
    dates = calendar.sessions_between(dt.date(2024, 1, 2), dt.date(2024, 3, 1))
    return tuple(date.date() for date in dates[:count])


def _protocol() -> DiscoveryProtocol:
    cutoff = dt.date(2024, 3, 1)
    return DiscoveryProtocol(
        study_id="swing-ranking-v1",
        protocol_version="v1",
        evidence_label="retrospective_screening",
        evaluation_start=dt.date(2023, 12, 29),
        evaluation_end_exclusive=dt.date(2024, 3, 2),
        data_cutoff=cutoff,
        prospective_wall=dt.date(2024, 3, 4),
        charter=swing_ranking_charter(),
        candidate_grammar=CandidateGrammar(version="v1", definition={"fixture": "generic"}),
        source_facts=tuple(
            SourceFact(
                kind=kind,
                content_hash=_hash(kind),
                as_of=cutoff,
                coverage_start=dt.date(2024, 1, 1),
                coverage_end_exclusive=dt.date(2024, 3, 2),
                adjustment_basis=ADJUSTMENT_BASIS,
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
        limitations=tuple(
            SourceLimitation(kind=kind, statement=f"{kind} limitation")
            for kind in REQUIRED_LIMITATION_KINDS
        ),
    )


def _strategy(protocol: DiscoveryProtocol) -> StrategyRevision:
    return StrategyRevision(
        study_id="swing-ranking-v1",
        strategy_name="fixture",
        revision="r1",
        readable_rules=("where", "when"),
        parameters={"fixture": "generic"},
        geometry_spec_identity=_hash("geometry"),
        protocol_identity=protocol.identity,
        candidate_grammar_identity=protocol.candidate_grammar.identity,
        input_manifest_identity=protocol.input_manifest_identity,
        charter_identity=protocol.charter.identity,
    )


def _candidate(
    protocol: DiscoveryProtocol,
    strategy: StrategyRevision,
    permanent_id: str,
    entry_session: dt.date,
    priority: Decimal,
) -> Candidate:
    signal_session = calendar.nyse().previous_session(dt.datetime.combine(entry_session, dt.time())).date()
    return Candidate(
        strategy_revision_identity=strategy.identity,
        input_manifest_identity=protocol.input_manifest_identity,
        permanent_id=permanent_id,
        symbol=permanent_id,
        signal_session=signal_session,
        entry_session=entry_session,
        signal_close=Decimal(100),
        average_dollar_volume=Decimal(20000000),
        scheduled_earnings_session=None,
        sessions_before_earnings=None,
        facts_as_of={kind: dt.date(2024, 1, 1) for kind in REQUIRED_SOURCE_KINDS},
        signal_facts={"close": SignalFact(value=Decimal(100), available_session=signal_session)},
        priority_value=priority,
    )


def _geometry(candidate: Candidate, stop: Decimal = Decimal(95), target: Decimal = Decimal(108)) -> EntryGeometry:
    return EntryGeometry(
        candidate_identity=candidate.identity,
        entry_price=Decimal(100),
        initial_stop_price=stop,
        target_price=target,
        planned_hold_sessions=21,
    )


def _bars(sessions: tuple[dt.date, ...], **changes: tuple[Decimal, Decimal, Decimal, Decimal]) -> tuple[DailyBar, ...]:
    values = []
    for session in sessions:
        open_, high, low, close = changes.get(session.isoformat(), (Decimal(100), Decimal(101), Decimal(99), Decimal(100)))
        values.append(DailyBar(session=session, open=open_, high=high, low=low, close=close))
    return tuple(values)


def _run(
    candidates: tuple[Candidate, ...],
    bars: dict[str, tuple[DailyBar, ...]],
    geometries: dict[str, EntryGeometry],
):
    protocol = _protocol()
    strategy = _strategy(protocol)
    geometry_program = GeometryProgram(
        strategy_revision_identity=strategy.identity,
        geometry_spec_identity=strategy.geometry_spec_identity,
        program_name="fixture geometry",
        version="v1",
        readable_rules=("study supplies every stop and target",),
        parameters={"fixture": "generic"},
    )
    return simulate(
        protocol=protocol,
        strategy=strategy,
        geometry_program=geometry_program,
        candidates=candidates,
        geometries_by_candidate_identity=geometries,
        bars_by_permanent_id=bars,
        priority_direction="descending",
    )


def test_gap_exit_precedes_opening_fill_and_uses_gap_proceeds():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    carried = _candidate(protocol, strategy, "A", sessions[0], Decimal(2))
    entrant = _candidate(protocol, strategy, "B", sessions[1], Decimal(1))
    result = _run(
        (carried, entrant),
        {
            "A": _bars(sessions, **{sessions[1].isoformat(): (Decimal(90), Decimal(91), Decimal(89), Decimal(90))}),
            "B": _bars(sessions),
        },
        {carried.identity: _geometry(carried), entrant.identity: _geometry(entrant)},
    )
    assert result.trades[0].exit_reason == "gap_stop"
    assert result.trades[0].exit_session == sessions[1]
    entrant_order = next(order for order in result.orders if order.candidate_identity == entrant.identity)
    assert entrant_order.status == "filled"
    assert entrant_order.quantity == Decimal(147)


def test_intraday_stop_beats_target_collision_and_time_exit_is_session_21():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    collision = _candidate(protocol, strategy, "A", sessions[0], Decimal(1))
    timed = _candidate(protocol, strategy, "B", sessions[0], Decimal(2))
    result = _run(
        (collision, timed),
        {
            "A": _bars(sessions, **{sessions[0].isoformat(): (Decimal(100), Decimal(109), Decimal(94), Decimal(100))}),
            "B": _bars(sessions),
        },
        {collision.identity: _geometry(collision), timed.identity: _geometry(timed)},
    )
    trades = {trade.permanent_id: trade for trade in result.trades}
    assert trades["A"].exit_reason == "stop"
    assert trades["A"].exit_price == Decimal(95)
    assert trades["B"].exit_reason == "time"
    assert trades["B"].exit_session == sessions[20]


def test_priority_tie_break_duplicate_and_deployment_caps_are_durable():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    candidates = tuple(
        _candidate(protocol, strategy, permanent_id, sessions[0], Decimal(1))
        for permanent_id in ("Z", "A", "B", "C", "D", "E", "F")
    )
    duplicate = replace(
        candidates[0],
        signal_session=calendar.nyse()
        .previous_session(dt.datetime.combine(sessions[0], dt.time()))
        .date(),
        priority_value=Decimal(2),
    )
    result = _run(
        (*candidates, duplicate),
        {candidate.permanent_id: _bars(sessions) for candidate in candidates},
        {candidate.identity: _geometry(candidate) for candidate in (*candidates, duplicate)},
    )
    assert len(result.orders) == 8
    assert sum(order.status == "filled" for order in result.orders) == 6
    assert any(order.reason == "duplicate_security" for order in result.orders)
    assert any(order.reason == "portfolio_cap" for order in result.orders)
    assert all(record.deployed_fraction <= Decimal("0.80") for record in result.equity)


def test_intraday_exit_proceeds_cannot_fund_same_session_entry():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    carried = tuple(
        _candidate(protocol, strategy, permanent_id, sessions[0], Decimal(1))
        for permanent_id in ("A", "B", "C", "D", "E", "F")
    )
    entrant = _candidate(protocol, strategy, "G", sessions[1], Decimal(2))
    target_day = {
        sessions[1].isoformat(): (
            Decimal(100),
            Decimal(109),
            Decimal(99),
            Decimal(108),
        )
    }
    bars = {
        candidate.permanent_id: _bars(sessions, **target_day)
        for candidate in carried
    }
    bars["G"] = _bars(sessions)
    all_candidates = (*carried, entrant)
    result = _run(
        all_candidates,
        bars,
        {candidate.identity: _geometry(candidate) for candidate in all_candidates},
    )
    entrant_order = next(
        order
        for order in result.orders
        if order.candidate_identity == entrant.identity
    )
    assert entrant_order.status == "rejected"
    assert entrant_order.reason == "portfolio_cap"
    assert all(
        trade.exit_session == sessions[1] and trade.exit_reason == "target"
        for trade in result.trades
    )


def test_reconciliation_and_event_hashes_are_deterministic():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    candidate = _candidate(protocol, strategy, "A", sessions[0], Decimal(1))
    bars = {"A": _bars(sessions)}
    geometries = {candidate.identity: _geometry(candidate)}
    first = _run((candidate,), bars, geometries)
    second = _run((candidate,), bars, geometries)
    first.assert_reconciled(Decimal(100000))
    assert [event.event_hash for event in first.events] == [event.event_hash for event in second.events]
    assert [event.session for event in first.events] == sorted(
        event.session for event in first.events
    )
    assert first.ending_equity == Decimal(100000)


def test_earnings_embargo_is_one_specific_terminal_rejection():
    protocol, strategy, sessions = _protocol(), None, _sessions()
    strategy = _strategy(protocol)
    candidate = replace(
        _candidate(protocol, strategy, "A", sessions[0], Decimal(1)),
        scheduled_earnings_session=sessions[1],
        sessions_before_earnings=1,
    )
    result = _run(
        (candidate,),
        {"A": _bars(sessions)},
        {candidate.identity: _geometry(candidate)},
    )
    assert len(result.orders) == 1
    assert result.orders[0].status == "rejected"
    assert result.orders[0].reason == "earnings_blackout"
    assert not result.trades
