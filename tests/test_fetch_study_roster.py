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
