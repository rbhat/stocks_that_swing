from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from sts import calendar
from sts.swing_ranking.artifacts import (
    ArtifactViolation,
    EvidenceSelection,
    StrategyEvaluation,
    build_artifact_package,
    write_artifact_package,
)
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
from sts.swing_ranking.metrics import calculate_metrics
from sts.swing_ranking.ranking import rank_strategies
from sts.swing_ranking.simulator import DailyBar, simulate
from sts.swing_ranking.split import derive_evaluation_split


def _evaluation() -> tuple[DiscoveryProtocol, StrategyEvaluation]:
    sessions = tuple(
        item.date()
        for item in calendar.sessions_between(
            dt.date(2023, 1, 3),
            dt.date(2024, 2, 15),
        )
    )
    bars = sessions[:22]
    protocol = DiscoveryProtocol(
        study_id="swing-ranking-v1",
        protocol_version="artifact-test-v1",
        evidence_label="retrospective_screening",
        evaluation_start=sessions[0],
        evaluation_end_exclusive=dt.date(2024, 2, 15),
        data_cutoff=dt.date(2024, 2, 14),
        prospective_wall=dt.date(2024, 3, 18),
        evaluation_split=derive_evaluation_split(
            sessions[0],
            dt.date(2024, 2, 15),
        ),
        charter=swing_ranking_charter(),
        candidate_grammar=CandidateGrammar("v1", {"fixture": "generic"}),
        source_facts=tuple(
            SourceFact(kind, "a" * 64, dt.date(2024, 2, 14), sessions[0], dt.date(2024, 2, 15), ADJUSTMENT_BASIS)
            for kind in REQUIRED_SOURCE_KINDS
        ),
        limitations=tuple(SourceLimitation(kind, f"{kind} limitation") for kind in REQUIRED_LIMITATION_KINDS),
    )
    strategy = StrategyRevision(
        "swing-ranking-v1", "fixture", "r1", ("where", "when"), {"fixture": "generic"},
        "b" * 64,
        protocol.identity, protocol.candidate_grammar.identity, protocol.input_manifest_identity, protocol.charter.identity,
    )
    candidate = Candidate(
        strategy.identity, protocol.input_manifest_identity, "permanent-1", "AAA", bars[0], bars[1],
        Decimal(100), Decimal(20_000_000), None, None,
        {kind: dt.date(2024, 2, 14) for kind in REQUIRED_SOURCE_KINDS},
        {"close": SignalFact(Decimal(100), bars[0])}, Decimal(1),
    )
    geometry = EntryGeometry(candidate.identity, Decimal(100), Decimal(95), Decimal(108), 21)
    program = GeometryProgram(strategy.identity, strategy.geometry_spec_identity, "fixture geometry", "v1", ("stop and target",), {"fixture": "generic"})
    result = simulate(
        protocol=protocol,
        strategy=strategy,
        geometry_program=program,
        candidates=(candidate,),
        geometries_by_candidate_identity={candidate.identity: geometry},
        bars_by_permanent_id={
            candidate.permanent_id: tuple(DailyBar(session, Decimal(100), Decimal(101), Decimal(99), Decimal(100)) for session in bars)
        },
        priority_direction="descending",
    )
    metrics = calculate_metrics(
        strategy_revision_identity=strategy.identity,
        result=result,
        candidates=(candidate,),
        starting_capital=protocol.charter.starting_capital,
    )
    return protocol, StrategyEvaluation(strategy, program, (geometry,), (candidate,), result, metrics)


def _selection(protocol: DiscoveryProtocol) -> EvidenceSelection:
    window = protocol.evaluation_split.development
    return EvidenceSelection(
        configured_study_identity="c" * 64,
        name="development",
        window_identity=window.sessions_identity,
        start=window.start,
        end_exclusive=window.end_exclusive,
        outcome_end_exclusive=(
            protocol.evaluation_split.development_validation_purge.end_exclusive
        ),
    )


def test_artifact_package_is_canonical_complete_and_idempotently_written(tmp_path: Path) -> None:
    protocol, evaluation = _evaluation()
    ranking = rank_strategies((evaluation.metrics,))
    package = build_artifact_package(
        protocol=protocol,
        selection=_selection(protocol),
        evaluations=(evaluation,),
        ranking=ranking,
        synthetic=True,
    )

    assert {"manifest.json", "protocol.json", "selection.json", "ranking.json", "report.md", "candidates.jsonl", "events.jsonl", "orders.jsonl", "trades.jsonl", "equity.jsonl", "metrics.jsonl"} <= set(package.files)
    manifest = json.loads(package.files["manifest.json"])
    assert manifest["artifact_identity"] == package.identity
    assert set(manifest["source_hashes"]) == set(REQUIRED_SOURCE_KINDS)
    assert "historical_screening_current_roster" == manifest["screening_label"]
    assert manifest["evidence_window"] == "development"
    assert "current_roster_survivorship" in package.files["report.md"].decode()

    path = tmp_path / "artifact"
    assert write_artifact_package(path, package).created
    assert not write_artifact_package(path, package).created
    assert (path / "manifest.json").read_bytes() == package.files["manifest.json"]


def test_artifact_writer_refuses_unequal_and_synthetic_runs_destination(tmp_path: Path) -> None:
    protocol, evaluation = _evaluation()
    package = build_artifact_package(
        protocol=protocol,
        selection=_selection(protocol),
        evaluations=(evaluation,),
        ranking=rank_strategies((evaluation.metrics,)),
        synthetic=True,
    )
    path = tmp_path / "artifact"
    write_artifact_package(path, package)
    (path / "report.md").write_text("changed\n")
    with pytest.raises(ArtifactViolation, match="unequal"):
        write_artifact_package(path, package)
    with pytest.raises(ArtifactViolation, match="refused under runs"):
        write_artifact_package(tmp_path / "runs" / "fixture", package)
