"""Strict JSON study-bundle parsing for swing-ranking-v1."""

from __future__ import annotations

import datetime as dt
import hashlib
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
    EvaluationSplit,
    GeometryProgram,
    SourceFact,
    SourceLimitation,
    SplitWindow,
    StrategyRevision,
)
from sts.swing_ranking.geometry import GeometrySpec, PriceFormula
from sts.swing_ranking.identity import IdentityViolation, canonical_bytes, identity_hash
from sts.swing_ranking.preflight import PreflightPaths
from sts.swing_ranking.split import derive_evaluation_split


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


def _split_window(raw: object, kind: str) -> SplitWindow:
    value = _object(
        raw,
        {"start", "end_exclusive", "session_count", "sessions_identity"},
        f"{kind} split window",
    )
    return SplitWindow(
        kind=kind,
        start=_date(value["start"], f"{kind} start"),
        end_exclusive=_date(value["end_exclusive"], f"{kind} end_exclusive"),
        session_count=value["session_count"],
        sessions_identity=_text(
            value["sessions_identity"],
            f"{kind} sessions_identity",
        ),
    )


def _evaluation_split(raw: object) -> EvaluationSplit:
    keys = {
        "version",
        "evaluation_start",
        "evaluation_end_exclusive",
        "development_fraction",
        "validation_fraction",
        "oos_fraction",
        "purge_entry_sessions",
        "session_count",
        "sessions_identity",
        "development",
        "development_validation_purge",
        "validation",
        "validation_oos_purge",
        "oos",
    }
    value = _object(raw, keys, "evaluation split")
    split = EvaluationSplit(
        version=_text(value["version"], "split version"),
        evaluation_start=_date(value["evaluation_start"], "split evaluation_start"),
        evaluation_end_exclusive=_date(
            value["evaluation_end_exclusive"],
            "split evaluation_end_exclusive",
        ),
        development_fraction=_decimal(
            value["development_fraction"],
            "development_fraction",
        ),
        validation_fraction=_decimal(
            value["validation_fraction"],
            "validation_fraction",
        ),
        oos_fraction=_decimal(value["oos_fraction"], "oos_fraction"),
        purge_entry_sessions=value["purge_entry_sessions"],
        session_count=value["session_count"],
        sessions_identity=_text(
            value["sessions_identity"],
            "split sessions_identity",
        ),
        development=_split_window(value["development"], "development"),
        development_validation_purge=_split_window(
            value["development_validation_purge"],
            "development_validation_purge",
        ),
        validation=_split_window(value["validation"], "validation"),
        validation_oos_purge=_split_window(
            value["validation_oos_purge"],
            "validation_oos_purge",
        ),
        oos=_split_window(value["oos"], "oos"),
    )
    expected = derive_evaluation_split(
        split.evaluation_start,
        split.evaluation_end_exclusive,
    )
    if split != expected:
        raise ConfigurationViolation(
            "evaluation split does not equal the deterministic XNYS derivation"
        )
    return split


@dataclass(frozen=True)
class ConfiguredStrategy:
    strategy: StrategyRevision
    program: StrategyProgram
    geometry_spec: GeometrySpec
    geometry_program: GeometryProgram


@dataclass(frozen=True)
class ConfiguredStudy:
    protocol: DiscoveryProtocol
    evidence_window: str
    strategies: tuple[ConfiguredStrategy, ...]

    def __post_init__(self) -> None:
        if self.evidence_window not in ("development", "validation", "oos"):
            raise ConfigurationViolation(
                "evidence_window must be development, validation, or oos"
            )
        strategies = tuple(self.strategies)
        if not strategies or not all(
            isinstance(value, ConfiguredStrategy) for value in strategies
        ):
            raise ConfigurationViolation(
                "strategies must contain configured strategies"
            )
        object.__setattr__(self, "strategies", strategies)

    @property
    def window(self) -> SplitWindow:
        return getattr(self.protocol.evaluation_split, self.evidence_window)

    @property
    def outcome_end_exclusive(self) -> dt.date:
        split = self.protocol.evaluation_split
        if self.evidence_window == "development":
            return split.development_validation_purge.end_exclusive
        if self.evidence_window == "validation":
            return split.validation_oos_purge.end_exclusive
        return self.protocol.prospective_wall

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/configured-study/v1", self)


