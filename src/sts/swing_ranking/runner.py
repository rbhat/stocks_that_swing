"""End-to-end evaluator for a fully resolved ``swing-ranking-v1`` study."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from sts.swing_ranking.artifacts import (
    ArtifactWriteResult,
    StrategyEvaluation,
    write_artifacts,
)
from sts.swing_ranking.candidates import ScheduledEarnings, generate_candidates
from sts.swing_ranking.config import ConfiguredStudy
from sts.swing_ranking.contracts import Candidate, ContractViolation, EntryGeometry
from sts.swing_ranking.geometry import resolve_geometry
from sts.swing_ranking.metrics import calculate_metrics
from sts.swing_ranking.preflight import PreflightPaths, ResolvedInputs
from sts.swing_ranking.ranking import RankingReport, rank_strategies
from sts.swing_ranking.simulator import DailyBar, simulate


class RunnerViolation(ContractViolation):
    """Resolved inputs cannot be evaluated without ambiguity."""


@dataclass(frozen=True)
class StudyRunResult:
    """The complete in-memory evaluation and its durable publication result."""

    evaluations: tuple[StrategyEvaluation, ...]
    ranking: RankingReport
    artifact: ArtifactWriteResult


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise RunnerViolation(f"{label} cannot be boolean")
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise RunnerViolation(f"{label} must be finite")
    return result


def _load_frames(
    resolved: ResolvedInputs,
    paths: PreflightPaths,
) -> tuple[Mapping[str, pd.DataFrame], Mapping[str, tuple[DailyBar, ...]]]:
    files = {
        item.stem.upper(): item
        for item in paths.parquet_root.iterdir()
        if item.is_file() and item.suffix == ".parquet"
    }
    frames: dict[str, pd.DataFrame] = {}
    bars: dict[str, tuple[DailyBar, ...]] = {}
    for parquet in resolved.parquets:
        path = files.get(parquet.symbol)
        if path is None:
            raise RunnerViolation(
                f"preflight-resolved parquet disappeared for {parquet.symbol}"
            )
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != parquet.file_sha256:
            raise RunnerViolation(
                f"preflight-resolved parquet changed for {parquet.symbol}"
            )
        frame = pd.read_parquet(path)
        frames[parquet.permanent_id] = frame
        bars[parquet.permanent_id] = tuple(
            DailyBar(
                session=session.date(),
                open=_decimal(row.open, f"{parquet.symbol} open"),
                high=_decimal(row.high, f"{parquet.symbol} high"),
                low=_decimal(row.low, f"{parquet.symbol} low"),
                close=_decimal(row.close, f"{parquet.symbol} close"),
            )
            for session, row in frame.iterrows()
        )
    return frames, bars


def evaluate_study(
    *,
    study: ConfiguredStudy,
    resolved: ResolvedInputs,
    paths: PreflightPaths,
    output: Path,
) -> StudyRunResult:
    """Evaluate and atomically publish one real-cache study.

    Callers must invoke the read-only preflight first. This function performs
    no downloads and has no synthetic or alternate simulator path.
    """
    if not isinstance(study, ConfiguredStudy):
        raise RunnerViolation("study must be a ConfiguredStudy")
    if not isinstance(resolved, ResolvedInputs):
        raise RunnerViolation("resolved must be ResolvedInputs")
    if not isinstance(paths, PreflightPaths):
        raise RunnerViolation("paths must be PreflightPaths")
    if resolved.protocol_identity != study.protocol.identity:
        raise RunnerViolation("resolved inputs do not match the configured protocol")

    frames, bars = _load_frames(resolved, paths)
    symbol_by_id = {
        security.permanent_id: security.symbol for security in resolved.securities
    }
    earnings_by_id: defaultdict[str, list[ScheduledEarnings]] = defaultdict(list)
    for event in resolved.earnings_events:
        earnings_by_id[event.permanent_id].append(
            ScheduledEarnings(event.earnings_session, event.known_session)
        )
    facts_as_of = {fact.kind: fact.as_of for fact in resolved.source_facts}
    evaluations: list[StrategyEvaluation] = []

    for configured in study.strategies:
        generated: list[Candidate] = []
        for permanent_id in sorted(frames):
            generated.extend(
                generate_candidates(
                    frame=frames[permanent_id],
                    permanent_id=permanent_id,
                    symbol=symbol_by_id[permanent_id],
                    protocol=study.protocol,
                    strategy=configured.strategy,
                    program=configured.program,
                    geometry_fact_names=configured.geometry_spec.signal_fact_names,
                    facts_as_of=facts_as_of,
                    scheduled_earnings=tuple(earnings_by_id[permanent_id]),
                )
            )
        candidates = tuple(
            sorted(
                (
                    candidate
                    for candidate in generated
                    if study.window.start
                    <= candidate.signal_session
                    < study.window.end_exclusive
                    and candidate.entry_session < study.window.end_exclusive
                ),
                key=lambda item: item.identity,
            )
        )
        geometries: dict[str, EntryGeometry] = {}
        bar_by_session = {
            permanent_id: {bar.session: bar for bar in values}
            for permanent_id, values in bars.items()
        }
        for candidate in candidates:
            entry_bar = bar_by_session.get(candidate.permanent_id, {}).get(
                candidate.entry_session
            )
            if entry_bar is None:
                continue
            try:
                geometry = resolve_geometry(
                    candidate=candidate,
                    entry_price=entry_bar.open,
                    spec=configured.geometry_spec,
                    charter=study.protocol.charter,
                )
            except ContractViolation:
                continue
            geometries[candidate.identity] = geometry
        simulation = simulate(
            protocol=study.protocol,
            strategy=configured.strategy,
            geometry_program=configured.geometry_program,
            candidates=candidates,
            geometries_by_candidate_identity=geometries,
            bars_by_permanent_id=bars,
            priority_direction=configured.program.priority_direction,
        )
        metrics = calculate_metrics(
            strategy_revision_identity=configured.strategy.identity,
            result=simulation,
            candidates=candidates,
            starting_capital=study.protocol.charter.starting_capital,
        )
        evaluations.append(
            StrategyEvaluation(
                strategy=configured.strategy,
                geometry_program=configured.geometry_program,
                geometries=tuple(
                    geometries[identity] for identity in sorted(geometries)
                ),
                candidates=candidates,
                simulation=simulation,
                metrics=metrics,
            )
        )

    values = tuple(evaluations)
    ranking = rank_strategies(tuple(item.metrics for item in values))
    artifact = write_artifacts(
        Path(output),
        protocol=study.protocol,
        evaluations=values,
        ranking=ranking,
        synthetic=False,
    )
    return StudyRunResult(values, ranking, artifact)


__all__ = [
    "RunnerViolation",
    "StudyRunResult",
    "evaluate_study",
]
