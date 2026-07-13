import datetime as dt

import pandas as pd
import pytest

from sts.catalyst import CatalystCalendar
from sts.forward.broker import cost_side
from sts.forward.ledger import Ledger, LedgerPaths, entry_id
from sts.forward.pipeline import (
    detect_missed_sessions,
    generate_signals,
    run_upkeep,
)


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def make_frame(rows: list[dict], start="2024-01-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def flat_rows(n, price=100.0):
    return [bar(price, price + 1, price - 1, price) for _ in range(n)]


@pytest.fixture
def ledger(tmp_path):
    return Ledger(LedgerPaths(root=tmp_path / "ledger"))


@pytest.fixture
def empty_catalyst():
    return CatalystCalendar(events=[])


def make_open_row(entry_date, entry_fill=100.0, sl=96.0, tp1=108.0, qty=10, family="h1", book="shared"):
    eid = entry_id(book, family, "AAA", entry_date)
    return {
        "entry_id": eid,
        "family": family,
        "source": "local-shared" if book == "shared" else "local-h1solo",
        "book": book,
        "ticker": "AAA",
        "signal_date": entry_date - dt.timedelta(days=1),
        "timestamp": dt.datetime.combine(entry_date, dt.time(13, 30), tzinfo=dt.UTC),
        "qty": qty,
        "entry_ref": entry_fill,
        "entry_fill": entry_fill,
        "entry_price_range": [entry_fill - 1, entry_fill + 1],
        "stop_initial": sl,
        "sl": sl,
        "tp1": tp1,
        "tp2": None,
        "status": "open",
        "usd_deployed": entry_fill * qty,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": cost_side(entry_fill, qty),
        "pnl_usd": None,
        "r_net": None,
    }


# ---------------------------------------------------------------------------
# run_upkeep
# ---------------------------------------------------------------------------

def test_run_upkeep_stop_exit(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=10, name="date")
    rows = flat_rows(10)
    rows[3] = bar(100, 101, 94, 95)  # low pierces stop=96 intrabar (no gap)
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    entry_date = idx[0].date()
    row = make_open_row(entry_date)
    ledger.append_row(row)

    asof = idx[3].date()
    closed = run_upkeep(ledger, {"AAA": df}, asof)

    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "stop"
    assert closed[0]["status"] == "closed"
    assert closed[0]["exit_price"] == 96.0


def test_run_upkeep_gap_stop_exit(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=10, name="date")
    rows = flat_rows(10)
    rows[3] = bar(90, 91, 88, 89)  # opens below stop=96
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    entry_date = idx[0].date()
    row = make_open_row(entry_date)
    ledger.append_row(row)

    asof = idx[3].date()
    closed = run_upkeep(ledger, {"AAA": df}, asof)

    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "stop_gap"
    assert closed[0]["exit_price"] == 90.0


def test_run_upkeep_target_exit(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=10, name="date")
    rows = flat_rows(10)
    rows[3] = bar(100, 109, 99, 108)  # high touches target=108
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    entry_date = idx[0].date()
    row = make_open_row(entry_date)
    ledger.append_row(row)

    asof = idx[3].date()
    closed = run_upkeep(ledger, {"AAA": df}, asof)

    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "target"
    assert closed[0]["exit_price"] == 108.0


def test_run_upkeep_time_exit(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=20, name="date")
    rows = flat_rows(20)  # flat, never hits stop/target
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    entry_date = idx[0].date()
    row = make_open_row(entry_date)
    ledger.append_row(row)

    asof = idx[15].date()  # 15 bars after entry -> time stop
    closed = run_upkeep(ledger, {"AAA": df}, asof)

    assert len(closed) == 1
    assert closed[0]["exit_reason"] == "time"


def test_run_upkeep_idempotent(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=10, name="date")
    rows = flat_rows(10)
    rows[3] = bar(100, 101, 94, 95)
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    entry_date = idx[0].date()
    row = make_open_row(entry_date)
    ledger.append_row(row)

    asof = idx[3].date()
    first = run_upkeep(ledger, {"AAA": df}, asof)
    assert len(first) == 1

    second = run_upkeep(ledger, {"AAA": df}, asof)
    assert second == []

    # no duplicate closed row
    closed_rows = [r for r in ledger.state().values() if r["status"] == "closed"]
    assert len(closed_rows) == 1


# ---------------------------------------------------------------------------
# generate_signals
# ---------------------------------------------------------------------------

def make_candidate(symbol, family, signal_date, is_seed=True, rsi2=10.0, wait=1):
    c = {"symbol": symbol, "family": family, "signal_date": signal_date}
    if family == "h1":
        c.update(is_seed=is_seed, rsi2_at_trigger=rsi2, reclaim_wait_sessions=wait)
    return c


def price_df_for(symbol, asof, close=100.0, atr_val=4.0, n=60):
    idx = pd.bdate_range(end=pd.Timestamp(asof), periods=n, name="date")
    rows = []
    for i in range(n):
        rows.append(bar(close, close + atr_val, close - atr_val, close))
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]
    return df


