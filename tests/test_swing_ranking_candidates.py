from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal

import pandas as pd

from sts import calendar
from sts.swing_ranking.candidates import (
    ConditionSpec,
    FeatureSpec,
    ScheduledEarnings,
    StrategyProgram,
    build_feature_matrix,
    generate_candidates,
)
from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_LIMITATION_KINDS,
    REQUIRED_SOURCE_KINDS,
    CandidateGrammar,
    DiscoveryProtocol,
    SourceFact,
    SourceLimitation,
    StrategyRevision,
    swing_ranking_charter,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _frame(end: str) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        calendar.sessions_between(
            dt.date(2024, 1, 2),
            dt.date.fromisoformat(end),
        ),
        name="date",
    )
    values = list(range(len(index)))
    return pd.DataFrame(
        {
            "open": [100 + value for value in values],
            "high": [102 + value for value in values],
            "low": [99 + value for value in values],
            "close": [101 + value for value in values],
            "volume": [1_000_000 + 1_000 * value for value in values],
        },
        index=index,
    )


def _program() -> StrategyProgram:
    return StrategyProgram(
        version="fixture-v1",
        features=(
            FeatureSpec("daily_close", "daily", "raw", "close", 1),
            FeatureSpec("daily_sma3", "daily", "sma", "close", 3),
            FeatureSpec("weekly_close", "weekly", "raw", "close", 1),
            FeatureSpec("weekly_sma2", "weekly", "sma", "close", 2),
            FeatureSpec("monthly_close", "monthly", "raw", "close", 1),
        ),
        where=(
            ConditionSpec("weekly_close", "gt", "weekly_sma2", None),
        ),
        when=(
            ConditionSpec("daily_close", "gt", "daily_sma3", None),
        ),
        priority_feature="daily_close",
        priority_direction="descending",
        average_dollar_volume_lookback=3,
    )


def _protocol(program: StrategyProgram) -> DiscoveryProtocol:
    cutoff = dt.date(2024, 4, 30)
    return DiscoveryProtocol(
        study_id="swing-ranking-v1",
        protocol_version="v1",
        evidence_label="retrospective_screening",
        evaluation_start=dt.date(2024, 1, 2),
        evaluation_end_exclusive=dt.date(2024, 5, 1),
        data_cutoff=cutoff,
        prospective_wall=dt.date(2024, 5, 1),
        charter=swing_ranking_charter(),
        candidate_grammar=CandidateGrammar(
            version="v1",
            definition={"program_identities": (program.identity,)},
        ),
        source_facts=tuple(
            SourceFact(
                kind=kind,
                content_hash=_hash(kind),
                as_of=cutoff,
                coverage_start=dt.date(2024, 1, 1),
                coverage_end_exclusive=dt.date(2024, 5, 1),
                adjustment_basis=ADJUSTMENT_BASIS,
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
        limitations=tuple(
            SourceLimitation(kind=kind, statement=f"{kind} limitation")
            for kind in REQUIRED_LIMITATION_KINDS
        ),
    )


def _strategy(
    protocol: DiscoveryProtocol,
    program: StrategyProgram,
) -> StrategyRevision:
    return StrategyRevision(
        study_id="swing-ranking-v1",
        strategy_name="generic fixture",
        revision="r1",
        readable_rules=("completed weekly context", "daily close trigger"),
        parameters={"program": program.definition},
        geometry_spec_identity=_hash("geometry"),
        protocol_identity=protocol.identity,
        candidate_grammar_identity=protocol.candidate_grammar.identity,
        input_manifest_identity=protocol.input_manifest_identity,
        charter_identity=protocol.charter.identity,
    )


def test_incomplete_week_and_month_are_not_exposed():
    program = _program()
    matrix = build_feature_matrix(_frame("2024-02-14"), program)
    wednesday = pd.Timestamp("2024-02-14")
    assert matrix.available_sessions.at[wednesday, "weekly_close"] == pd.Timestamp(
        "2024-02-09"
    )
    assert matrix.available_sessions.at[wednesday, "monthly_close"] == pd.Timestamp(
        "2024-01-31"
    )


def test_completed_week_is_available_on_its_final_session():
    program = _program()
    matrix = build_feature_matrix(_frame("2024-02-16"), program)
    friday = pd.Timestamp("2024-02-16")
    assert matrix.available_sessions.at[friday, "weekly_close"] == friday


def test_decimal_threshold_conditions_execute_inside_float_feature_matrix():
    program = _program()
    threshold_program = replace(
        program,
        where=(ConditionSpec("weekly_close", "gt", None, Decimal(0)),),
        when=(ConditionSpec("daily_close", "gt", None, Decimal(0)),),
    )
    protocol = _protocol(threshold_program)
    strategy = _strategy(protocol, threshold_program)
    candidates = generate_candidates(
        frame=_frame("2024-02-16"),
        permanent_id="perm-1",
        symbol="AAA",
        protocol=protocol,
            strategy=strategy,
            program=threshold_program,
            geometry_fact_names=(),
            facts_as_of={
            kind: dt.date(2024, 1, 1) for kind in REQUIRED_SOURCE_KINDS
        },
        scheduled_earnings=(),
    )
    assert candidates


def test_future_bars_do_not_change_prior_features_or_candidates():
    program = _program()
    short = _frame("2024-03-15")
    long = _frame("2024-04-30")
    short_matrix = build_feature_matrix(short, program)
    long_matrix = build_feature_matrix(long, program)
    pd.testing.assert_frame_equal(
        short_matrix.values,
        long_matrix.values.loc[short.index],
    )
    protocol = _protocol(program)
    strategy = _strategy(protocol, program)
    facts = {kind: dt.date(2024, 1, 1) for kind in REQUIRED_SOURCE_KINDS}
    short_candidates = generate_candidates(
        frame=short,
        permanent_id="perm-1",
        symbol="AAA",
        protocol=protocol,
        strategy=strategy,
        program=program,
        geometry_fact_names=(),
        facts_as_of=facts,
        scheduled_earnings=(),
    )
    assert short_candidates[-1].signal_session == short.index[-1].date()
    long_candidates = generate_candidates(
        frame=long,
        permanent_id="perm-1",
        symbol="RENAMED",
        protocol=protocol,
        strategy=strategy,
        program=program,
        geometry_fact_names=(),
        facts_as_of=facts,
        scheduled_earnings=(),
    )
    prior_long = tuple(
        candidate
        for candidate in long_candidates
        if candidate.signal_session <= short.index[-1].date()
    )
    assert [candidate.identity for candidate in short_candidates] == [
        candidate.identity for candidate in prior_long
    ]


def test_candidate_captures_available_facts_and_symbol_is_not_identity():
    program = _program()
    protocol = _protocol(program)
    strategy = _strategy(protocol, program)
    candidates = generate_candidates(
        frame=_frame("2024-03-15"),
        permanent_id="perm-1",
        symbol="AAA",
        protocol=protocol,
            strategy=strategy,
            program=program,
            geometry_fact_names=(),
            facts_as_of={
            kind: dt.date(2024, 1, 1) for kind in REQUIRED_SOURCE_KINDS
        },
        scheduled_earnings=(
            ScheduledEarnings(
                earnings_session=dt.date(2024, 3, 15),
                known_session=dt.date(2024, 1, 2),
            ),
        ),
    )
    assert candidates
    candidate = candidates[-1]
    assert all(
        fact.available_session <= candidate.signal_session
        for fact in candidate.signal_facts.values()
    )
    assert candidate.entry_session > candidate.signal_session
