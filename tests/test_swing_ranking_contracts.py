from __future__ import annotations

import datetime as dt
import hashlib
import inspect
from dataclasses import replace
from decimal import Decimal

import pytest

from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_LIMITATION_KINDS,
    REQUIRED_SOURCE_KINDS,
    Candidate,
    CandidateGrammar,
    ContractViolation,
    DiscoveryProtocol,
    EntryGeometry,
    SignalFact,
    SourceFact,
    SourceLimitation,
    StrategyRevision,
    locked_tie_break,
    swing_ranking_charter,
)
from sts.swing_ranking.identity import canonical_bytes, identity_hash


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _protocol() -> DiscoveryProtocol:
    cutoff = dt.date(2025, 1, 31)
    return DiscoveryProtocol(
        study_id="swing-ranking-v1",
        protocol_version="v1",
        evidence_label="retrospective_screening",
        evaluation_start=dt.date(2010, 1, 1),
        evaluation_end_exclusive=dt.date(2025, 2, 1),
        data_cutoff=cutoff,
        prospective_wall=dt.date(2025, 2, 3),
        charter=swing_ranking_charter(),
        candidate_grammar=CandidateGrammar(
            version="v1",
            definition={
                "higher_timeframe": "trend_or_level",
                "daily_trigger": "human_readable",
            },
        ),
        source_facts=tuple(
            SourceFact(
                kind=kind,
                content_hash=_hash(kind),
                as_of=cutoff,
                coverage_start=dt.date(2010, 1, 1),
                coverage_end_exclusive=dt.date(2025, 2, 1),
                adjustment_basis=ADJUSTMENT_BASIS,
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
        limitations=tuple(
            SourceLimitation(kind=kind, statement=f"{kind} remains a limitation")
            for kind in REQUIRED_LIMITATION_KINDS
        ),
    )


def _strategy(protocol: DiscoveryProtocol) -> StrategyRevision:
    return StrategyRevision(
        study_id="swing-ranking-v1",
        strategy_name="example setup",
        revision="r1",
        readable_rules=("trend defines where", "daily trigger defines when"),
        parameters={"atr_multiple": Decimal(2), "level": "prior_high"},
        geometry_spec_identity=_hash("geometry"),
        protocol_identity=protocol.identity,
        candidate_grammar_identity=protocol.candidate_grammar.identity,
        input_manifest_identity=protocol.input_manifest_identity,
        charter_identity=protocol.charter.identity,
    )


def _candidate(protocol: DiscoveryProtocol, strategy: StrategyRevision) -> Candidate:
    return Candidate(
        strategy_revision_identity=strategy.identity,
        input_manifest_identity=protocol.input_manifest_identity,
        permanent_id="perm-42",
        symbol="OLD",
        signal_session=dt.date(2025, 1, 30),
        entry_session=dt.date(2025, 1, 31),
        signal_close=Decimal(100),
        average_dollar_volume=Decimal(20000000),
        scheduled_earnings_session=dt.date(2025, 2, 6),
        sessions_before_earnings=4,
        facts_as_of={kind: dt.date(2025, 1, 30) for kind in REQUIRED_SOURCE_KINDS},
        signal_facts={
            "daily_close": SignalFact(
                value=Decimal(100), available_session=dt.date(2025, 1, 30)
            )
        },
        priority_value=Decimal("1.25"),
    )


def test_contracts_are_frozen_and_have_no_implicit_constructor_defaults():
    for contract in (
        CandidateGrammar,
        DiscoveryProtocol,
        StrategyRevision,
        Candidate,
        EntryGeometry,
    ):
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in inspect.signature(contract).parameters.values()
        )


def test_protocol_requires_complete_sources_limitations_and_exact_charter():
    protocol = _protocol()
    assert protocol.input_manifest_identity
    assert protocol.identity
    with pytest.raises(ContractViolation, match="every required kind"):
        replace(protocol, source_facts=protocol.source_facts[:-1])
    with pytest.raises(ContractViolation, match="every required kind"):
        replace(protocol, limitations=protocol.limitations[:-1])
    with pytest.raises(ContractViolation, match="ratified charter"):
        replace(protocol.charter, maximum_hold_sessions=20)


def test_protocol_identities_are_order_stable_and_reject_floats():
    protocol = _protocol()
    reversed_protocol = replace(
        protocol,
        source_facts=tuple(reversed(protocol.source_facts)),
        limitations=tuple(reversed(protocol.limitations)),
    )
    assert reversed_protocol.identity == protocol.identity
    assert reversed_protocol.input_manifest_identity == protocol.input_manifest_identity
    with pytest.raises(ContractViolation, match="float"):
        CandidateGrammar(version="v1", definition={"threshold": 1.5})
    with pytest.raises(ContractViolation, match="finite Decimal"):
        replace(protocol.charter, minimum_price=5)
    assert canonical_bytes({"price": Decimal("1.0")}) == canonical_bytes(
        {"price": Decimal(1)}
    )


def test_strategy_and_candidate_are_bound_to_protocol_and_permanent_id():
    protocol = _protocol()
    strategy = _strategy(protocol)
    candidate = _candidate(protocol, strategy)
    strategy.validate_against(protocol)
    candidate.validate_against(protocol, strategy)
    assert candidate.identity == replace(candidate, symbol="NEW").identity
    assert candidate.tie_break == locked_tie_break(
        strategy.identity, candidate.signal_session, candidate.permanent_id
    )
    assert candidate.tie_break == "af4470b69beab8956e0a4d7c7ed23a8b201f3327045f4f13fc281e57777f3feb"
    assert candidate.tie_break != locked_tie_break(
        strategy.identity, candidate.signal_session, "perm-43"
    )
    with pytest.raises(ContractViolation, match="earnings blackout"):
        replace(candidate, sessions_before_earnings=2).validate_against(protocol, strategy)
    with pytest.raises(ContractViolation, match="protocol cutoff"):
        replace(
            candidate,
            facts_as_of={
                kind: protocol.prospective_wall for kind in REQUIRED_SOURCE_KINDS
            },
        ).validate_against(protocol, strategy)


def test_entry_geometry_rejects_1_5r_and_enforces_stop_and_hold_limits():
    protocol = _protocol()
    strategy = _strategy(protocol)
    candidate = _candidate(protocol, strategy)
    geometry = EntryGeometry(
        candidate_identity=candidate.identity,
        entry_price=Decimal(100),
        initial_stop_price=Decimal(90),
        target_price=Decimal("115.01"),
        planned_hold_sessions=21,
    )
    geometry.validate_against(candidate, protocol.charter)
    assert geometry.planned_reward_risk == Decimal("1.501")
    with pytest.raises(ContractViolation, match="strictly greater"):
        replace(geometry, target_price=Decimal(115)).validate_against(
            candidate, protocol.charter
        )
    with pytest.raises(ContractViolation, match="stop exceeds"):
        replace(geometry, initial_stop_price=Decimal(87)).validate_against(
            candidate, protocol.charter
        )
    with pytest.raises(ContractViolation, match="hard 21-session"):
        replace(geometry, planned_hold_sessions=20).validate_against(
            candidate, protocol.charter
        )


def test_same_session_earnings_is_constructible_then_rejected_by_embargo():
    protocol = _protocol()
    strategy = _strategy(protocol)
    candidate = replace(
        _candidate(protocol, strategy),
        scheduled_earnings_session=dt.date(2025, 1, 31),
        sessions_before_earnings=0,
    )
    with pytest.raises(ContractViolation, match="earnings blackout"):
        candidate.validate_against(protocol, strategy)


def test_locked_tie_is_a_sha256_identity_not_a_symbol_sort():
    strategy_id = identity_hash("fixture", {"revision": "r1"})
    tie = locked_tie_break(strategy_id, dt.date(2025, 1, 30), "perm-42")
    assert len(tie) == 64
    assert tie == locked_tie_break(strategy_id, dt.date(2025, 1, 30), "perm-42")
