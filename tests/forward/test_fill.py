import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import forward_fill  # noqa: E402

from sts import risk  # noqa: E402
from sts.forward.ledger import Ledger, LedgerPaths, entry_id  # noqa: E402


class FakeStore:
    """Minimal StudyStore stand-in: .load(symbol) -> df or None."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol):
        return self._frames.get(symbol)


def bar_frame(date: dt.date, open_: float, close: float = None):
    close = close if close is not None else open_
    idx = pd.DatetimeIndex([pd.Timestamp(date)], name="date")
    return pd.DataFrame(
        {"open": [open_], "high": [open_ + 1], "low": [open_ - 1], "close": [close], "volume": [1_000_000]},
        index=idx,
    )


def candidate_signal(asof: dt.date, signal_date: dt.date, symbol="AAA", book="shared",
                      family="h1", qty=10, atr_sig=2.0, close_sig=100.0):
    eid = entry_id(book, family, symbol, signal_date)
    return {
        "kind": "candidate",
        "book": book,
        "family": family,
        "entry_id": eid,
        "signal_date": signal_date.isoformat(),
        "ticker": symbol,
        "qty": qty,
        "entry_price_range": [close_sig - 0.5, close_sig + 0.5],
        "sl": risk.atr_stop(close_sig, atr_sig, 2.0),
        "tp1": risk.atr_target(close_sig, atr_sig, 2.0),
        "atr_sig": atr_sig,
        "close_sig": close_sig,
        "config_name": "trend_pullback",
    }


@pytest.fixture
def ledger(tmp_path):
    return Ledger(LedgerPaths(root=tmp_path / "ledger"))


def _entry_session_for(signal_date: dt.date) -> dt.date:
    return forward_fill._entry_session(signal_date)


def _setup(monkeypatch, ledger, tmp_path, signal_date, open_price=101.0, no_discord=True):
    entry_session = _entry_session_for(signal_date)
    cand = candidate_signal(entry_session, signal_date)
    ledger.append_signal(cand)

    store = FakeStore({"AAA": bar_frame(entry_session, open_price)})
    monkeypatch.setattr(forward_fill, "StudyStore", lambda: store)
    monkeypatch.setattr(forward_fill, "_sleep", lambda s: (_ for _ in ()).throw(
        AssertionError("should not need to sleep: open is available")
    ))

    argv = ["--asof", entry_session.isoformat(), "--ledger-root", str(tmp_path / "ledger")]
    if no_discord:
        argv.append("--no-discord")
    return cand, entry_session, argv


def test_fill_opens_row_and_reanchors_stop_target(tmp_path, monkeypatch, ledger):
    signal_date = dt.date(2024, 1, 2)  # a Tuesday
    cand, entry_session, argv = _setup(monkeypatch, ledger, tmp_path, signal_date, open_price=101.0)

    rc = forward_fill.run(argv)
    assert rc == 0

    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    state = ledger2.state()
    assert cand["entry_id"] in state
    row = state[cand["entry_id"]]
    assert row["status"] == "open"
    assert row["entry_fill"] == 101.0
    assert row["entry_ref"] == 101.0
    assert row["sl"] == pytest.approx(risk.atr_stop(101.0, cand["atr_sig"], 2.0))
    assert row["tp1"] == pytest.approx(risk.atr_target(101.0, cand["atr_sig"], 2.0))
    # fees_total is the entry-side cost only at open time.
    from sts.forward.broker import cost_side
    assert row["fees_total"] == pytest.approx(cost_side(101.0, row["qty"]))


def test_fill_idempotent_on_second_run(tmp_path, monkeypatch, ledger):
    signal_date = dt.date(2024, 1, 2)
    cand, entry_session, argv = _setup(monkeypatch, ledger, tmp_path, signal_date, open_price=101.0)

    rc1 = forward_fill.run(argv)
    assert rc1 == 0

    # Second run must not call get_open again / re-fill: fail loudly if it
    # tries to hit the (fake) store beyond the idempotency check.
    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    before = dict(ledger2.state())

    rc2 = forward_fill.run(argv)
    assert rc2 == 0

    ledger3 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    after = ledger3.state()
    assert after.keys() == before.keys()
    assert after[cand["entry_id"]]["seq"] == before[cand["entry_id"]]["seq"]


def test_fill_unavailable_open_defers_candidate(tmp_path, monkeypatch, ledger):
    signal_date = dt.date(2024, 1, 2)
    entry_session = _entry_session_for(signal_date)
    cand = candidate_signal(entry_session, signal_date)
    ledger.append_signal(cand)

    store = FakeStore({})  # no bar at all -> get_open always None
    monkeypatch.setattr(forward_fill, "StudyStore", lambda: store)
    monkeypatch.setattr(forward_fill, "fetch_daily", lambda *a, **k: pd.DataFrame())

    sleeps: list[float] = []
    monkeypatch.setattr(forward_fill, "_sleep", lambda s: sleeps.append(s))

    argv = [
        "--asof", entry_session.isoformat(),
        "--ledger-root", str(tmp_path / "ledger"),
        "--no-discord",
        "--max-wait-min", "0.1",  # 1 poll interval budget -> minimal test time
    ]
    rc = forward_fill.run(argv)
    assert rc == 0

    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    assert cand["entry_id"] not in ledger2.state()


def test_fill_skips_when_book_blocked(tmp_path, monkeypatch, ledger):
    """A symbol already held in the book at fill time -> dup_symbol skip,
    no open row appended."""
    signal_date = dt.date(2024, 1, 2)
    entry_session = _entry_session_for(signal_date)
    cand = candidate_signal(entry_session, signal_date, symbol="AAA", book="shared", family="h1")
    ledger.append_signal(cand)

    # Pre-existing open row for the same symbol in the same book.
    existing = {
        "entry_id": entry_id("shared", "h2", "AAA", signal_date - dt.timedelta(days=1)),
        "family": "h2",
        "source": "local-shared",
        "book": "shared",
        "ticker": "AAA",
        "signal_date": signal_date - dt.timedelta(days=1),
        "timestamp": dt.datetime.combine(signal_date, dt.time(13, 30), tzinfo=dt.UTC),
        "qty": 5,
        "entry_ref": 100.0,
        "entry_fill": 100.0,
        "entry_price_range": [99.0, 101.0],
        "stop_initial": 95.0,
        "sl": 95.0,
        "tp1": 110.0,
        "tp2": None,
        "status": "open",
        "usd_deployed": 500.0,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": 1.0,
        "pnl_usd": None,
        "r_net": None,
    }
    ledger.append_row(existing)

    store = FakeStore({"AAA": bar_frame(entry_session, 101.0)})
    monkeypatch.setattr(forward_fill, "StudyStore", lambda: store)

    argv = ["--asof", entry_session.isoformat(), "--ledger-root", str(tmp_path / "ledger"), "--no-discord"]
    rc = forward_fill.run(argv)
    assert rc == 0

    ledger2 = Ledger(LedgerPaths(root=tmp_path / "ledger"))
    assert cand["entry_id"] not in ledger2.state()
    skips = [r for r in ledger2.signals() if r.get("kind") == "skip" and r["entry_id"] == cand["entry_id"]]
    assert len(skips) == 1
    assert skips[0]["reason"] == "dup_symbol"


def test_fill_refuses_on_non_session(tmp_path, monkeypatch, ledger):
    non_session = dt.date(2024, 1, 6)  # Saturday
    argv = ["--asof", non_session.isoformat(), "--ledger-root", str(tmp_path / "ledger"), "--no-discord"]
    monkeypatch.setattr(forward_fill, "StudyStore", lambda: (_ for _ in ()).throw(
        AssertionError("must not touch the store on a non-session")
    ))
    rc = forward_fill.run(argv)
    assert rc == 0
