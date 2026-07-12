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
