import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import forward_eod


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
    _store, df = study_store
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
    _store, df = study_store
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
    _store, df = study_store
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
    from sts.forward.ledger import Ledger, LedgerPaths

    ledger = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    assert asof in ledger.processed_upkeep_dates()
    assert asof in ledger.processed_signal_dates()
    assert asof in ledger.processed_notification_dates()
    done = next(
        rec for rec in ledger.signals(asof) if rec["kind"] == "notifications_done"
    )
    summary = done["summary"]
    assert summary["market_data"]["counts"] == {
        "fresh": 1,
        "stale": 0,
        "missing": 0,
    }
    assert summary["signal_outcome"] == "selected_zero"
    assert summary["stage_completion"] == {
        "upkeep_done": True,
        "signals_done": True,
        "notifications_done": True,
    }
    assert set(summary["runtime_seconds"]) == {
        "fetch",
        "load",
        "upkeep",
        "signals",
        "notifications",
    }
    assert any("Nightly status" in text for text in sent)


def test_crash_after_signals_done_resumes_notifications_from_ledger(
    tmp_path, study_store, monkeypatch
):
    _store, df = study_store
    asof = df.index[-1].date()
    ledger_root = tmp_path / "ledger"

    monkeypatch.setattr(forward_eod, "_roster_symbols", lambda: ["AAA"])
    sent: list[str] = []
    monkeypatch.setattr(
        forward_eod.alerts,
        "send",
        lambda text, **kwargs: sent.append(text) or True,
    )
    sync_calls: list[bool] = []
    monkeypatch.setattr(
        forward_eod,
        "_run_sync",
        lambda do_sync: sync_calls.append(do_sync),
    )

    real_generate = forward_eod.generate_signals

    def generate_then_crash(*args, **kwargs):
        real_generate(*args, **kwargs)
        raise RuntimeError("injected crash after signals_done")

    monkeypatch.setattr(forward_eod, "generate_signals", generate_then_crash)
    argv = [
        "--no-fetch",
        "--asof",
        asof.isoformat(),
        "--ledger-root",
        str(ledger_root),
    ]
    assert forward_eod.run(argv) == 1

    from sts.forward.ledger import Ledger, LedgerPaths

    ledger = Ledger(LedgerPaths(root=ledger_root))
    assert asof in ledger.processed_signal_dates()
    assert asof not in ledger.processed_notification_dates()

    monkeypatch.setattr(forward_eod, "generate_signals", real_generate)
    assert forward_eod.run(argv) == 0

    ledger = Ledger(LedgerPaths(root=ledger_root))
    assert asof in ledger.processed_notification_dates()
    assert any(f"No candidates for {asof.isoformat()}" in text for text in sent)
    assert any("equity=" in text for text in sent)
    assert sync_calls == [True, True]


def test_notification_marker_is_written_only_after_complete_send_set(tmp_path):
    from sts.forward.ledger import Ledger, LedgerPaths

    asof = dt.date(2024, 3, 15)
    ledger = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    for book in ("shared", "h1solo"):
        ledger.append_equity_snapshot(
            {
                "date": asof,
                "book": book,
                "equity": 100_000.0,
                "cash": 100_000.0,
                "usd_deployed": 0.0,
                "open_count": 0,
            }
        )

    attempted: list[str] = []

    def crash_after_first(message):
        attempted.append(message)
        raise RuntimeError("injected notification crash")

    with pytest.raises(RuntimeError, match="notification crash"):
        forward_eod._send_signal_notifications(ledger, asof, crash_after_first)
    assert asof not in ledger.processed_notification_dates()

    forward_eod._send_signal_notifications(ledger, asof, attempted.append)
    assert asof in ledger.processed_notification_dates()
    assert sum(message.startswith("No candidates") for message in attempted) == 2
    assert sum("equity=" in message for message in attempted) == 1


def test_failed_notification_delivery_leaves_stage_incomplete(tmp_path):
    from sts.forward.ledger import Ledger, LedgerPaths

    asof = dt.date(2024, 3, 15)
    ledger = Ledger(LedgerPaths(root=tmp_path / "ledger"))

    with pytest.raises(RuntimeError, match="delivery failed"):
        forward_eod._send_signal_notifications(
            ledger,
            asof,
            lambda message: False,
        )

    assert asof not in ledger.processed_notification_dates()


def test_zero_streak_warning_is_configurable_and_does_not_create_candidates(
    tmp_path,
):
    from sts.forward.ledger import Ledger, LedgerPaths

    ledger = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    dates = [dt.date(2024, 3, 13), dt.date(2024, 3, 14), dt.date(2024, 3, 15)]
    empty_counts = {
        family: {
            "detected": 0,
            "selected": 0,
            "missing_signal_bar": 0,
            "stale_signal_bar": 0,
            "invalid_geometry": 0,
            "embargoed": 0,
            "queued": 0,
            "skipped_by_reason": {},
        }
        for family in ("h2", "h1")
    }
    for asof in dates:
        ledger.append_signal(
            {
                "kind": "upkeep_done",
                "book": "shared",
                "entry_id": None,
                "signal_date": asof.isoformat(),
                "date": asof.isoformat(),
            }
        )
        ledger.append_signal(
            {
                "kind": "signals_done",
                "book": "shared",
                "entry_id": None,
                "signal_date": asof.isoformat(),
                "date": asof.isoformat(),
                "summary": {"families": empty_counts},
            }
        )

    sent: list[str] = []
    forward_eod._send_signal_notifications(
        ledger,
        dates[-1],
        sent.append,
        zero_streak_warning=3,
    )

    done = next(
        rec
        for rec in ledger.signals(dates[-1])
        if rec["kind"] == "notifications_done"
    )
    assert done["summary"]["consecutive_selected_zero_sessions"] == 3
    assert done["summary"]["health_warning"] is not None
    assert any("WARNING selected=0 for 3" in message for message in sent)
    assert not any(
        rec["kind"] == "candidate" for rec in ledger.signals(dates[-1])
    )


def test_noop_second_run_still_invokes_sync(tmp_path, study_store, monkeypatch):
    _store, df = study_store
    asof = df.index[-1].date()

    monkeypatch.setattr(forward_eod, "_roster_symbols", lambda: ["AAA"])
    monkeypatch.setattr(forward_eod.alerts, "send", lambda *a, **k: True)

    argv = ["--no-fetch", "--asof", asof.isoformat(),
            "--ledger-root", str(tmp_path / "ledger")]

    sync_calls: list[bool] = []
    monkeypatch.setattr(forward_eod, "_run_sync", lambda do_sync: sync_calls.append(do_sync))

    assert forward_eod.run(argv) == 0
    assert sync_calls == [True]
    from sts.forward.ledger import Ledger, LedgerPaths

    ledger = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    assert asof in ledger.processed_upkeep_dates()
    assert asof in ledger.processed_signal_dates()
    assert asof in ledger.processed_notification_dates()
    before = ledger.signals(asof)

    # second run hits the already-done path but must still attempt sync
    assert forward_eod.run(argv) == 0
    assert sync_calls == [True, True]
    assert ledger.signals(asof) == before
