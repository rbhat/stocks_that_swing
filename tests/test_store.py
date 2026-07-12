import datetime as dt
import json
import os

import pandas as pd
import pytest

from sts.data.store import PriceStore
from sts.data import store as store_module


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


# Sessions: 2026-06-25, 06-26, 06-29, 06-30 are real NYSE trading days.
D1 = ["2026-06-25", "2026-06-26"]
D2 = ["2026-06-26", "2026-06-29", "2026-06-30"]
NOW = dt.datetime(2026, 6, 30, 20, 0, tzinfo=dt.timezone.utc)  # after 06-30 close


@pytest.fixture
def store(tmp_path):
    return PriceStore(tmp_path / "ohlcv")


def test_create_then_gap_fill(store):
    assert store.update("TEST", lambda s, start: make_df(D1), NOW) == "created"
    full = make_df(D1 + ["2026-06-29", "2026-06-30"])

    def fetch(s, start):
        assert start == dt.date(2026, 6, 26)  # refetch from last cached bar
        return full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "updated"
    assert store.last_date("TEST") == dt.date(2026, 6, 30)
    assert len(store.load("TEST")) == 4


def test_idempotent_second_run_is_noop(store):
    full = make_df(D1 + ["2026-06-29", "2026-06-30"])
    store.update("TEST", lambda s, start: full, NOW)
    calls = []

    def fetch(s, start):
        calls.append(s)
        return full

    assert store.update("TEST", fetch, NOW) == "current"
    assert calls == []  # up-to-date symbol is skipped entirely
    assert store.load("TEST").equals(full)


def test_atomic_write_preserves_original_on_crash(store, monkeypatch):
    good = make_df(D1)
    store.update("TEST", lambda s, start: good, NOW)

    def boom(self, path, *a, **k):
        with open(path, "w") as f:
            f.write("partial garbage")
        raise RuntimeError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(RuntimeError):
        store._atomic_write("TEST", make_df(D2))

    monkeypatch.undo()
    assert store.load("TEST").equals(good)  # original intact, no temp junk
    assert list(store.root.glob("*.tmp")) == []


def test_split_readjustment_triggers_rebuild(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)
    rebuilt = make_df(D1 + ["2026-06-29", "2026-06-30"], close_scale=0.5)  # 2:1 split re-adjusts history

    def fetch(s, start):
        return rebuilt if start is None else rebuilt.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "rebuilt"
    assert store.load("TEST").equals(rebuilt)


