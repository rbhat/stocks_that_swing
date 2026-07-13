import datetime as dt

import pytest

from sts.forward.book import START_EQUITY, BookState, h1_throttle_room
from sts.forward.broker import cost_side
from sts.forward.ledger import Ledger, LedgerPaths, entry_id
from sts.risk import position_size


def make_row(**overrides):
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
        "entry_fill": 120.0,
        "entry_price_range": [119.0, 121.0],
        "stop_initial": 115.0,
        "sl": 115.0,
        "tp1": 130.0,
        "tp2": None,
        "status": "open",
        "usd_deployed": 1200.0,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": cost_side(120.0, 10),
        "pnl_usd": None,
        "r_net": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def ledger(tmp_path):
    return Ledger(LedgerPaths(root=tmp_path / "ledger"))


def test_cash_equity_replay_single_open_row(ledger):
    ledger.append_row(make_row())
    state = BookState.from_ledger(ledger, "shared", marks={"NVDA": 125.0})

    entry_fee = cost_side(120.0, 10)
    expected_cash = START_EQUITY - 1200.0 - entry_fee
    assert state.cash == pytest.approx(expected_cash)
    assert state.equity == pytest.approx(expected_cash + 10 * 125.0)
    assert state.open_count() == 1
    assert state.deployed_usd() == pytest.approx(1200.0)


def test_cash_equity_replay_closed_row(ledger):
    entry_fee = cost_side(120.0, 10)
    exit_fee = cost_side(125.0, 10)
    ledger.append_row(make_row())
    ledger.append_row(make_row(
        status="closed",
        exit_price=125.0,
        exit_timestamp=dt.datetime(2026, 7, 11, 20, 0),
        exit_reason="target",
        fees_total=entry_fee + exit_fee,
        pnl_usd=50.0 - entry_fee - exit_fee,
        r_net=1.0,
    ))
    state = BookState.from_ledger(ledger, "shared", marks={})

    expected_cash = START_EQUITY - 1200.0 - entry_fee + 10 * 125.0 - exit_fee
    assert state.cash == pytest.approx(expected_cash)
    assert state.equity == pytest.approx(expected_cash)  # no open positions
    assert state.open_count() == 0


def test_equity_falls_back_to_entry_fill_when_no_mark(ledger):
    ledger.append_row(make_row())
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.equity == pytest.approx(state.cash + 10 * 120.0)


def test_can_enter_dup_symbol_own_book(ledger):
    ledger.append_row(make_row())
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.can_enter("NVDA", 1000.0, shared_blocked=set()) == "dup_symbol"


def test_can_enter_dup_symbol_shared_blocked(ledger):
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.can_enter("MSFT", 1000.0, shared_blocked={"MSFT"}) == "dup_symbol"


def test_can_enter_slot(ledger):
    for i in range(8):
        ledger.append_row(make_row(
            entry_id=entry_id("shared", "h1", f"SYM{i}", dt.date(2026, 7, 10)),
            ticker=f"SYM{i}",
        ))
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.open_count() == 8
    assert state.can_enter("NEW", 1000.0, shared_blocked=set()) == "slot"


def test_can_enter_deploy_cap(ledger):
    # deploy nearly all equity so any new notional busts the 80% cap.
    ledger.append_row(make_row(usd_deployed=79_000.0, qty=1, entry_fill=79_000.0,
                                fees_total=cost_side(79_000.0, 1)))
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.can_enter("NEW", 5_000.0, shared_blocked=set()) == "deploy_cap"


def test_can_enter_none_when_clear(ledger):
    state = BookState.from_ledger(ledger, "shared", marks={})
    assert state.can_enter("NEW", 1000.0, shared_blocked=set()) is None


def test_size_matches_risk_position_size(ledger):
    ledger.append_row(make_row())
    state = BookState.from_ledger(ledger, "shared", marks={"NVDA": 120.0})
    expected = position_size(
        state.equity, 50.0, 45.0,
        deployed=state.deployed_usd(), cash=state.cash, open_positions=state.open_count(),
    )
    assert state.size(50.0, 45.0) == expected
    assert expected > 0


def test_snapshot_shape(ledger):
    ledger.append_row(make_row())
    state = BookState.from_ledger(ledger, "shared", marks={"NVDA": 120.0})
    snap = state.snapshot(dt.date(2026, 7, 12))
    assert snap == {
        "date": "2026-07-12",
        "book": "shared",
        "equity": state.equity,
        "cash": state.cash,
        "usd_deployed": state.deployed_usd(),
        "open_count": 1,
    }


SESSIONS = [dt.date(2026, 7, d) for d in range(6, 13)]  # 7/6 .. 7/12 (7 sessions)


def make_candidate(signal_date, entry_id_, book="shared", family="h1", ticker="AAA"):
    return {
        "signal_date": signal_date,
        "book": book,
        "family": family,
        "entry_id": entry_id_,
        "ticker": ticker,
        "qty": 10,
        "kind": "candidate",
    }


def test_h1_throttle_room_four_in_window_gives_zero(ledger):
    # last 5 sessions: 7/8, 7/9, 7/10, 7/11, 7/12
    for i, d in enumerate([dt.date(2026, 7, 8), dt.date(2026, 7, 9),
                            dt.date(2026, 7, 10), dt.date(2026, 7, 11)]):
        ledger.append_signal(make_candidate(d, f"shared:h1:SYM{i}:{d.isoformat()}", ticker=f"SYM{i}"))
    room = h1_throttle_room(ledger, "shared", SESSIONS)
    assert room == 0


def test_h1_throttle_room_one_falls_out_of_window_gives_one(ledger):
    # 7/7 is outside the trailing-5 window [7/8..7/12]; only 3 remain inside.
    dates = [dt.date(2026, 7, 7), dt.date(2026, 7, 8),
             dt.date(2026, 7, 9), dt.date(2026, 7, 10)]
    for i, d in enumerate(dates):
        ledger.append_signal(make_candidate(d, f"shared:h1:SYM{i}:{d.isoformat()}", ticker=f"SYM{i}"))
    room = h1_throttle_room(ledger, "shared", SESSIONS)
    assert room == 1


def test_h1_throttle_room_dedupes_candidate_and_filled_row(ledger):
    d = dt.date(2026, 7, 10)
    eid = entry_id("shared", "h1", "NVDA", d)
    ledger.append_signal(make_candidate(d, eid, ticker="NVDA"))
    ledger.append_row(make_row(entry_id=eid, signal_date=d))
    room = h1_throttle_room(ledger, "shared", SESSIONS)
    assert room == 3  # one distinct entry, not two


def test_h1_throttle_room_ignores_other_book_and_family(ledger):
    d = dt.date(2026, 7, 10)
    ledger.append_signal(make_candidate(d, "h1solo:h1:AAA:2026-07-10", book="h1solo", ticker="AAA"))
    ledger.append_signal(make_candidate(d, "shared:h2:BBB:2026-07-10", family="h2", ticker="BBB"))
    room = h1_throttle_room(ledger, "shared", SESSIONS)
    assert room == 4
