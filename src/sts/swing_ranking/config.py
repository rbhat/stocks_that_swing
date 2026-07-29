"""Strict JSON study-bundle parsing for swing-ranking-v1."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sts.swing_ranking.candidates import ConditionSpec, FeatureSpec, StrategyProgram
from sts.swing_ranking.contracts import (
    CandidateGrammar,
    Charter,
    ContractViolation,
    DiscoveryProtocol,
    GeometryProgram,
    SourceFact,
    SourceLimitation,
    StrategyRevision,
)
from sts.swing_ranking.geometry import GeometrySpec, PriceFormula
from sts.swing_ranking.identity import IdentityViolation, canonical_bytes, identity_hash
from sts.swing_ranking.preflight import PreflightPaths


class ConfigurationViolation(ContractViolation):
    """A study bundle is incomplete, ambiguous, or contains an implicit value."""


def _object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ConfigurationViolation(f"{name} must contain exactly {sorted(keys)}")
    return value


def _list(value: object, name: str) -> tuple[Any, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationViolation(f"{name} must be a non-empty list")
    return tuple(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationViolation(f"{name} must be a non-empty string")
    return value.strip()


def _date(value: object, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(_text(value, name))
    except ValueError as exc:
        raise ConfigurationViolation(f"{name} must be an ISO date") from exc


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str):
        raise ConfigurationViolation(f"{name} must be an explicit decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigurationViolation(f"{name} must be a finite decimal string") from exc
    if not result.is_finite():
        raise ConfigurationViolation(f"{name} must be a finite decimal string")
    return result


def _read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationViolation(f"{name} is unreadable JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationViolation(f"{name} must be a JSON object")
    try:
        canonical_bytes(raw)
    except IdentityViolation as exc:
        raise ConfigurationViolation(f"{name} is not canonical: {exc}") from exc
    return raw


def _feature(raw: object) -> FeatureSpec:
    value = _object(
        raw,
        {"name", "timeframe", "operation", "source", "lookback"},
        "feature",
    )
    return FeatureSpec(
        name=_text(value["name"], "feature name"),
        timeframe=value["timeframe"],
        operation=_text(value["operation"], "feature operation"),
        source=_text(value["source"], "feature source"),
        lookback=value["lookback"],
    )


def _condition(raw: object) -> ConditionSpec:
    value = _object(
        raw,
        {"left", "comparator", "right_feature", "right_threshold"},
        "condition",
    )
    right_feature = value["right_feature"]
    if right_feature is not None:
        right_feature = _text(right_feature, "condition right_feature")
    threshold = value["right_threshold"]
    if threshold is not None:
        threshold = _decimal(threshold, "condition right_threshold")
    return ConditionSpec(
        left=_text(value["left"], "condition left"),
        comparator=_text(value["comparator"], "condition comparator"),
        right_feature=right_feature,
        right_threshold=threshold,
    )


def _program(raw: object) -> StrategyProgram:
    value = _object(
        raw,
        {
            "version",
            "features",
            "where",
            "when",
            "priority_feature",
            "priority_direction",
            "average_dollar_volume_lookback",
        },
        "strategy program",
    )
    return StrategyProgram(
        version=_text(value["version"], "program version"),
        features=tuple(_feature(item) for item in _list(value["features"], "features")),
        where=tuple(_condition(item) for item in _list(value["where"], "where")),
        when=tuple(_condition(item) for item in _list(value["when"], "when")),
        priority_feature=_text(value["priority_feature"], "priority_feature"),
        priority_direction=value["priority_direction"],
        average_dollar_volume_lookback=value["average_dollar_volume_lookback"],
    )


def _formula(raw: object) -> PriceFormula:
    value = _object(
        raw,
        {"kind", "primary_fact", "secondary_fact", "multiple"},
        "price formula",
    )
    return PriceFormula(
        kind=value["kind"],
        primary_fact=value["primary_fact"],
        secondary_fact=value["secondary_fact"],
        multiple=_decimal(value["multiple"], "price formula multiple"),
    )


def _geometry(raw: object) -> GeometrySpec:
    value = _object(
        raw,
        {"version", "stop", "target", "hold_sessions"},
        "geometry",
    )
    return GeometrySpec(
        version=_text(value["version"], "geometry version"),
        stop=_formula(value["stop"]),
        target=_formula(value["target"]),
        hold_sessions=value["hold_sessions"],
    )


def _charter(raw: object) -> Charter:
    keys = {
        "starting_capital",
        "risk_fraction",
        "maximum_notional_fraction",
        "maximum_positions",
        "maximum_deployed_fraction",
        "minimum_price",
        "minimum_average_dollar_volume",
        "maximum_stop_fraction",
        "minimum_planned_reward_risk",
        "minimum_hold_sessions",
        "maximum_hold_sessions",
        "earnings_blackout_sessions",
        "long_only",
        "paper_only",
    }
    value = _object(raw, keys, "charter")
    return Charter(
        starting_capital=_decimal(value["starting_capital"], "starting_capital"),
        risk_fraction=_decimal(value["risk_fraction"], "risk_fraction"),
        maximum_notional_fraction=_decimal(
            value["maximum_notional_fraction"],
            "maximum_notional_fraction",
        ),
        maximum_positions=value["maximum_positions"],
        maximum_deployed_fraction=_decimal(
            value["maximum_deployed_fraction"],
            "maximum_deployed_fraction",
        ),
        minimum_price=_decimal(value["minimum_price"], "minimum_price"),
        minimum_average_dollar_volume=_decimal(
            value["minimum_average_dollar_volume"],
            "minimum_average_dollar_volume",
        ),
        maximum_stop_fraction=_decimal(
            value["maximum_stop_fraction"],
            "maximum_stop_fraction",
        ),
        minimum_planned_reward_risk=_decimal(
            value["minimum_planned_reward_risk"],
            "minimum_planned_reward_risk",
        ),
        minimum_hold_sessions=value["minimum_hold_sessions"],
        maximum_hold_sessions=value["maximum_hold_sessions"],
        earnings_blackout_sessions=value["earnings_blackout_sessions"],
        long_only=value["long_only"],
        paper_only=value["paper_only"],
    )


@dataclass(frozen=True)
class ConfiguredStrategy:
    strategy: StrategyRevision
    program: StrategyProgram
    geometry_spec: GeometrySpec
    geometry_program: GeometryProgram


@dataclass(frozen=True)
class ConfiguredStudy:
    protocol: DiscoveryProtocol
    strategies: tuple[ConfiguredStrategy, ...]

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/configured-study/v1", self)


def load_study_bundle(path: Path) -> ConfiguredStudy:
    raw = _object(
        _read_json(Path(path), "study bundle"),
        {"protocol", "strategies"},
        "study bundle",
    )
    strategy_rows = _list(raw["strategies"], "strategies")
    components: list[tuple[dict[str, Any], StrategyProgram, GeometrySpec]] = []
    for row in strategy_rows:
        value = _object(
            row,
            {
                "name",
                "revision",
                "readable_rules",
                "program",
                "geometry",
            },
            "strategy",
        )
        components.append((value, _program(value["program"]), _geometry(value["geometry"])))
    program_ids = tuple(item[1].identity for item in components)
    geometry_ids = tuple(item[2].identity for item in components)
    if len(set(zip(program_ids, geometry_ids, strict=True))) != len(components):
        raise ConfigurationViolation("strategy program/geometry pairs must be unique")
    protocol_raw = _object(
        raw["protocol"],
        {
            "study_id",
            "protocol_version",
            "evidence_label",
            "evaluation_start",
            "evaluation_end_exclusive",
            "data_cutoff",
            "prospective_wall",
            "grammar_version",
            "charter",
            "source_facts",
            "limitations",
        },
        "protocol",
    )
    grammar = CandidateGrammar(
        version=_text(protocol_raw["grammar_version"], "grammar_version"),
        definition={
            "program_identities": program_ids,
            "geometry_spec_identities": geometry_ids,
        },
    )
    source_facts = tuple(
        SourceFact(
            kind=_text(item["kind"], "source kind"),
            content_hash=_text(item["content_hash"], "source hash"),
            as_of=_date(item["as_of"], "source as_of"),
            coverage_start=_date(item["coverage_start"], "source coverage_start"),
            coverage_end_exclusive=_date(
                item["coverage_end_exclusive"],
                "source coverage_end_exclusive",
            ),
            adjustment_basis=_text(
                item["adjustment_basis"],
                "source adjustment_basis",
            ),
        )
        for item in (
            _object(
                row,
                {
                    "kind",
                    "content_hash",
                    "as_of",
                    "coverage_start",
                    "coverage_end_exclusive",
                    "adjustment_basis",
                },
                "source fact",
            )
            for row in _list(protocol_raw["source_facts"], "source_facts")
        )
    )
    limitations = tuple(
        SourceLimitation(
            kind=_text(item["kind"], "limitation kind"),
            statement=_text(item["statement"], "limitation statement"),
        )
        for item in (
            _object(row, {"kind", "statement"}, "limitation")
            for row in _list(protocol_raw["limitations"], "limitations")
        )
    )
    protocol = DiscoveryProtocol(
        study_id=_text(protocol_raw["study_id"], "study_id"),
        protocol_version=_text(
            protocol_raw["protocol_version"],
            "protocol_version",
        ),
        evidence_label=_text(protocol_raw["evidence_label"], "evidence_label"),
        evaluation_start=_date(
            protocol_raw["evaluation_start"],
            "evaluation_start",
        ),
        evaluation_end_exclusive=_date(
            protocol_raw["evaluation_end_exclusive"],
            "evaluation_end_exclusive",
        ),
        data_cutoff=_date(protocol_raw["data_cutoff"], "data_cutoff"),
        prospective_wall=_date(
            protocol_raw["prospective_wall"],
            "prospective_wall",
        ),
        charter=_charter(protocol_raw["charter"]),
        candidate_grammar=grammar,
        source_facts=source_facts,
        limitations=limitations,
    )
    configured: list[ConfiguredStrategy] = []
    for value, program, geometry in components:
        feature_names = {feature.name for feature in program.features}
        if not set(geometry.signal_fact_names).issubset(feature_names):
            raise ConfigurationViolation(
                "geometry formulas must reference declared strategy features"
            )
        rules = tuple(
            _text(item, "readable rule")
            for item in _list(value["readable_rules"], "readable_rules")
        )
        strategy = StrategyRevision(
            study_id=protocol.study_id,
            strategy_name=_text(value["name"], "strategy name"),
            revision=_text(value["revision"], "strategy revision"),
            readable_rules=rules,
            parameters={"program": program.definition},
            geometry_spec_identity=geometry.identity,
            protocol_identity=protocol.identity,
            candidate_grammar_identity=grammar.identity,
            input_manifest_identity=protocol.input_manifest_identity,
            charter_identity=protocol.charter.identity,
        )
        geometry_program = GeometryProgram(
            strategy_revision_identity=strategy.identity,
            geometry_spec_identity=geometry.identity,
            program_name=f"{strategy.strategy_name} geometry",
            version=geometry.version,
            readable_rules=rules,
            parameters={"geometry_spec": geometry.definition},
        )
        configured.append(
            ConfiguredStrategy(strategy, program, geometry, geometry_program)
        )
    return ConfiguredStudy(protocol, tuple(configured))


def load_preflight_paths(path: Path) -> PreflightPaths:
    raw = _object(
        _read_json(Path(path), "preflight paths"),
        {
            "roster",
            "roster_manifest",
            "source_manifest",
            "security_master",
            "symbol_history",
            "corporate_actions",
            "earnings_calendar",
            "exchange_calendar",
            "parquet_root",
        },
        "preflight paths",
    )
    base = Path(path).resolve().parent

    def resolved(name: str) -> Path:
        value = Path(_text(raw[name], name))
        return value if value.is_absolute() else base / value

    return PreflightPaths(
        roster=resolved("roster"),
        roster_manifest=resolved("roster_manifest"),
        source_manifest=resolved("source_manifest"),
        security_master=resolved("security_master"),
        symbol_history=resolved("symbol_history"),
        corporate_actions=resolved("corporate_actions"),
        earnings_calendar=resolved("earnings_calendar"),
        exchange_calendar=resolved("exchange_calendar"),
        parquet_root=resolved("parquet_root"),
    )


__all__ = [
    "ConfigurationViolation",
    "ConfiguredStrategy",
    "ConfiguredStudy",
    "load_preflight_paths",
    "load_study_bundle",
]
