from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from sts.swing_ranking.artifacts import ArtifactViolation
from sts.swing_ranking.config import load_cohort_selected_study
from sts.swing_ranking.forward import advance_forward_run, initialize_forward_run

ROOT = Path(__file__).resolve().parents[1]


def _initialized_run(tmp_path: Path):
    study, selection = load_cohort_selected_study(
        ROOT / "configs/swing_ranking_v1/study_bundle.json",
        ROOT / "configs/swing_ranking_v1/oos_cohort_selection.json",
    )
    seal = tmp_path / "seal"
    seal.mkdir()
    (seal / "seal.json").write_text(
        json.dumps(
            {
                "status": "sealed",
                "selection_identity": selection.identity,
                "forward_eligibility": "unconditional_pre_oos",
                "forward_eligible_cohorts": ["VF9", "MC5"],
                "seal_identity": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    earnings = tmp_path / "earnings.json"
    earnings.write_text("{}\n", encoding="utf-8")
    run = tmp_path / "forward"
    initialize_forward_run(
        study=study,
        selection=selection,
        seal_path=seal,
        upcoming_earnings_snapshot=earnings,
        authorization_date=dt.date(2026, 7, 31),
        output=run,
    )
    return study, selection, run


def test_forward_advance_is_next_session_only_atomic_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study, selection, run = _initialized_run(tmp_path)
    session = dt.date(2026, 8, 3)

    with pytest.raises(ArtifactViolation, match="expected 2026-08-03"):
        advance_forward_run(
            study=study,
            selection=selection,
            output=run,
            session=dt.date(2026, 8, 4),
            parquet_root=tmp_path,
            security_master=tmp_path / "master.json",
            earnings_snapshot=tmp_path / "earnings.json",
            enforce_wall_clock=False,
        )

    monkeypatch.setattr(
        "sts.swing_ranking.forward._load_forward_inputs",
        lambda **_kwargs: (
            {},
            {},
            {},
            {},
            {
                "schema_version": "swing-ranking-v1.forward-source.v1",
                "session": session,
            },
        ),
    )
    monkeypatch.setattr(
        "sts.swing_ranking.forward._read_json",
        _read_json_with_daily_snapshot(session),
    )
    monkeypatch.setattr(
        "sts.swing_ranking.forward.calendar.last_completed_session",
        lambda: session,
    )
    result = advance_forward_run(
        study=study,
        selection=selection,
        output=run,
        session=session,
        parquet_root=tmp_path,
        security_master=tmp_path / "master.json",
        earnings_snapshot=tmp_path / "daily-earnings.json",
    )

    assert result.created
    assert result.candidate_count == 0
    assert result.closed_trade_count == 0
    assert sum(1 for _ in (run / "equity.jsonl").open()) == 9
    assert sum(1 for _ in (run / "events.jsonl").open()) == 9
    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
    assert state["last_processed_session"] == "2026-08-03"
    assert state["next_eligible_signal_session"] == "2026-08-04"
    assert (run / "sessions/2026-08-03/manifest.json").is_file()

    repeated = advance_forward_run(
        study=study,
        selection=selection,
        output=run,
        session=session,
        parquet_root=tmp_path,
        security_master=tmp_path / "master.json",
        earnings_snapshot=tmp_path / "daily-earnings.json",
        enforce_wall_clock=False,
    )
    assert not repeated.created
    assert sum(1 for _ in (run / "equity.jsonl").open()) == 9


def _read_json_with_daily_snapshot(session: dt.date):
    from sts.swing_ranking import forward

    original = forward._read_json

    def read(path: Path):
        if path.name == "daily-earnings.json":
            return {"source": {"snapshot_date": session.isoformat()}}
        return original(path)

    return read
