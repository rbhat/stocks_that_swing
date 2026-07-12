"""StudyStore: the wide-roster layer-1 evidence store.

Mirrors test_store.py's style (real NYSE session dates, injectable fetch).
The store must uphold the same discipline as PriceStore where it matters —
atomic writes, validate-before-write, incomplete bars never cached — while
staying a plain evidence cache (no revision log, no rebuild machinery).

NOTE: the parent's test_study_store.py also covered `stm.jobs.study_refresh`
(a production refresh job) — that module is out of scope for this port (the
exact port list uses scripts/fetch_study_roster.py to populate
cache/study_frames/ instead; see Phase-1 port report). Only the
StudyStore-class tests are ported here; the "Roster config" and
"study_refresh.refresh" sections are dropped along with it.
"""

import datetime as dt

import pandas as pd
import pytest

from sts import calendar as calendar_module
from sts.data.study_store import StudyStore


def make_df(dates, close_scale=1.0):
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="date")
    n = len(idx)
    return pd.DataFrame(
        {
            "open": [100.0 * close_scale + i for i in range(n)],
            "high": [101.0 * close_scale + i for i in range(n)],
            "low": [99.0 * close_scale + i for i in range(n)],
            "close": [100.5 * close_scale + i for i in range(n)],
            "volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


# Real NYSE trading days (same anchors as test_store.py).
D1 = ["2026-06-25", "2026-06-26"]
D_FULL = ["2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"]
LAST_COMPLETED = dt.date(2026, 6, 30)


@pytest.fixture
def store(tmp_path):
    return StudyStore(tmp_path / "study_frames")


@pytest.fixture(autouse=True)
def pin_last_completed(monkeypatch):
    """Pin the calendar so truncation/freshness logic is deterministic."""
    monkeypatch.setattr(
        calendar_module, "last_completed_session", lambda now=None: LAST_COMPLETED
    )


# ---------------------------------------------------------------------------
# StudyStore
# ---------------------------------------------------------------------------

def test_write_then_load_roundtrip(store):
    df = make_df(D1)
    store.write("test", df)
    assert store.symbols() == ["TEST"]
    loaded = store.load("TEST")
    pd.testing.assert_frame_equal(loaded, df)
    assert store.last_date("TEST") == dt.date(2026, 6, 26)


def test_quality_rejection_leaves_store_untouched(store):
    good = make_df(D1)
    store.write("TEST", good)

    bad = make_df(D_FULL)
    bad.loc[bad.index[1], "close"] = -5.0
    with pytest.raises(ValueError, match="TEST"):
        store.write("TEST", bad)

    # Prior good frame intact, and no stray temp files left behind.
    pd.testing.assert_frame_equal(store.load("TEST"), good)
    leftovers = [p for p in store.root.iterdir() if p.suffix != ".parquet"]
    assert leftovers == []


def test_incomplete_bars_truncated_on_write(store, monkeypatch):
    monkeypatch.setattr(
        calendar_module, "last_completed_session", lambda now=None: dt.date(2026, 6, 26)
    )
    store.write("TEST", make_df(D_FULL))
    assert store.last_date("TEST") == dt.date(2026, 6, 26)
    assert len(store.load("TEST")) == 2


def test_load_all_returns_exactly_written_frames(store):
    store.write("AAA", make_df(D1))
    store.write("BBB", make_df(D1, close_scale=2.0))
    frames = store.load_all()
    assert sorted(frames) == ["AAA", "BBB"]
    assert frames["BBB"]["close"].iloc[0] == pytest.approx(201.0)


def test_load_missing_symbol_is_none(store):
    assert store.load("NOPE") is None
    assert store.last_date("NOPE") is None
