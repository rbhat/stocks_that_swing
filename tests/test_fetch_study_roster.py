import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import fetch_study_roster as fsr  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402


def _ohlcv(n=320, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1_000_000},
        index=idx,
    )


def test_write_frame_uses_study_store(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr, "STUDY_FRAMES_DIR", tmp_path)
    store = StudyStore(root=tmp_path)
    monkeypatch.setattr(fsr, "_store", lambda: store)

    fsr._write_frame("AAPL", _ohlcv())

    assert "AAPL" in store.symbols()
    df = store.load("AAPL")
    assert df is not None and len(df) > 0


def test_fresh_scratch_symbols_uses_last_completed_session(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr, "STUDY_FRAMES_DIR", tmp_path)
    store = StudyStore(root=tmp_path)
    monkeypatch.setattr(fsr, "_store", lambda: store)

    # last completed session in the frame's timezone-naive index terms
    stale = _ohlcv(n=320, start="2020-01-02")  # ends ~2021
    store.write("STALE", stale)

    import sts.calendar as calendar
    today_bar = _ohlcv(n=1, start=calendar.last_completed_session().isoformat())
    store.write("FRESH", today_bar)

    fresh = fsr._fresh_scratch_symbols()
    assert "FRESH" in fresh
    assert "STALE" not in fresh


def test_write_roster_artifacts_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr, "STUDY_FRAMES_DIR", tmp_path)
    store = StudyStore(root=tmp_path)
    monkeypatch.setattr(fsr, "_store", lambda: store)
    roster_yaml = tmp_path / "study_roster.yaml"
    manifest_json = tmp_path / "study_roster_manifest.json"
    monkeypatch.setattr(fsr, "ROSTER_YAML", roster_yaml)
    monkeypatch.setattr(fsr, "ROSTER_MANIFEST", manifest_json)

    store.write("AAPL", _ohlcv())
    store.write("MSFT", _ohlcv())

    fsr._write_roster_artifacts(seeds=["AAPL"], anchors=["SPY"])

    import yaml, json
    roster = yaml.safe_load(roster_yaml.read_text())
    assert set(roster["symbols"]) == {"AAPL", "MSFT"}
    assert roster["source"] == "cache/scan/constituents.json (S&P 500 + Nasdaq-100)"
    assert "as_of" in roster and "seeds" in roster and "anchors" in roster

    manifest = json.loads(manifest_json.read_text())
    assert set(manifest["symbols"].keys()) == {"AAPL", "MSFT"}
    entry = manifest["symbols"]["AAPL"]
    assert {"first_session", "last_session", "n_bars", "file_sha256"} <= entry.keys()
    assert manifest["adjustment_basis"] == "split+dividend adjusted total return (auto_adjust=True)"


def test_dry_run_noop_does_not_write_artifacts(tmp_path, monkeypatch):
    """--dry-run must be a pure preview: even on the 'target already met' no-op
    path, it must never write study_roster.yaml / study_roster_manifest.json."""
    monkeypatch.setattr(fsr, "STUDY_FRAMES_DIR", tmp_path)
    store = StudyStore(root=tmp_path)
    monkeypatch.setattr(fsr, "_store", lambda: store)

    roster_yaml = tmp_path / "study_roster.yaml"
    manifest_json = tmp_path / "study_roster_manifest.json"
    monkeypatch.setattr(fsr, "ROSTER_YAML", roster_yaml)
    monkeypatch.setattr(fsr, "ROSTER_MANIFEST", manifest_json)

    constituents_json = tmp_path / "constituents.json"
    constituents_json.write_text('{"symbols": ["SPY", "QQQ"]}')
    monkeypatch.setattr(fsr, "CONSTITUENTS", constituents_json)
    monkeypatch.setattr(fsr, "ANCHORS", ["SPY", "QQQ"])
    monkeypatch.setattr(fsr, "_seed_symbols", lambda: [])
    monkeypatch.setattr(fsr, "_load_failures", lambda: set())

    # Pre-populate the store so must_fetch is empty and need_fill == 0
    # (target already met -> the no-op branch).
    store.write("SPY", _ohlcv())
    store.write("QQQ", _ohlcv())

    calls = []
    monkeypatch.setattr(fsr, "_write_roster_artifacts", lambda **kw: calls.append(kw))

    monkeypatch.setattr(
        sys, "argv",
        ["fetch_study_roster.py", "--dry-run", "--target-total", "2"],
    )

    fsr.main()

    assert calls == []
    assert not roster_yaml.exists()
    assert not manifest_json.exists()
