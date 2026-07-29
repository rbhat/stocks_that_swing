"""Canonical, immutable study artifacts for ``swing-ranking-v1``.

The writer is deliberately separate from evaluation: it receives only frozen
study values, validates their identity bindings, and publishes a complete
directory atomically.  It never reads the cache or runs a simulation.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

from sts.swing_ranking.contracts import (
    Candidate,
    ContractViolation,
    DiscoveryProtocol,
    EntryGeometry,
    GeometryProgram,
    StrategyRevision,
)
from sts.swing_ranking.identity import (
    canonical_bytes,
    canonical_json,
    identity_hash,
    sha256_hex,
)
from sts.swing_ranking.metrics import StrategyMetrics
from sts.swing_ranking.ranking import RankingReport
from sts.swing_ranking.simulator import SimulationResult

_ARTIFACT_DOMAIN = "swing-ranking-v1/artifact/v1"
_SCHEMA_VERSION = "swing-ranking-v1.artifact.v1"


class ArtifactViolation(ContractViolation):
    """Artifact inputs or an artifact destination are incomplete or unsafe."""


@dataclass(frozen=True)
class StrategyEvaluation:
    """All immutable outputs for one strategy revision and its one simulator run."""

    strategy: StrategyRevision
    geometry_program: GeometryProgram
    geometries: tuple[EntryGeometry, ...]
    candidates: tuple[Candidate, ...]
    simulation: SimulationResult
    metrics: StrategyMetrics

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyRevision):
            raise ArtifactViolation("strategy must be a StrategyRevision")
        if not isinstance(self.geometry_program, GeometryProgram):
            raise ArtifactViolation("geometry_program must be a GeometryProgram")
        self.geometry_program.validate_against(self.strategy)
        candidates = tuple(self.candidates)
        geometries = tuple(self.geometries)
        if not all(isinstance(item, Candidate) for item in candidates):
            raise ArtifactViolation("candidates must contain Candidate values")
        if not all(isinstance(item, EntryGeometry) for item in geometries):
            raise ArtifactViolation("geometries must contain EntryGeometry values")
        candidate_ids = [candidate.identity for candidate in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ArtifactViolation("candidates must be unique by identity")
        if tuple(sorted(candidate_ids)) != tuple(candidate_ids):
            raise ArtifactViolation("candidates must be candidate-SHA ordered")
        for candidate in candidates:
            if candidate.strategy_revision_identity != self.strategy.identity:
                raise ArtifactViolation("candidate strategy identity does not match evaluation")
        geometry_ids = [geometry.candidate_identity for geometry in geometries]
        if len(geometry_ids) != len(set(geometry_ids)):
            raise ArtifactViolation("geometries must be unique by candidate identity")
        if not set(geometry_ids).issubset(candidate_ids):
            raise ArtifactViolation("geometry references a candidate absent from evaluation")
        if tuple(sorted(geometry_ids)) != tuple(geometry_ids):
            raise ArtifactViolation("geometries must be candidate-SHA ordered")
        if not isinstance(self.simulation, SimulationResult):
            raise ArtifactViolation("simulation must be a SimulationResult")
        if not isinstance(self.metrics, StrategyMetrics):
            raise ArtifactViolation("metrics must be a StrategyMetrics")
        if self.metrics.strategy_revision_identity != self.strategy.identity:
            raise ArtifactViolation("metrics strategy identity does not match evaluation")
        if len(self.simulation.orders) != len(candidates):
            raise ArtifactViolation("simulation orders must exactly cover candidates")
        if {order.candidate_identity for order in self.simulation.orders} != set(candidate_ids):
            raise ArtifactViolation("simulation orders do not exactly match candidates")
        self.simulation.assert_reconciled(self.metrics.starting_capital)
        if self.metrics.candidate_count != len(candidates):
            raise ArtifactViolation("metrics candidate count does not match candidates")
        if self.metrics.order_count != len(self.simulation.orders):
            raise ArtifactViolation("metrics order count does not match simulation")
        if self.metrics.trade_count != len(self.simulation.trades):
            raise ArtifactViolation("metrics trade count does not match simulation")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "geometries", geometries)

@dataclass(frozen=True)
class ArtifactPackage:
    """Canonical files and content identity ready for a durable publication."""

    identity: str
    files: Mapping[str, bytes]
    synthetic: bool

    def __post_init__(self) -> None:
        if not isinstance(self.identity, str) or len(self.identity) != 64:
            raise ArtifactViolation("artifact identity must be a SHA-256 hex string")
        files = dict(self.files)
        if not files or any(not isinstance(name, str) or not name for name in files):
            raise ArtifactViolation("artifact files must be a non-empty relative-name mapping")
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in files):
            raise ArtifactViolation("artifact file names must remain below the artifact directory")
        if any(not isinstance(content, bytes) for content in files.values()):
            raise ArtifactViolation("artifact file contents must be bytes")
        object.__setattr__(self, "files", files)


@dataclass(frozen=True)
class ArtifactWriteResult:
    path: Path
    identity: str
    created: bool


def _record(record: object, identity: str | None) -> dict[str, object]:
    document: dict[str, object] = {"record": record}
    if identity is not None:
        document["identity"] = identity
    return document


def _canonical_value(value: object) -> object:
    """Normalize integer-keyed metric maps before the shared serializer sees them."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    return value