def make_prices(symbols, asof):
    return {s: price_df_for(s, asof) for s in symbols}


def test_generate_signals_h2_before_h1(ledger, empty_catalyst):
    asof = dt.date(2024, 3, 15)
    prices = make_prices(["AAA", "BBB"], asof)

    def source(prices, asof, catalyst):
        return {
            "h2": [make_candidate("BBB", "h2", asof)],
            "h1": [make_candidate("AAA", "h1", asof)],
        }

    result = generate_signals(ledger, prices, asof, empty_catalyst, candidate_source=source)
    queued = result["queued"]
    assert [q["family"] for q in queued if q["book"] == "shared"][:2] == ["h2", "h1"]


def test_generate_signals_h1_throttle(ledger, empty_catalyst):
    asof = dt.date(2024, 3, 15)
    symbols = [f"S{i}" for i in range(6)]
    prices = make_prices(symbols, asof)

    def source(prices, asof, catalyst):
        return {
            "h1": [
                make_candidate(sym, "h1", asof, rsi2=float(i))
                for i, sym in enumerate(symbols)
            ],
            "h2": [],
        }

    result = generate_signals(ledger, prices, asof, empty_catalyst, candidate_source=source)
    shared_queued = [q for q in result["queued"] if q["book"] == "shared"]
    shared_skipped = [q for q in result["skipped"] if q["book"] == "shared"]

    # H1-throttle caps at 4 new entries per rolling 5 sessions in the shared book.
    assert len(shared_queued) == 4
    throttle_skips = [s for s in shared_skipped if s["reason"] == "throttle"]
    assert len(throttle_skips) == 2


def test_generate_signals_cross_family_dup_block(ledger, empty_catalyst):
    asof = dt.date(2024, 3, 15)
    prices = make_prices(["AAA"], asof)

    # AAA already held via h2 in the shared book.
    ledger.append_row(make_open_row(asof - dt.timedelta(days=5), family="h2", book="shared"))

    def source(prices, asof, catalyst):
        return {"h1": [make_candidate("AAA", "h1", asof)], "h2": []}

    result = generate_signals(ledger, prices, asof, empty_catalyst, candidate_source=source)

    shared_skips = [s for s in result["skipped"] if s["book"] == "shared"]
    assert any(s["reason"] == "dup_symbol" for s in shared_skips)

    h1solo_queued = [q for q in result["queued"] if q["book"] == "h1solo"]
    assert any(q["ticker"] == "AAA" for q in h1solo_queued)


def test_generate_signals_skip_reasons_recorded(ledger, empty_catalyst):
    asof = dt.date(2024, 3, 15)
    prices = make_prices(["AAA"], asof)

    def source(prices, asof, catalyst):
        return {"h1": [make_candidate("AAA", "h1", asof)], "h2": []}

    result = generate_signals(ledger, prices, asof, empty_catalyst, candidate_source=source)
    assert result["queued"] or result["skipped"]
    for rec in result["skipped"]:
        assert rec["reason"] in {
            "slot", "throttle", "embargo", "dup_symbol", "deploy_cap", "size_zero",
        }


# ---------------------------------------------------------------------------
# detect_missed_sessions
# ---------------------------------------------------------------------------

def test_detect_missed_sessions(ledger, empty_catalyst):
    idx = pd.bdate_range("2024-01-02", periods=10, name="date")
    rows = flat_rows(10)
    df = pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]

    d0 = idx[0].date()
    run_upkeep(ledger, {"AAA": df}, d0)

    d_later = idx[5].date()
    missing = detect_missed_sessions(ledger, d_later)

    expected = [d.date() for d in idx[1:5]]
    assert missing == expected
