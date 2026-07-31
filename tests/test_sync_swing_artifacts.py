from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sts.swing_ranking.identity import sha256_hex


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "sync_swing_artifacts.py"
    spec = importlib.util.spec_from_file_location("sync_swing_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drive_folder_ids_are_separate_and_frozen():
    script = _load_script()
    assert script.FORWARD_FOLDER_ID == "1VHPM0pz_BW-48tR6vs9PFJmPJ1YGy87R"
    assert script.BACKTEST_FOLDER_ID == "1sQ6LdAmvsD2-nH9kBO-s9nJrsMChHwBy"
    assert script.FORWARD_FOLDER_ID != script.BACKTEST_FOLDER_ID


def test_verify_forward_checks_top_level_and_session_hashes(tmp_path: Path):
    script = _load_script()
    run = tmp_path / "forward"
    session = run / "sessions" / "2026-08-03"
    session.mkdir(parents=True)
    (run / "state.json").write_text("{}\n", encoding="utf-8")
    (session / "source.json").write_text("{}\n", encoding="utf-8")
    (run / "manifest.json").write_text(
        json.dumps(
            {"content_hashes": {"state.json": sha256_hex(b"{}\n")}}
        ),
        encoding="utf-8",
    )
    (session / "manifest.json").write_text(
        json.dumps(
            {"content_hashes": {"source.json": sha256_hex(b"{}\n")}}
        ),
        encoding="utf-8",
    )

    script.verify_forward(run)
    (session / "source.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        script.verify_forward(run)