def _json(value: object) -> bytes:
    return canonical_bytes(_canonical_value(value)) + b"\n"


def _jsonl(rows: Sequence[object]) -> bytes:
    return b"".join(
        canonical_json(_canonical_value(row)).encode("utf-8") + b"\n" for row in rows
    )


def _validate_evaluations(
    protocol: DiscoveryProtocol,
    evaluations: Sequence[StrategyEvaluation],
    ranking: RankingReport,
) -> tuple[StrategyEvaluation, ...]:
    if not isinstance(protocol, DiscoveryProtocol):
        raise ArtifactViolation("protocol must be a DiscoveryProtocol")
    values = tuple(evaluations)
    if not values or not all(isinstance(value, StrategyEvaluation) for value in values):
        raise ArtifactViolation("evaluations must be non-empty StrategyEvaluation values")
    values = tuple(sorted(values, key=lambda value: value.strategy.identity))
    identities = [value.strategy.identity for value in values]
    if len(identities) != len(set(identities)):
        raise ArtifactViolation("evaluations must be unique by strategy identity")
    for value in values:
        value.strategy.validate_against(protocol)
        value.geometry_program.validate_against(value.strategy)
        candidate_by_id = {candidate.identity: candidate for candidate in value.candidates}
        for candidate in value.candidates:
            if candidate.strategy_revision_identity != value.strategy.identity:
                raise ArtifactViolation("candidate strategy binding does not match")
            if candidate.input_manifest_identity != protocol.input_manifest_identity:
                raise ArtifactViolation("candidate input-manifest binding does not match")
        filled_candidate_ids = {
            order.candidate_identity
            for order in value.simulation.orders
            if order.status == "filled"
        }
        if not filled_candidate_ids.issubset(candidate_by_id):
            raise ArtifactViolation("filled order references an unknown candidate")
        if not filled_candidate_ids.issubset(
            {geometry.candidate_identity for geometry in value.geometries}
        ):
            raise ArtifactViolation("filled order lacks recorded entry geometry")
    if not isinstance(ranking, RankingReport):
        raise ArtifactViolation("ranking must be a RankingReport")
    report_ids = {
        row.strategy_revision_identity
        for rows in (ranking.profit, ranking.drawdown, ranking.profit_drawdown)
        for row in rows
    }
    if report_ids - set(identities):
        raise ArtifactViolation("ranking references a strategy absent from evaluations")
    metrics_by_id = {value.strategy.identity: value.metrics for value in values}
    for rows in (ranking.profit, ranking.drawdown, ranking.profit_drawdown):
        for row in rows:
            if metrics_by_id.get(row.strategy_revision_identity) != row.metrics:
                raise ArtifactViolation("ranking metrics do not match strategy evaluation")
    return values