@dataclass(frozen=True)
class CohortMember:
    """One exact revision and its immutable cohort memberships."""

    strategy_name: str
    strategy_revision_identity: str
    memberships: tuple[str, ...]


@dataclass(frozen=True)
class CohortSelection:
    """User-approved OOS and forward cohort binding."""

    selection_name: str
    approved_on: dt.date
    study_bundle_sha256: str
    evidence_window: str
    members: tuple[CohortMember, ...]
    cohorts: dict[str, tuple[str, ...]]
    forward_run_id: str
    forward_eligible_cohorts: tuple[str, ...]
    forward_eligibility: str
    minimum_decision_trades_per_revision: int
    interim_trade_counts: tuple[int, ...]

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/cohort-selection/v1", self)


def load_study_bundle(path: Path) -> ConfiguredStudy:
    raw = _object(
        _read_json(Path(path), "study bundle"),
        {"protocol", "evidence_window", "strategies"},
        "study bundle",
    )
    evidence_window = _text(raw["evidence_window"], "evidence_window")
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
            "evaluation_split",
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
            "members": tuple(
                {
                    "program_identity": program_identity,
                    "geometry_spec_identity": geometry_identity,
                }
                for program_identity, geometry_identity in zip(
                    program_ids,
                    geometry_ids,
                    strict=True,
                )
            ),
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
    evaluation_split = _evaluation_split(protocol_raw["evaluation_split"])
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
        evaluation_split=evaluation_split,
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
    return ConfiguredStudy(protocol, evidence_window, tuple(configured))


def load_selected_study(
    bundle_path: Path,
    selection_path: Path,
) -> ConfiguredStudy:
    """Bind one explicit evidence-window selection to an exact frozen bundle."""
    bundle_path = Path(bundle_path)
    selection = _object(
        _read_json(Path(selection_path), "evidence selection"),
        {"schema_version", "study_bundle_sha256", "evidence_window"},
        "evidence selection",
    )
    if (
        _text(selection["schema_version"], "selection schema_version")
        != "swing-ranking-v1.evidence-selection.v1"
    ):
        raise ConfigurationViolation("unsupported evidence selection schema")
    expected_hash = _text(
        selection["study_bundle_sha256"],
        "selection study_bundle_sha256",
    )
    if len(expected_hash) != 64 or any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        raise ConfigurationViolation(
            "selection study_bundle_sha256 must be lowercase SHA-256 hex"
        )
    try:
        actual_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ConfigurationViolation(
            f"study bundle is unreadable: {exc}"
        ) from exc
    if actual_hash != expected_hash:
        raise ConfigurationViolation(
            "evidence selection does not match the frozen study bundle"
        )
    configured = load_study_bundle(bundle_path)
    evidence_window = _text(
        selection["evidence_window"],
        "selection evidence_window",
    )
    return ConfiguredStudy(
        configured.protocol,
        evidence_window,
        configured.strategies,
    )


