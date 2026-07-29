"""Fail-closed, I/O-free contracts for the ``swing-ranking-v1`` study."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from sts.swing_ranking.identity import (
    IdentityViolation,
    canonical_bytes,
    identity_hash,
    require_sha256,
)

STUDY_ID = "swing-ranking-v1"
ADJUSTMENT_BASIS = "split_and_dividend_adjusted_total_return"
REQUIRED_SOURCE_KINDS = (
    "security_master",
    "current_roster",
    "daily_market_data",
    "corporate_actions",
    "earnings_calendar",
    "exchange_calendar",
)
REQUIRED_LIMITATION_KINDS = (
    "current_roster_survivorship",
    "symbol_history",
    "delisting_coverage",
    "adjustment_vintage",
    "historical_earnings_calendar",
)
TIE_BREAK_DOMAIN = "swing-ranking-v1/tie-break/v1"

D0 = Decimal(0)
D1 = Decimal(1)


class ContractViolation(ValueError):
    """A swing-ranking-v1 value is incomplete or violates the charter."""


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be a non-empty string")
    return value.strip()


def _date(value: dt.date, name: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ContractViolation(f"{name} must be a datetime.date")
    return value


def _decimal(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal) or isinstance(value, bool) or not value.is_finite():
        raise ContractViolation(f"{name} must be a finite Decimal")
    return value


def _positive_decimal(value: Decimal, name: str) -> Decimal:
    value = _decimal(value, name)
    if value <= D0:
        raise ContractViolation(f"{name} must be positive")
    return value


def _positive_count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractViolation(f"{name} must be a positive integer")
    return value


def _sha256(value: str, name: str) -> str:
    try:
        return require_sha256(value, name)
    except IdentityViolation as exc:
        raise ContractViolation(str(exc)) from exc


def _freeze_mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractViolation(f"{name} must be a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        frozen[_text(key, f"{name} key")] = _freeze_value(item, f"{name}[{key!r}]")
    try:
        canonical_bytes(frozen)
    except IdentityViolation as exc:
        raise ContractViolation(str(exc)) from exc
    return MappingProxyType(frozen)


def _freeze_value(value: Any, name: str) -> Any:
    if isinstance(value, float):
        raise ContractViolation(f"{name} contains a float; use Decimal")
    if isinstance(value, Mapping):
        return _freeze_mapping(value, name)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_value(item, f"{name} item") for item in value)
    try:
        canonical_bytes(value)
    except IdentityViolation as exc:
        raise ContractViolation(str(exc)) from exc
    return value


@dataclass(frozen=True)
class Charter:
    """The ratified non-negotiable constraints, supplied explicitly per study."""

    starting_capital: Decimal
    risk_fraction: Decimal
    maximum_notional_fraction: Decimal
    maximum_positions: int
    maximum_deployed_fraction: Decimal
    minimum_price: Decimal
    minimum_average_dollar_volume: Decimal
    maximum_stop_fraction: Decimal
    minimum_planned_reward_risk: Decimal
    minimum_hold_sessions: int
    maximum_hold_sessions: int
    earnings_blackout_sessions: int
    long_only: bool
    paper_only: bool

    def __post_init__(self) -> None:
        money_fields = (
            "starting_capital",
            "risk_fraction",
            "maximum_notional_fraction",
            "maximum_deployed_fraction",
            "minimum_price",
            "minimum_average_dollar_volume",
            "maximum_stop_fraction",
            "minimum_planned_reward_risk",
        )
        for name in money_fields:
            object.__setattr__(self, name, _positive_decimal(getattr(self, name), name))
        for name in (
            "maximum_positions",
            "minimum_hold_sessions",
            "maximum_hold_sessions",
            "earnings_blackout_sessions",
        ):
            object.__setattr__(self, name, _positive_count(getattr(self, name), name))
        if self.minimum_hold_sessions > self.maximum_hold_sessions:
            raise ContractViolation("minimum_hold_sessions cannot exceed maximum_hold_sessions")
        if not isinstance(self.long_only, bool) or not self.long_only:
            raise ContractViolation("long_only must be explicitly True")
        if not isinstance(self.paper_only, bool) or not self.paper_only:
            raise ContractViolation("paper_only must be explicitly True")
        required = {
            "starting_capital": Decimal(100000),
            "risk_fraction": Decimal("0.0075"),
            "maximum_notional_fraction": Decimal("0.15"),
            "maximum_positions": 8,
            "maximum_deployed_fraction": Decimal("0.80"),
            "minimum_price": Decimal(5),
            "minimum_average_dollar_volume": Decimal(20000000),
            "maximum_stop_fraction": Decimal("0.12"),
            "minimum_planned_reward_risk": Decimal("1.5"),
            "minimum_hold_sessions": 3,
            "maximum_hold_sessions": 21,
            "earnings_blackout_sessions": 2,
        }
        for name, expected in required.items():
            if getattr(self, name) != expected:
                raise ContractViolation(f"{name} must equal the ratified charter value")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/charter/v1", self)


def swing_ranking_charter() -> Charter:
    """Return the complete ratified charter without introducing implicit defaults."""
    return Charter(
        starting_capital=Decimal(100000),
        risk_fraction=Decimal("0.0075"),
        maximum_notional_fraction=Decimal("0.15"),
        maximum_positions=8,
        maximum_deployed_fraction=Decimal("0.80"),
        minimum_price=Decimal(5),
        minimum_average_dollar_volume=Decimal(20000000),
        maximum_stop_fraction=Decimal("0.12"),
        minimum_planned_reward_risk=Decimal("1.5"),
        minimum_hold_sessions=3,
        maximum_hold_sessions=21,
        earnings_blackout_sessions=2,
        long_only=True,
        paper_only=True,
    )


@dataclass(frozen=True)
class SourceFact:
    """A bounded source input and its point-in-time availability fact."""

    kind: str
    content_hash: str
    as_of: dt.date
    coverage_start: dt.date
    coverage_end_exclusive: dt.date
    adjustment_basis: str

    def __post_init__(self) -> None:
        kind = _text(self.kind, "source fact kind")
        if kind not in REQUIRED_SOURCE_KINDS:
            raise ContractViolation(f"unknown source fact kind {kind!r}")
        object.__setattr__(self, "kind", kind)
        _sha256(self.content_hash, f"{kind} content_hash")
        as_of = _date(self.as_of, f"{kind} as_of")
        start = _date(self.coverage_start, f"{kind} coverage_start")
        end = _date(self.coverage_end_exclusive, f"{kind} coverage_end_exclusive")
        if start >= end:
            raise ContractViolation(f"{kind} coverage must be non-empty")
        if as_of < start:
            raise ContractViolation(f"{kind} as_of cannot precede coverage")
        if self.adjustment_basis != ADJUSTMENT_BASIS:
            raise ContractViolation("adjustment_basis must be split-and-dividend total return")


@dataclass(frozen=True)
class SourceLimitation:
    """A required, explicit limitation attached to every historical artifact."""

    kind: str
    statement: str

    def __post_init__(self) -> None:
        kind = _text(self.kind, "limitation kind")
        if kind not in REQUIRED_LIMITATION_KINDS:
            raise ContractViolation(f"unknown limitation kind {kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "statement", _text(self.statement, f"{kind} statement"))


@dataclass(frozen=True)
class CandidateGrammar:
    """The pre-performance grammar that bounds human-readable exploration."""

    version: str
    definition: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, "grammar version"))
        object.__setattr__(self, "definition", _freeze_mapping(self.definition, "grammar definition"))
        if not self.definition:
            raise ContractViolation("grammar definition cannot be empty")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/candidate-grammar/v1", self)


@dataclass(frozen=True)
class DiscoveryProtocol:
    """The complete pre-performance discovery record."""

    study_id: str
    protocol_version: str
    evidence_label: str
    evaluation_start: dt.date
    evaluation_end_exclusive: dt.date
    data_cutoff: dt.date
    prospective_wall: dt.date
    charter: Charter
    candidate_grammar: CandidateGrammar
    source_facts: tuple[SourceFact, ...]
    limitations: tuple[SourceLimitation, ...]

    def __post_init__(self) -> None:
        if _text(self.study_id, "study_id") != STUDY_ID:
            raise ContractViolation(f"study_id must be {STUDY_ID!r}")
        object.__setattr__(self, "protocol_version", _text(self.protocol_version, "protocol_version"))
        if self.evidence_label != "retrospective_screening":
            raise ContractViolation(
                "evidence_label must be explicitly retrospective_screening"
            )
        evaluation_start = _date(self.evaluation_start, "evaluation_start")
        evaluation_end = _date(
            self.evaluation_end_exclusive,
            "evaluation_end_exclusive",
        )
        if evaluation_start >= evaluation_end:
            raise ContractViolation("evaluation range must be non-empty")
        cutoff = _date(self.data_cutoff, "data_cutoff")
        wall = _date(self.prospective_wall, "prospective_wall")
        if wall <= cutoff:
            raise ContractViolation("prospective_wall must follow data_cutoff")
        if evaluation_end > wall or evaluation_start > cutoff:
            raise ContractViolation("evaluation range must end by the prospective wall")
        if not isinstance(self.charter, Charter):
            raise ContractViolation("charter must be a Charter")
        if not isinstance(self.candidate_grammar, CandidateGrammar):
            raise ContractViolation("candidate_grammar must be a CandidateGrammar")
        facts = tuple(self.source_facts)
        if not all(isinstance(fact, SourceFact) for fact in facts):
            raise ContractViolation("source_facts must contain SourceFact values")
        fact_kinds = [fact.kind for fact in facts]
        if len(fact_kinds) != len(set(fact_kinds)):
            raise ContractViolation("source facts must be unique by kind")
        if set(fact_kinds) != set(REQUIRED_SOURCE_KINDS):
            raise ContractViolation("source facts must include every required kind")
        if any(fact.as_of > cutoff for fact in facts):
            raise ContractViolation("source facts cannot be available after data_cutoff")
        object.__setattr__(self, "source_facts", tuple(sorted(facts, key=lambda fact: fact.kind)))
        limitations = tuple(self.limitations)
        if not all(isinstance(item, SourceLimitation) for item in limitations):
            raise ContractViolation("limitations must contain SourceLimitation values")
        limitation_kinds = [item.kind for item in limitations]
        if len(limitation_kinds) != len(set(limitation_kinds)):
            raise ContractViolation("limitations must be unique by kind")
        if set(limitation_kinds) != set(REQUIRED_LIMITATION_KINDS):
            raise ContractViolation("limitations must include every required kind")
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted(limitations, key=lambda item: item.kind)),
        )

    @property
    def input_manifest_identity(self) -> str:
        return identity_hash(
            "swing-ranking-v1/input-manifest/v1",
            {"source_facts": self.source_facts, "limitations": self.limitations},
        )

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/protocol/v1", self)


@dataclass(frozen=True)
class StrategyRevision:
    """An immutable, readable strategy revision bound to one protocol."""

    study_id: str
    strategy_name: str
    revision: str
    readable_rules: tuple[str, ...]
    parameters: Mapping[str, Any]
    protocol_identity: str
    candidate_grammar_identity: str
    input_manifest_identity: str
    charter_identity: str

    def __post_init__(self) -> None:
        if _text(self.study_id, "study_id") != STUDY_ID:
            raise ContractViolation(f"study_id must be {STUDY_ID!r}")
        object.__setattr__(self, "strategy_name", _text(self.strategy_name, "strategy_name"))
        object.__setattr__(self, "revision", _text(self.revision, "revision"))
        rules = tuple(_text(rule, "readable rule") for rule in self.readable_rules)
        if not rules:
            raise ContractViolation("readable_rules cannot be empty")
        object.__setattr__(self, "readable_rules", rules)
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters, "parameters"))
        if not self.parameters:
            raise ContractViolation("parameters cannot be empty")
        for name in (
            "protocol_identity",
            "candidate_grammar_identity",
            "input_manifest_identity",
            "charter_identity",
        ):
            _sha256(getattr(self, name), name)

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/strategy-revision/v1", self)

    def validate_against(self, protocol: DiscoveryProtocol) -> None:
        if self.protocol_identity != protocol.identity:
            raise ContractViolation("strategy revision protocol identity does not match")
        if self.candidate_grammar_identity != protocol.candidate_grammar.identity:
            raise ContractViolation("strategy revision grammar identity does not match")
        if self.input_manifest_identity != protocol.input_manifest_identity:
            raise ContractViolation("strategy revision input manifest identity does not match")
        if self.charter_identity != protocol.charter.identity:
            raise ContractViolation("strategy revision charter identity does not match")


@dataclass(frozen=True)
class SignalFact:
    """One numeric fact used at a completed signal close."""

    value: Decimal
    available_session: dt.date

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _decimal(self.value, "signal fact value"))
        object.__setattr__(
            self,
            "available_session",
            _date(self.available_session, "signal fact available_session"),
        )


@dataclass(frozen=True)
class Candidate:
    """A causal signal identified by permanent security ID.

    ``facts_as_of`` records source-snapshot provenance and may expose the
    accepted current-roster survivorship limitation. ``signal_facts`` alone
    carries decision-time values and must be available by the signal close.
    """

    strategy_revision_identity: str
    input_manifest_identity: str
    permanent_id: str
    symbol: str
    signal_session: dt.date
    entry_session: dt.date
    signal_close: Decimal
    average_dollar_volume: Decimal
    scheduled_earnings_session: dt.date | None
    sessions_before_earnings: int | None
    facts_as_of: Mapping[str, dt.date]
    signal_facts: Mapping[str, SignalFact]
    priority_value: Decimal

    def __post_init__(self) -> None:
        _sha256(self.strategy_revision_identity, "strategy_revision_identity")
        _sha256(self.input_manifest_identity, "input_manifest_identity")
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        symbol = _text(self.symbol, "symbol").upper()
        if any(character.isspace() for character in symbol):
            raise ContractViolation("symbol cannot contain whitespace")
        object.__setattr__(self, "symbol", symbol)
        signal = _date(self.signal_session, "signal_session")
        entry = _date(self.entry_session, "entry_session")
        if entry <= signal:
            raise ContractViolation("entry_session must follow signal_session")
        object.__setattr__(self, "signal_close", _positive_decimal(self.signal_close, "signal_close"))
        object.__setattr__(
            self,
            "average_dollar_volume",
            _positive_decimal(self.average_dollar_volume, "average_dollar_volume"),
        )
        earnings = self.scheduled_earnings_session
        sessions = self.sessions_before_earnings
        if earnings is None:
            if sessions is not None:
                raise ContractViolation("sessions_before_earnings requires an earnings session")
        else:
            earnings = _date(earnings, "scheduled_earnings_session")
            if earnings < entry:
                raise ContractViolation(
                    "scheduled_earnings_session cannot precede entry_session"
                )
            if not isinstance(sessions, int) or isinstance(sessions, bool):
                raise ContractViolation("sessions_before_earnings must be an integer")
            if sessions < 0:
                raise ContractViolation("sessions_before_earnings cannot be negative")
        facts = dict(self.facts_as_of)
        if set(facts) != set(REQUIRED_SOURCE_KINDS):
            raise ContractViolation("facts_as_of must include every required source kind")
        for kind, fact_date in facts.items():
            _date(fact_date, f"facts_as_of[{kind}]")
        object.__setattr__(self, "facts_as_of", MappingProxyType(facts))
        signal_facts = dict(self.signal_facts)
        if not signal_facts:
            raise ContractViolation("signal_facts cannot be empty")
        for name, fact in signal_facts.items():
            _text(name, "signal_facts key")
            if not isinstance(fact, SignalFact):
                raise ContractViolation("signal_facts must contain SignalFact values")
            if fact.available_session > signal:
                raise ContractViolation(
                    f"future signal fact {name} exceeds signal_session"
                )
        object.__setattr__(self, "signal_facts", MappingProxyType(signal_facts))
        object.__setattr__(self, "priority_value", _decimal(self.priority_value, "priority_value"))

    @property
    def identity(self) -> str:
        """Identity deliberately excludes the mutable ticker symbol."""
        return identity_hash(
            "swing-ranking-v1/candidate/v1",
            {
                "strategy_revision_identity": self.strategy_revision_identity,
                "input_manifest_identity": self.input_manifest_identity,
                "permanent_id": self.permanent_id,
                "signal_session": self.signal_session,
                "entry_session": self.entry_session,
                "signal_close": self.signal_close,
                "average_dollar_volume": self.average_dollar_volume,
                "scheduled_earnings_session": self.scheduled_earnings_session,
                "sessions_before_earnings": self.sessions_before_earnings,
                "facts_as_of": self.facts_as_of,
                "signal_facts": self.signal_facts,
                "priority_value": self.priority_value,
            },
        )

    @property
    def tie_break(self) -> str:
        return locked_tie_break(
            self.strategy_revision_identity,
            self.signal_session,
            self.permanent_id,
        )

    def validate_against(self, protocol: DiscoveryProtocol, strategy: StrategyRevision) -> None:
        strategy.validate_against(protocol)
        if self.strategy_revision_identity != strategy.identity:
            raise ContractViolation("candidate strategy revision identity does not match")
        if self.input_manifest_identity != protocol.input_manifest_identity:
            raise ContractViolation("candidate input manifest identity does not match")
        if not (
            protocol.evaluation_start
            <= self.signal_session
            < protocol.evaluation_end_exclusive
        ):
            raise ContractViolation("candidate signal is outside the evaluation range")
        if self.entry_session >= protocol.evaluation_end_exclusive:
            raise ContractViolation("candidate entry is outside the evaluation range")
        if any(as_of > protocol.data_cutoff for as_of in self.facts_as_of.values()):
            raise ContractViolation("candidate source fact exceeds the protocol cutoff")
        if self.signal_close < protocol.charter.minimum_price:
            raise ContractViolation("candidate signal_close is below the charter minimum price")
        if self.average_dollar_volume < protocol.charter.minimum_average_dollar_volume:
            raise ContractViolation("candidate average_dollar_volume is below the charter minimum")
        if self.scheduled_earnings_session is not None:
            assert self.sessions_before_earnings is not None
            if self.sessions_before_earnings <= protocol.charter.earnings_blackout_sessions:
                raise ContractViolation("candidate enters inside the earnings blackout")


def locked_tie_break(
    strategy_revision_identity: str,
    signal_session: dt.date,
    permanent_id: str,
) -> str:
    """Return the locked SHA-256 lexical tie key; ticker text never participates."""
    _sha256(strategy_revision_identity, "strategy_revision_identity")
    _date(signal_session, "signal_session")
    _text(permanent_id, "permanent_id")
    return identity_hash(
        TIE_BREAK_DOMAIN,
        {
            "strategy_revision_identity": strategy_revision_identity,
            "signal_session": signal_session,
            "permanent_id": permanent_id,
        },
    )


@dataclass(frozen=True)
class EntryGeometry:
    """Prospective entry geometry; strict reward/risk is checked before entry."""

    candidate_identity: str
    entry_price: Decimal
    initial_stop_price: Decimal
    target_price: Decimal
    planned_hold_sessions: int

    def __post_init__(self) -> None:
        _sha256(self.candidate_identity, "candidate_identity")
        entry = _positive_decimal(self.entry_price, "entry_price")
        stop = _positive_decimal(self.initial_stop_price, "initial_stop_price")
        target = _positive_decimal(self.target_price, "target_price")
        if stop >= entry:
            raise ContractViolation("initial_stop_price must be below entry_price")
        if target <= entry:
            raise ContractViolation("target_price must exceed entry_price")
        object.__setattr__(self, "planned_hold_sessions", _positive_count(self.planned_hold_sessions, "planned_hold_sessions"))

    @property
    def risk_per_share(self) -> Decimal:
        return self.entry_price - self.initial_stop_price

    @property
    def reward_per_share(self) -> Decimal:
        return self.target_price - self.entry_price

    @property
    def planned_reward_risk(self) -> Decimal:
        return self.reward_per_share / self.risk_per_share

    @property
    def stop_fraction(self) -> Decimal:
        return self.risk_per_share / self.entry_price

    def validate_against(self, candidate: Candidate, charter: Charter) -> None:
        if self.candidate_identity != candidate.identity:
            raise ContractViolation("entry geometry candidate identity does not match")
        if self.stop_fraction > charter.maximum_stop_fraction:
            raise ContractViolation("entry geometry stop exceeds the charter maximum")
        if self.planned_reward_risk <= charter.minimum_planned_reward_risk:
            raise ContractViolation("planned reward/risk must be strictly greater than 1.5")
        if self.planned_hold_sessions != charter.maximum_hold_sessions:
            raise ContractViolation("planned_hold_sessions must equal the hard 21-session stop")


@dataclass(frozen=True)
class GeometryProgram:
    """An explicit, strategy-bound source of prospective entry geometry.

    The program records *how* a study supplied its geometry but intentionally
    does not privilege a stop or target formula.  The evaluator receives the
    resulting ``EntryGeometry`` values keyed by candidate identity.
    """

    strategy_revision_identity: str
    program_name: str
    version: str
    readable_rules: tuple[str, ...]
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        _sha256(self.strategy_revision_identity, "strategy_revision_identity")
        object.__setattr__(self, "program_name", _text(self.program_name, "geometry program_name"))
        object.__setattr__(self, "version", _text(self.version, "geometry version"))
        rules = tuple(_text(rule, "geometry readable rule") for rule in self.readable_rules)
        if not rules:
            raise ContractViolation("geometry readable_rules cannot be empty")
        object.__setattr__(self, "readable_rules", rules)
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters, "geometry parameters"))
        if not self.parameters:
            raise ContractViolation("geometry parameters cannot be empty")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/geometry-program/v1", self)

    def validate_against(self, strategy: StrategyRevision) -> None:
        if self.strategy_revision_identity != strategy.identity:
            raise ContractViolation("geometry program strategy revision identity does not match")
