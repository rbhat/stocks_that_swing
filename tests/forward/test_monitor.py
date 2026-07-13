import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import forward_monitor  # noqa: E402

from sts.forward.ledger import Ledger, LedgerPaths, entry_id  # noqa: E402


class FakeStore:
    def load(self, symbol):
        return None


def open_row(entry_id_, symbol, sl, tp1, book="shared", family="h1"):
    return {
        "entry_id": entry_id_,
        "family": family,
        "source": "local-shared" if book == "shared" else "local-h1solo",
        "book": book,
        "ticker": symbol,
        "signal_date": dt.date(2024, 1, 2),
        "timestamp": dt.datetime(2024, 1, 3, 13, 30, tzinfo=dt.UTC),
        "qty": 10,
        "entry_ref": 100.0,
        "entry_fill": 100.0,
        "entry_price_range": [99.0, 101.0],
        "stop_initial": sl,
        "sl": sl,
        "tp1": tp1,
        "tp2": None,
        "status": "open",
        "usd_deployed": 1000.0,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": 1.5,
        "pnl_usd": None,
        "r_net": None,
    }


@pytest.fixture
def ledger(tmp_path):
    return Ledger(LedgerPaths(root=tmp_path / "ledger"))


# RTH so the pre/post move-warning branch is inert (isolates stop/target logic).
_RTH_NOW = dt.datetime(2024, 1, 3, 15, 0, tzinfo=dt.timezone.utc)  # 10am ET


def test_stop_touched_sends_alert_and_journals(tmp_path, monkeypatch, ledger):
    eid = entry_id("shared", "h1", "AAA", dt.date(2024, 1, 2))
    ledger.append_row(open_row(eid, "AAA", sl=95.0, tp1=110.0))

    monkeypatch.setattr(forward_monitor, "StudyStore", lambda: FakeStore())
    monkeypatch.setattr(forward_monitor, "_get_quote", lambda sym: {"last": 94.0, "prev_close": 100.0})

    sent = []
    monkeypatch.setattr(forward_monitor.alerts, "send", lambda text, **k: sent.append(text) or True)

    monkeypatch.setattr(forward_monitor, "_now_utc", lambda: _RTH_NOW)

    argv = ["--asof", "2024-01-03", "--ledger-root", str(tmp_path / "ledger")]
    rc = forward_monitor.run(argv)
    assert rc == 0
    assert len(sent) == 1
    assert "STOP TOUCHED" in sent[0]

    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    journaled = [r for r in ledger2.signals(dt.date(2024, 1, 3)) if r["kind"] == "monitor_alert"]
    assert len(journaled) == 1
    assert journaled[0]["entry_id"] == f"{eid}#stop_touched"


def test_monitor_never_writes_ledger_rows(tmp_path, monkeypatch, ledger):
    eid = entry_id("shared", "h1", "AAA", dt.date(2024, 1, 2))
    ledger.append_row(open_row(eid, "AAA", sl=95.0, tp1=110.0))

    monkeypatch.setattr(forward_monitor, "StudyStore", lambda: FakeStore())
    monkeypatch.setattr(forward_monitor, "_get_quote", lambda sym: {"last": 94.0, "prev_close": 100.0})
    monkeypatch.setattr(forward_monitor.alerts, "send", lambda *a, **k: True)

    monkeypatch.setattr(forward_monitor, "_now_utc", lambda: _RTH_NOW)

    argv = ["--asof", "2024-01-03", "--ledger-root", str(tmp_path / "ledger")]
    forward_monitor.run(argv)

    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    state = ledger2.state()
    # Still exactly the one pre-existing open row; monitor appended nothing
    # to the h1/h2 journals (only to the signals journal).
    assert len(state) == 1
    assert state[eid]["status"] == "open"


def test_second_run_same_day_does_not_realert(tmp_path, monkeypatch, ledger):
    eid = entry_id("shared", "h1", "AAA", dt.date(2024, 1, 2))
    ledger.append_row(open_row(eid, "AAA", sl=95.0, tp1=110.0))

    monkeypatch.setattr(forward_monitor, "StudyStore", lambda: FakeStore())
    monkeypatch.setattr(forward_monitor, "_get_quote", lambda sym: {"last": 94.0, "prev_close": 100.0})

    sent = []
    monkeypatch.setattr(forward_monitor.alerts, "send", lambda text, **k: sent.append(text) or True)

    monkeypatch.setattr(forward_monitor, "_now_utc", lambda: _RTH_NOW)

    argv = ["--asof", "2024-01-03", "--ledger-root", str(tmp_path / "ledger")]
    assert forward_monitor.run(argv) == 0
    assert forward_monitor.run(argv) == 0

    assert len(sent) == 1  # second run: dedupe suppressed the re-alert


def test_no_alert_when_price_between_stop_and_target(tmp_path, monkeypatch, ledger):
    eid = entry_id("shared", "h1", "AAA", dt.date(2024, 1, 2))
    ledger.append_row(open_row(eid, "AAA", sl=95.0, tp1=110.0))

    monkeypatch.setattr(forward_monitor, "StudyStore", lambda: FakeStore())
    monkeypatch.setattr(forward_monitor, "_get_quote", lambda sym: {"last": 101.0, "prev_close": 100.0})

    sent = []
    monkeypatch.setattr(forward_monitor.alerts, "send", lambda text, **k: sent.append(text) or True)

    monkeypatch.setattr(forward_monitor, "_now_utc", lambda: _RTH_NOW)

    argv = ["--asof", "2024-01-03", "--ledger-root", str(tmp_path / "ledger")]
    assert forward_monitor.run(argv) == 0
    assert sent == []


def test_never_writes_ledger_row_helper_uses_open_rows_only(tmp_path, monkeypatch, ledger):
    """No open rows -> no quote calls, clean no-op run."""
    monkeypatch.setattr(forward_monitor, "StudyStore", lambda: FakeStore())
    monkeypatch.setattr(forward_monitor, "_get_quote", lambda sym: (_ for _ in ()).throw(
        AssertionError("no symbols to quote")
    ))
    monkeypatch.setattr(forward_monitor.alerts, "send", lambda *a, **k: True)

    argv = ["--asof", "2024-01-03", "--ledger-root", str(tmp_path / "ledger")]
    assert forward_monitor.run(argv) == 0
