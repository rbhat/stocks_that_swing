import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import forward_eod  # noqa: E402


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def make_frame(n, start="2024-01-02", price=100.0):
    idx = pd.bdate_range(start, periods=n, name="date")
    rows = [bar(price, price + 1, price - 1, price) for _ in range(n)]
    return pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]


@pytest.fixture
def study_store(tmp_path, monkeypatch):
    root = tmp_path / "study_frames"
    root.mkdir()
    from sts.data.study_store import StudyStore

    df = make_frame(30)
    monkeypatch.setattr(forward_eod, "StudyStore", lambda: StudyStore(root=root))
    store = StudyStore(root=root)
    store.write("AAA", df)
    return store, df


def test_dry_run_no_network_calls(tmp_path, study_store, monkeypatch):
    store, df = study_store
    asof = df.index[-1].date()

    def _boom(*a, **k):
        raise AssertionError("fetch_daily must not be called in --dry-run")

    monkeypatch.setattr(forward_eod, "fetch_daily", _boom)
    monkeypatch.setattr(
        forward_eod, "_roster_symbols", lambda: ["AAA"]
    )
    monkeypatch.setattr(forward_eod.alerts, "send", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Discord must not be called in --dry-run")
    ))

    ledger_root = tmp_path / "ledger"
    rc = forward_eod.run([
        "--dry-run",
        "--asof", asof.isoformat(),
        "--ledger-root", str(ledger_root),
    ])
    assert rc == 0


def test_dry_run_second_invocation_is_noop(tmp_path, study_store, monkeypatch):
    store, df = study_store
    asof = df.index[-1].date()

    monkeypatch.setattr(forward_eod, "fetch_daily", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no network in dry-run")
    ))
    monkeypatch.setattr(forward_eod, "_roster_symbols", lambda: ["AAA"])
    monkeypatch.setattr(forward_eod.alerts, "send", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no discord in dry-run")
    ))

    ledger_root = tmp_path / "ledger"
    argv = ["--dry-run", "--asof", asof.isoformat(), "--ledger-root", str(ledger_root)]

    rc1 = forward_eod.run(argv)
    assert rc1 == 0

    from sts.forward.ledger import Ledger, LedgerPaths
    ledger = Ledger(LedgerPaths(root=ledger_root))
    assert asof in ledger.processed_upkeep_dates()

    rc2 = forward_eod.run(argv)
    assert rc2 == 0
    # second run should be recognized as already-done (no-op path)
    assert forward_eod._already_done(ledger, asof)


def test_empty_queue_night_sends_book_status_and_no_candidates(
    tmp_path, study_store, monkeypatch
):
    """With Discord enabled (fake send injected), an empty-queue night must
    send BOTH the explicit no-candidates message and the book status."""
    store, df = study_store
    asof = df.index[-1].date()

    monkeypatch.setattr(forward_eod, "_roster_symbols", lambda: ["AAA"])
    sent: list[str] = []
    monkeypatch.setattr(forward_eod.alerts, "send", lambda text, **k: sent.append(text) or True)

    rc = forward_eod.run([
        "--no-fetch", "--no-sync",  # Discord NOT suppressed
        "--asof", asof.isoformat(),
        "--ledger-root", str(tmp_path / "ledger"),
    ])
    assert rc == 0
    assert any(f"No candidates for {asof.isoformat()}" in t for t in sent)
    assert any("equity=" in t for t in sent)  # book_status line


def test_noop_second_run_still_invokes_sync(tmp_path, study_store, monkeypatch):
    store, df = study_store
    asof = df.index[-1].date()

    monkeypatch.setattr(forward_eod, "_roster_symbols", lambda: ["AAA"])
    monkeypatch.setattr(forward_eod.alerts, "send", lambda *a, **k: True)

    argv = ["--no-fetch", "--asof", asof.isoformat(),
            "--ledger-root", str(tmp_path / "ledger")]

    sync_calls: list[bool] = []
    monkeypatch.setattr(forward_eod, "_run_sync", lambda do_sync: sync_calls.append(do_sync))

    assert forward_eod.run(argv) == 0
    assert sync_calls == [True]

    # second run hits the already-done path but must still attempt sync
    assert forward_eod.run(argv) == 0
    assert sync_calls == [True, True]
