import datetime as dt

import pytest

from sts.forward.ledger import Ledger, LedgerPaths, entry_id


def make_open_row(**overrides):
    row = {
        "entry_id": entry_id("shared", "h1", "NVDA", dt.date(2026, 7, 10)),
        "family": "h1",
        "source": "local-shared",
        "book": "shared",
        "ticker": "NVDA",
        "signal_date": dt.date(2026, 7, 10),
        "timestamp": dt.datetime(2026, 7, 10, 13, 30),
        "qty": 10,
        "entry_ref": 120.0,
        "entry_fill": 120.05,
        "entry_price_range": [119.0, 121.0],
        "stop_initial": 115.0,
        "sl": 115.0,
        "tp1": 130.0,
        "tp2": None,
        "status": "open",
        "usd_deployed": 1200.5,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": 1.6,
        "pnl_usd": None,
        "r_net": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def ledger(tmp_path):
    return Ledger(LedgerPaths(root=tmp_path / "ledger"))


def test_entry_id_format():
    assert entry_id("shared", "h1", "NVDA", dt.date(2026, 7, 10)) == "shared:h1:NVDA:2026-07-10"


def test_append_row_rejects_missing_required_field(ledger):
    row = make_open_row()
    del row["stop_initial"]
    with pytest.raises(ValueError, match="stop_initial"):
        ledger.append_row(row)


def test_append_row_rejects_none_for_required_nonnull_field(ledger):
    row = make_open_row(entry_id=None)
    with pytest.raises(ValueError, match="entry_id"):
        ledger.append_row(row)


def test_closed_row_requires_exit_fields(ledger):
    row = make_open_row(status="closed")
    with pytest.raises(ValueError, match="exit_price"):
        ledger.append_row(row)


def test_append_row_stamps_schema_seq_updated_at(ledger):
    row = make_open_row()
    ledger.append_row(row)
    rows = ledger.open_rows(book="shared")
    assert len(rows) == 1
    r = rows[0]
    assert r["schema_version"] == 1
    assert r["seq"] == 1
    assert "updated_at" in r


def test_seq_auto_increments_per_entry_id(ledger):
    row = make_open_row()
    ledger.append_row(row)
    closed = make_open_row(
        status="closed",
        exit_price=125.0,
        exit_timestamp=dt.datetime(2026, 7, 11, 20, 0),
        exit_reason="target",
        pnl_usd=50.0,
        r_net=1.0,
    )
    ledger.append_row(closed)
    state = ledger.state()
    eid = entry_id("shared", "h1", "NVDA", dt.date(2026, 7, 10))
    assert state[eid]["seq"] == 2
    assert state[eid]["status"] == "closed"


def test_state_returns_latest_version_only(ledger):
    ledger.append_row(make_open_row())
    ledger.append_row(make_open_row(status="closed", exit_price=125.0,
                                     exit_timestamp=dt.datetime(2026, 7, 11, 20, 0),
                                     exit_reason="target", pnl_usd=50.0, r_net=1.0))
    state = ledger.state()
    eid = entry_id("shared", "h1", "NVDA", dt.date(2026, 7, 10))
    assert len(state) == 1
    assert state[eid]["status"] == "closed"


def test_open_rows_filters_closed(ledger):
    ledger.append_row(make_open_row())
    ledger.append_row(make_open_row(
        entry_id=entry_id("shared", "h1", "AAPL", dt.date(2026, 7, 10)),
        ticker="AAPL",
        status="closed",
        exit_price=125.0,
        exit_timestamp=dt.datetime(2026, 7, 11, 20, 0),
        exit_reason="target",
        pnl_usd=50.0,
        r_net=1.0,
    ))
    open_rows = ledger.open_rows(book="shared")
    assert len(open_rows) == 1
    assert open_rows[0]["ticker"] == "NVDA"


def test_held_symbols(ledger):
    ledger.append_row(make_open_row())
    assert ledger.held_symbols("shared") == {"NVDA"}


def test_h1_and_h2_rows_land_in_separate_files(ledger):
    ledger.append_row(make_open_row())
    ledger.append_row(make_open_row(
        entry_id=entry_id("shared", "h2", "MSFT", dt.date(2026, 7, 10)),
        family="h2",
        ticker="MSFT",
    ))
    assert ledger.paths.h1.exists()
    assert ledger.paths.h2.exists()
    h1_lines = ledger.paths.h1.read_text().strip().splitlines()
    h2_lines = ledger.paths.h2.read_text().strip().splitlines()
    assert len(h1_lines) == 1
    assert len(h2_lines) == 1


def test_equity_snapshot_idempotent(ledger):
    snap = {"date": dt.date(2026, 7, 10), "book": "shared", "equity": 100000.0,
            "cash": 90000.0, "deployed": 10000.0, "open_count": 1}
    ledger.append_equity_snapshot(snap)
    ledger.append_equity_snapshot(snap)
    series = ledger.equity_series("shared")
    assert len(series) == 1


def test_equity_snapshot_distinguishes_book(ledger):
    ledger.append_equity_snapshot({"date": dt.date(2026, 7, 10), "book": "shared", "equity": 1})
    ledger.append_equity_snapshot({"date": dt.date(2026, 7, 10), "book": "h1solo", "equity": 2})
    assert len(ledger.equity_series("shared")) == 1
    assert len(ledger.equity_series("h1solo")) == 1


def test_signal_idempotent(ledger):
    rec = {"signal_date": dt.date(2026, 7, 10), "book": "shared", "entry_id": "shared:h1:NVDA:2026-07-10",
           "kind": "candidate"}
    ledger.append_signal(rec)
    ledger.append_signal(rec)
    assert len(ledger.signals(dt.date(2026, 7, 10))) == 1


def test_signals_filters_by_date(ledger):
    ledger.append_signal({"signal_date": dt.date(2026, 7, 10), "book": "shared",
                           "entry_id": "a", "kind": "candidate"})
    ledger.append_signal({"signal_date": dt.date(2026, 7, 11), "book": "shared",
                           "entry_id": "b", "kind": "candidate"})
    assert len(ledger.signals(dt.date(2026, 7, 10))) == 1
    assert len(ledger.signals()) == 2


def test_processed_upkeep_dates(ledger):
    ledger.append_signal({"signal_date": dt.date(2026, 7, 10), "book": "shared",
                           "entry_id": None, "kind": "upkeep_done", "date": dt.date(2026, 7, 10)})
    assert ledger.processed_upkeep_dates() == {dt.date(2026, 7, 10)}