def test_missing_overlap_bar_triggers_rebuild(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # last cached: 06-26
    full = make_df(D1 + ["2026-06-29", "2026-06-30"])

    def fetch(s, start):
        if start is None:
            return full
        return full.loc["2026-06-29":]  # skips the 06-26 overlap bar

    assert store.update("TEST", fetch, NOW) == "rebuilt"
    assert store.load("TEST").equals(full)


def test_tiny_overlap_diff_merges_without_rebuild(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # 06-26 close = 101.5
    full = make_df(D1 + ["2026-06-29", "2026-06-30"]).copy()
    full.loc["2026-06-26", "close"] *= 1.0005  # < 0.1% drift, e.g. rounding

    def fetch(s, start):
        return full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "updated"
    assert store.load("TEST").index[-1].date() == dt.date(2026, 6, 30)


def test_dividend_sized_overlap_diff_triggers_rebuild(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # 06-26 close = 101.5
    full = make_df(D1 + ["2026-06-29", "2026-06-30"]).copy()
    full["close"] *= 1.002  # ~0.2% ex-div re-adjustment, just over the 0.1% cutoff

    def fetch(s, start):
        return full if start is None else full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "rebuilt"
    assert store.load("TEST").equals(full)


def test_incomplete_bar_after_now_is_not_stored(store):
    full = make_df(D1 + ["2026-06-29", "2026-06-30", "2026-07-01"])  # 07-01 close is after NOW

    assert store.update("TEST", lambda s, start: full, NOW) == "created"
    stored = store.load("TEST")
    assert stored.index[-1].date() == dt.date(2026, 6, 30)
    assert dt.date(2026, 7, 1) not in stored.index.date


def test_rejected_validate_does_not_write(store):
    good = make_df(D1)
    store.update("TEST", lambda s, start: good, NOW)

    class Rejected:
        ok = False
        errors = ["bad data"]

    def validate(symbol, df):
        return Rejected()

    full = make_df(D1 + ["2026-06-29", "2026-06-30"])
    result = store.update("TEST", lambda s, start: full, NOW, validate=validate)
    assert result == "rejected: bad data"
    assert store.load("TEST").equals(good)  # untouched


def read_revisions(store):
    path = store.root / "revisions.jsonl"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_tiny_overlap_diff_logs_absorbed_revision(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # 06-26 close = 101.5
    full = make_df(D1 + ["2026-06-29", "2026-06-30"]).copy()
    full.loc["2026-06-26", "close"] *= 1.0005  # < 0.1% drift, e.g. rounding

    def fetch(s, start):
        return full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "updated"

    revisions = read_revisions(store)
    assert len(revisions) == 1
    rec = revisions[0]
    assert rec["symbol"] == "TEST"
    assert rec["session"] == "2026-06-26"
    assert rec["action"] == "absorbed"
    assert rec["old"]["close"] == pytest.approx(101.5)
    assert rec["new"]["close"] == pytest.approx(101.5 * 1.0005)
    assert rec["close_rel_diff"] == pytest.approx(0.0005, rel=1e-3)
    assert "detected_at" in rec


def test_dividend_sized_overlap_diff_logs_rebuilt_revision(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # 06-26 close = 101.5
    full = make_df(D1 + ["2026-06-29", "2026-06-30"]).copy()
    full["close"] *= 1.002  # ~0.2% ex-div re-adjustment, just over the 0.1% cutoff

    def fetch(s, start):
        return full if start is None else full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "rebuilt"

    revisions = read_revisions(store)
    assert len(revisions) == 1
    rec = revisions[0]
    assert rec["action"] == "rebuilt"
    assert rec["session"] == "2026-06-26"
    assert rec["old"]["close"] == pytest.approx(101.5)
    assert rec["new"]["close"] == pytest.approx(101.5 * 1.002)


def test_missing_overlap_bar_logs_rebuilt_revision_with_null_new(store):
    store.update("TEST", lambda s, start: make_df(D1), NOW)  # last cached: 06-26
    full = make_df(D1 + ["2026-06-29", "2026-06-30"])

    def fetch(s, start):
        if start is None:
            return full
        return full.loc["2026-06-29":]  # skips the 06-26 overlap bar

    assert store.update("TEST", fetch, NOW) == "rebuilt"

    revisions = read_revisions(store)
    assert len(revisions) == 1
    rec = revisions[0]
    assert rec["action"] == "rebuilt"
    assert rec["session"] == "2026-06-26"
    assert rec["new"] is None
    assert rec["old"]["close"] == pytest.approx(101.5)


def test_identical_overlap_bar_logs_no_revision(store):
    full = make_df(D1 + ["2026-06-29", "2026-06-30"])
    store.update("TEST", lambda s, start: make_df(D1), NOW)

    def fetch(s, start):
        return full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "updated"
    assert read_revisions(store) == []


def test_unwritable_revisions_path_does_not_break_update(store, monkeypatch):
    store.update("TEST", lambda s, start: make_df(D1), NOW)
    full = make_df(D1 + ["2026-06-29", "2026-06-30"]).copy()
    full.loc["2026-06-26", "close"] *= 1.0005  # triggers a revision log attempt

    real_open = os.open

    def flaky_open(path, *args, **kwargs):
        if "revisions.jsonl" in str(path):
            raise OSError("disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "open", flaky_open)

    def fetch(s, start):
        return full.loc[start.isoformat():]

    assert store.update("TEST", fetch, NOW) == "updated"
    assert store.load("TEST").index[-1].date() == dt.date(2026, 6, 30)
    assert not (store.root / "revisions.jsonl").exists()