def load_cohort_selected_study(
    bundle_path: Path,
    selection_path: Path,
) -> tuple[ConfiguredStudy, CohortSelection]:
    """Bind the approved nine-revision OOS/forward cohorts to one frozen bundle."""
    bundle_path = Path(bundle_path)
    raw = _object(
        _read_json(Path(selection_path), "cohort selection"),
        {
            "schema_version",
            "selection_name",
            "approved_on",
            "study_bundle_sha256",
            "evidence_window",
            "members",
            "cohorts",
            "forward",
        },
        "cohort selection",
    )
    if (
        _text(raw["schema_version"], "cohort selection schema_version")
        != "swing-ranking-v1.cohort-selection.v1"
    ):
        raise ConfigurationViolation("unsupported cohort selection schema")
    expected_hash = _text(raw["study_bundle_sha256"], "study bundle sha256")
    if len(expected_hash) != 64 or any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        raise ConfigurationViolation("study bundle sha256 must be lowercase SHA-256 hex")
    try:
        actual_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ConfigurationViolation(f"study bundle is unreadable: {exc}") from exc
    if actual_hash != expected_hash:
        raise ConfigurationViolation("cohort selection does not match the frozen study bundle")
    evidence_window = _text(raw["evidence_window"], "evidence_window")
    if evidence_window != "oos":
        raise ConfigurationViolation("cohort selection must select oos")
    configured = load_study_bundle(bundle_path)
    strategy_by_id = {
        item.strategy.identity: item for item in configured.strategies
    }
    members: list[CohortMember] = []
    for row in _list(raw["members"], "cohort members"):
        value = _object(
            row,
            {"strategy_name", "strategy_revision_identity", "memberships"},
            "cohort member",
        )
        identity = _text(
            value["strategy_revision_identity"],
            "strategy revision identity",
        )
        if len(identity) != 64 or any(
            character not in "0123456789abcdef" for character in identity
        ):
            raise ConfigurationViolation(
                "strategy revision identity must be lowercase SHA-256 hex"
            )
        memberships = tuple(
            _text(item, "cohort membership")
            for item in _list(value["memberships"], "cohort memberships")
        )
        member = CohortMember(
            strategy_name=_text(value["strategy_name"], "strategy name"),
            strategy_revision_identity=identity,
            memberships=memberships,
        )
        frozen = strategy_by_id.get(identity)
        if frozen is None or frozen.strategy.strategy_name != member.strategy_name:
            raise ConfigurationViolation(
                "cohort member does not match a frozen strategy name and identity"
            )
        members.append(member)
    if len(members) != 9 or len({item.strategy_revision_identity for item in members}) != 9:
        raise ConfigurationViolation("cohort selection must contain nine unique revisions")
    cohort_rows = _object(raw["cohorts"], {"VF9", "MC5", "FO4"}, "cohorts")
    cohorts = {
        name: tuple(
            _text(item, f"{name} strategy identity")
            for item in _list(cohort_rows[name], name)
        )
        for name in ("VF9", "MC5", "FO4")
    }
    member_ids = {item.strategy_revision_identity for item in members}
    vf9, mc5, fo4 = map(set, (cohorts["VF9"], cohorts["MC5"], cohorts["FO4"]))
    if (
        len(cohorts["VF9"]) != 9
        or len(cohorts["MC5"]) != 5
        or len(cohorts["FO4"]) != 4
        or vf9 != member_ids
        or mc5 & fo4
        or mc5 | fo4 != vf9
    ):
        raise ConfigurationViolation("cohorts must satisfy VF9 = MC5 + FO4 with 9/5/4 members")
    expected_memberships = {
        identity: {"VF9", "MC5" if identity in mc5 else "FO4"}
        for identity in vf9
    }
    if any(
        set(item.memberships) != expected_memberships[item.strategy_revision_identity]
        for item in members
    ):
        raise ConfigurationViolation("member cohort labels do not match cohort definitions")
    forward = _object(
        raw["forward"],
        {
            "run_id",
            "eligible_cohorts",
            "eligibility",
            "minimum_decision_trades_per_revision",
            "interim_trade_counts",
        },
        "forward selection",
    )
    eligible = tuple(
        _text(item, "forward eligible cohort")
        for item in _list(forward["eligible_cohorts"], "forward eligible cohorts")
    )
    if set(eligible) != {"VF9", "MC5"}:
        raise ConfigurationViolation("VF9 and MC5 must both be forward eligible")
    eligibility = _text(forward["eligibility"], "forward eligibility")
    if eligibility != "unconditional_pre_oos":
        raise ConfigurationViolation("forward eligibility must be unconditional_pre_oos")
    minimum_trades = forward["minimum_decision_trades_per_revision"]
    interim = tuple(forward["interim_trade_counts"])
    if minimum_trades != 30 or interim != (10, 20):
        raise ConfigurationViolation("forward evidence thresholds must remain 10/20 interim and 30 decision-ready")
    selection = CohortSelection(
        selection_name=_text(raw["selection_name"], "selection name"),
        approved_on=_date(raw["approved_on"], "approved_on"),
        study_bundle_sha256=expected_hash,
        evidence_window=evidence_window,
        members=tuple(members),
        cohorts=cohorts,
        forward_run_id=_text(forward["run_id"], "forward run id"),
        forward_eligible_cohorts=eligible,
        forward_eligibility=eligibility,
        minimum_decision_trades_per_revision=minimum_trades,
        interim_trade_counts=interim,
    )
    selected = tuple(
        strategy_by_id[item.strategy_revision_identity] for item in members
    )
    return ConfiguredStudy(configured.protocol, "oos", selected), selection


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
    "CohortMember",
    "CohortSelection",
    "ConfigurationViolation",
    "ConfiguredStrategy",
    "ConfiguredStudy",
    "load_cohort_selected_study",
    "load_preflight_paths",
    "load_selected_study",
    "load_study_bundle",
]
