from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "run_swing_ranking.py"
_SPEC = importlib.util.spec_from_file_location("run_swing_ranking", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
run_swing_ranking = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_swing_ranking)


def test_dry_run_requires_source_and_never_executes(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit):
        run_swing_ranking.run(["--dry-run"])
    calls: list[str] = []
    assert run_swing_ranking.run(
        ["--synthetic-fixture", "--dry-run", "--output", str(tmp_path / "fixture")],
        preflight_runner=lambda source: calls.append(source) or {"identity": "fixture"},
        execution_runner=lambda *_: pytest.fail("dry run must not execute"),
    ) == 0
    assert calls == ["synthetic_fixture"]
    assert not (tmp_path / "fixture").exists()
    assert "no output writes" in capsys.readouterr().out


def test_execution_needs_separate_explicit_flag(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit):
        run_swing_ranking.run(["--real-cache", "--output", str(tmp_path / "artifact")])
    assert "execution is disabled" in capsys.readouterr().err


def test_public_synthetic_mode_fails_closed_without_injected_fixture() -> None:
    with pytest.raises(SystemExit):
        run_swing_ranking.run(["--synthetic-fixture", "--dry-run"])
