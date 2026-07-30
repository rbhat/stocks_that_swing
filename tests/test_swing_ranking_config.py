from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from sts import calendar
from sts.swing_ranking.config import ConfigurationViolation, load_study_bundle
from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_LIMITATION_KINDS,
    REQUIRED_SOURCE_KINDS,
)
from sts.swing_ranking.preflight import (
    PreflightPaths,
    ResolvedInputs,
    ResolvedParquet,
    ResolvedSecurity,
)
from sts.swing_ranking.runner import RunnerViolation, evaluate_study
from sts.swing_ranking.split import (
    derive_evaluation_split,
    evaluation_split_document,
)


def _bundle() -> dict[str, object]:
    evaluation_start = dt.date(2024, 1, 2)
    evaluation_end = dt.date(2024, 8, 31)
    return {
        "evidence_window": "development",
        "protocol": {
            "study_id": "swing-ranking-v1",
            "protocol_version": "fixture-v1",
            "evidence_label": "retrospective_screening",
            "evaluation_start": evaluation_start.isoformat(),
            "evaluation_end_exclusive": evaluation_end.isoformat(),
            "data_cutoff": "2024-08-30",
            "prospective_wall": "2024-09-03",
            "evaluation_split": evaluation_split_document(
                derive_evaluation_split(evaluation_start, evaluation_end)
            ),
            "grammar_version": "fixture-v1",
            "charter": {
                "starting_capital": "100000",
                "risk_fraction": "0.0075",
                "maximum_notional_fraction": "0.15",
                "maximum_positions": 8,
                "maximum_deployed_fraction": "0.80",
                "minimum_price": "5",
                "minimum_average_dollar_volume": "20000000",
                "maximum_stop_fraction": "0.12",
                "minimum_planned_reward_risk": "1.5",
                "minimum_hold_sessions": 3,
                "maximum_hold_sessions": 21,
                "earnings_blackout_sessions": 2,
                "long_only": True,
                "paper_only": True,
            },
            "source_facts": [
                {
                    "kind": kind,
                    "content_hash": "a" * 64,
                    "as_of": "2024-08-30",
                    "coverage_start": evaluation_start.isoformat(),
                    "coverage_end_exclusive": evaluation_end.isoformat(),
                    "adjustment_basis": ADJUSTMENT_BASIS,
                }
                for kind in REQUIRED_SOURCE_KINDS
            ],
            "limitations": [
                {"kind": kind, "statement": f"{kind} fixture limitation"}
                for kind in REQUIRED_LIMITATION_KINDS
            ],
        },
        "strategies": [
            {
                "name": "weekly trend",
                "revision": "r1",
                "readable_rules": [
                    "weekly close is positive",
                    "daily close is positive",
                    "stop one ATR below entry; target two risks above entry",
                ],
                "program": {
                    "version": "v1",
                    "features": [
                        {
                            "name": "weekly_close",
                            "timeframe": "weekly",
                            "operation": "raw",
                            "source": "close",
                            "lookback": 1,
                        },
                        {
                            "name": "daily_close",
                            "timeframe": "daily",
                            "operation": "raw",
                            "source": "close",
                            "lookback": 1,
                        },
                        {
                            "name": "daily_atr",
                            "timeframe": "daily",
                            "operation": "atr",
                            "source": "close",
                            "lookback": 2,
                        },
                    ],
                    "where": [
                        {
                            "left": "weekly_close",
                            "comparator": "gt",
                            "right_feature": None,
                            "right_threshold": "0",
                        }
                    ],
                    "when": [
                        {
                            "left": "daily_close",
                            "comparator": "gt",
                            "right_feature": None,
                            "right_threshold": "0",
                        }
                    ],
                    "priority_feature": "daily_close",
                    "priority_direction": "descending",
                    "average_dollar_volume_lookback": 2,
                },
                "geometry": {
                    "version": "v1",
                    "stop": {
                        "kind": "entry_minus_fact_multiple",
                        "primary_fact": "daily_atr",
                        "secondary_fact": None,
                        "multiple": "1",
                    },
                    "target": {
                        "kind": "entry_plus_risk_multiple",
                        "primary_fact": None,
                        "secondary_fact": None,
                        "multiple": "2",
                    },
                    "hold_sessions": 21,
                },
            }
        ],
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_load_study_bundle_binds_program_geometry_and_protocol(tmp_path: Path) -> None:
    path = tmp_path / "study.json"
    _write(path, _bundle())
    study = load_study_bundle(path)
    configured = study.strategies[0]
    configured.strategy.validate_against(study.protocol)
    configured.geometry_program.validate_against(configured.strategy)
    assert configured.strategy.geometry_spec_identity == configured.geometry_spec.identity
    assert study.evidence_window == "development"
    assert study.window == study.protocol.evaluation_split.development
    assert configured.geometry_spec.identity in study.protocol.candidate_grammar.definition[
        "geometry_spec_identities"
    ]


def test_load_study_bundle_rejects_json_float(tmp_path: Path) -> None:
    value = _bundle()
    value["protocol"]["charter"]["starting_capital"] = 100000.0
    path = tmp_path / "study.json"
    _write(path, value)
    with pytest.raises(ConfigurationViolation, match="not canonical"):
        load_study_bundle(path)


def test_configured_study_reaches_artifact_implementation_boundary(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "study.json"
    _write(bundle, _bundle())
    study = load_study_bundle(bundle)
    sessions = calendar.sessions_between(
        study.protocol.evaluation_start,
        study.protocol.data_cutoff,
    )
    prehistory_session = calendar.nyse().previous_session(sessions[0]).tz_localize(None)
    frame_sessions = pd.DatetimeIndex([prehistory_session, *sessions]).tz_localize(
        None
    )
    frame = pd.DataFrame(
        {
            "open": [100.0] * len(frame_sessions),
            "high": [102.0] * len(frame_sessions),
            "low": [98.0] * len(frame_sessions),
            "close": [100.0] * len(frame_sessions),
            "volume": [1_000_000] * len(frame_sessions),
        },
        index=frame_sessions,
    )
    frame.loc[prehistory_session, "high"] = 100.0
    frame.loc[prehistory_session, "close"] = 100.0 + 1e-12
    parquet_root = tmp_path / "parquets"
    parquet_root.mkdir()
    parquet = parquet_root / "AAA.parquet"
    frame.to_parquet(parquet)
    file_hash = hashlib.sha256(parquet.read_bytes()).hexdigest()
    resolved = ResolvedInputs(
        protocol_identity=study.protocol.identity,
        roster_sha256="b" * 64,
        roster_manifest_sha256="c" * 64,
        source_manifest_sha256="d" * 64,
        source_facts=study.protocol.source_facts,
        securities=(ResolvedSecurity("permanent-aaa", "AAA"),),
        parquets=(
            ResolvedParquet(
                "permanent-aaa",
                "AAA",
                file_hash,
                prehistory_session.date(),
                sessions[-1].date(),
                len(frame_sessions),
            ),
        ),
        earnings_events=(),
    )
    paths = PreflightPaths(
        roster=bundle,
        roster_manifest=bundle,
        source_manifest=bundle,
        security_master=bundle,
        symbol_history=bundle,
        corporate_actions=bundle,
        earnings_calendar=bundle,
        exchange_calendar=bundle,
        parquet_root=parquet_root,
    )
    output = tmp_path / "artifact"
    result = evaluate_study(
        study=study,
        resolved=resolved,
        paths=paths,
        output=output,
    )
    assert result.artifact.path == output
    assert result.evaluations[0].metrics.candidate_count > 0
    assert (output / "manifest.json").is_file()
    frame.assign(close=101.0).to_parquet(parquet)
    with pytest.raises(RunnerViolation, match="changed"):
        evaluate_study(
            study=study,
            resolved=resolved,
            paths=paths,
            output=tmp_path / "altered",
        )