def _report_markdown(protocol: DiscoveryProtocol, evaluations: Sequence[StrategyEvaluation], identity: str, synthetic: bool) -> bytes:
    lines = [
        "# Swing ranking screening artifact",
        "",
        f"- Artifact identity: `{identity}`",
        f"- Evidence: `{protocol.evidence_label}`",
        f"- Synthetic fixture: `{str(synthetic).lower()}`",
        f"- Strategies: `{len(evaluations)}`",
        "- Costs: `none assumed or deducted`; turnover and break-even cost are diagnostics only.",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- `{item.kind}`: {item.statement}" for item in protocol.limitations)
    lines.extend(["", "## Sources", ""])
    lines.extend(
        f"- `{fact.kind}`: `{fact.content_hash}`; {fact.coverage_start.isoformat()} to {fact.coverage_end_exclusive.isoformat()}"
        for fact in protocol.source_facts
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_artifact_package(
    *,
    protocol: DiscoveryProtocol,
    evaluations: Sequence[StrategyEvaluation],
    ranking: RankingReport,
    synthetic: bool,
) -> ArtifactPackage:
    """Build all canonical artifact bytes without touching the filesystem."""
    if not isinstance(synthetic, bool):
        raise ArtifactViolation("synthetic must be a bool")
    values = _validate_evaluations(protocol, evaluations, ranking)
    logical_payload = {
        "schema_version": _SCHEMA_VERSION,
        "protocol": protocol,
        "evaluations": values,
        "ranking": ranking,
        "synthetic": synthetic,
    }
    identity = identity_hash(_ARTIFACT_DOMAIN, _canonical_value(logical_payload))
    source_hashes = {fact.kind: fact.content_hash for fact in protocol.source_facts}
    files: dict[str, bytes] = {
        "protocol.json": _json(
            {
                "identity": protocol.identity,
                "input_manifest_identity": protocol.input_manifest_identity,
                "record": protocol,
            }
        ),
        "ranking.json": _json({"artifact_identity": identity, "record": ranking}),
        "candidates.jsonl": _jsonl(
            [_record(candidate, candidate.identity) for value in values for candidate in value.candidates]
        ),
        "events.jsonl": _jsonl(
            [_record(event, event.event_hash) for value in values for event in value.simulation.events]
        ),
        "orders.jsonl": _jsonl(
            [_record(order, order.identity) for value in values for order in value.simulation.orders]
        ),
        "trades.jsonl": _jsonl(
            [_record(trade, trade.identity) for value in values for trade in value.simulation.trades]
        ),
        "equity.jsonl": _jsonl(
            [_record(record, record.identity) for value in values for record in value.simulation.equity]
        ),
        "metrics.jsonl": _jsonl(
            [_record(value.metrics, value.strategy.identity) for value in values]
        ),
        "report.md": _report_markdown(protocol, values, identity, synthetic),
    }
    for value in values:
        files[f"strategies/{value.strategy.identity}.json"] = _json(
            {
                "strategy_identity": value.strategy.identity,
                "geometry_program_identity": value.geometry_program.identity,
                "strategy": value.strategy,
                "geometry_program": value.geometry_program,
                "geometries": value.geometries,
            }
        )
    content_hashes = {name: sha256_hex(content) for name, content in sorted(files.items())}
    record_counts = {
        "strategies": len(values),
        "candidates": sum(len(value.candidates) for value in values),
        "events": sum(len(value.simulation.events) for value in values),
        "orders": sum(len(value.simulation.orders) for value in values),
        "trades": sum(len(value.simulation.trades) for value in values),
        "equity": sum(len(value.simulation.equity) for value in values),
        "metrics": len(values),
    }
    files["manifest.json"] = _json(
        {
            "schema_version": _SCHEMA_VERSION,
            "artifact_identity": identity,
            "synthetic_fixture": synthetic,
            "evidence_label": protocol.evidence_label,
            "screening_label": "historical_screening_current_roster",
            "protocol_identity": protocol.identity,
            "candidate_grammar_identity": protocol.candidate_grammar.identity,
            "input_manifest_identity": protocol.input_manifest_identity,
            "charter_identity": protocol.charter.identity,
            "source_hashes": source_hashes,
            "source_count": len(protocol.source_facts),
            "limitation_count": len(protocol.limitations),
            "limitations": protocol.limitations,
            "strategy_identities": tuple(value.strategy.identity for value in values),
            "record_counts": record_counts,
            "content_hashes": content_hashes,
        }
    )
    return ArtifactPackage(identity=identity, files=files, synthetic=synthetic)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_staged_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _same_tree(path: Path, files: Mapping[str, bytes]) -> bool:
    if not path.is_dir():
        return False
    actual = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual != set(files):
        return False
    return all((path / name).read_bytes() == content for name, content in files.items())


def write_artifact_package(path: Path, package: ArtifactPackage) -> ArtifactWriteResult:
    """Publish a complete package by sibling staging and atomic directory rename."""
    target = Path(path)
    if target.name in {"", "."}:
        raise ArtifactViolation("artifact path must name a directory")
    resolved = target.resolve()
    if package.synthetic and "runs" in resolved.parts:
        raise ArtifactViolation("synthetic artifacts are refused under runs/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _same_tree(target, package.files):
            return ArtifactWriteResult(target, package.identity, created=False)
        raise ArtifactViolation(f"refusing to overwrite unequal artifact {target}")
    stage = target.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        for name, content in sorted(package.files.items()):
            _write_staged_file(stage / name, content)
        for directory in sorted(
            {item.parent for item in stage.rglob("*") if item.is_file()},
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            _fsync_directory(directory)
        _fsync_directory(stage)
        if target.exists():
            if _same_tree(target, package.files):
                return ArtifactWriteResult(target, package.identity, created=False)
            raise ArtifactViolation(f"refusing to overwrite unequal artifact {target}")
        os.replace(stage, target)
        _fsync_directory(target.parent)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return ArtifactWriteResult(target, package.identity, created=True)


def write_artifacts(
    path: Path,
    *,
    protocol: DiscoveryProtocol,
    evaluations: Sequence[StrategyEvaluation],
    ranking: RankingReport,
    synthetic: bool,
) -> ArtifactWriteResult:
    """Build and atomically publish one artifact directory."""
    return write_artifact_package(
        path,
        build_artifact_package(
            protocol=protocol,
            evaluations=evaluations,
            ranking=ranking,
            synthetic=synthetic,
        ),
    )


__all__ = [
    "ArtifactPackage",
    "ArtifactViolation",
    "ArtifactWriteResult",
    "StrategyEvaluation",
    "build_artifact_package",
    "write_artifact_package",
    "write_artifacts",
]
