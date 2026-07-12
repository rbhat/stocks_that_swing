"""Tests for stm.tradelog.TradeLog: append-only, dedupe-on-read, concurrent
writers, and the local half of the Drive merge contract."""

from __future__ import annotations

import json

import pytest

from sts.models import TRADE_FIELDS, new_trade_record
from sts.tradelog import TradeLog


def make_record(**overrides) -> dict:
    kwargs = dict(
        mode="backtest",
        source="test",
        config="c1",
        symbol="AAPL",
        direction="long",
        entry_date="2024-01-08",
        exit_date=None,
        entry=100.0,
        size=10,
        stop=70.0,
        targets=[105.44],
        exit=None,
        exit_reason=None,
        pnl_usd=None,
        pnl_pct=None,
        r_multiple=None,
        holding_days=None,
    )
    kwargs.update(overrides)
    return new_trade_record(**kwargs)


def test_append_then_read_round_trips_all_fields(tmp_path):
    log = TradeLog(tmp_path / "trades.jsonl")
    rec = make_record()
    log.append(rec)

    out = log.read()
    assert len(out) == 1
    for field in TRADE_FIELDS:
        assert out[0][field] == rec[field]


def test_append_only_never_rewrites_prior_bytes(tmp_path):
    path = tmp_path / "trades.jsonl"
    log = TradeLog(path)
    log.append(make_record())
    log.append(make_record())

    prior_bytes = path.read_bytes()

    log.append(make_record())

    new_bytes = path.read_bytes()
    assert new_bytes.startswith(prior_bytes)
    assert len(new_bytes) > len(prior_bytes)


def test_missing_required_field_raises_and_writes_nothing(tmp_path):
    path = tmp_path / "trades.jsonl"
    log = TradeLog(path)
    log.append(make_record())
    prior_bytes = path.read_bytes()

    bad = make_record()
    del bad["symbol"]

    with pytest.raises(ValueError, match="symbol"):
        log.append(bad)

    assert path.read_bytes() == prior_bytes


def test_missing_entry_or_exit_date_raises_at_creation(tmp_path):
    kwargs = dict(
        mode="backtest", source="test", config="c1", symbol="AAPL", direction="long",
        exit_date=None, entry=100.0, size=10, stop=70.0, targets=[105.44], exit=None,
        exit_reason=None, pnl_usd=None, pnl_pct=None, r_multiple=None, holding_days=None,
    )  # entry_date omitted
    with pytest.raises(ValueError, match="entry_date"):
        new_trade_record(**kwargs)

    kwargs2 = dict(kwargs, entry_date="2024-01-08")
    del kwargs2["exit_date"]  # exit_date omitted too
    with pytest.raises(ValueError, match="exit_date"):
        new_trade_record(**kwargs2)


def test_full_record_round_trips_entry_and_exit_date(tmp_path):
    log = TradeLog(tmp_path / "trades.jsonl")
    rec = make_record(entry_date="2024-01-08", exit_date="2024-01-11")
    log.append(rec)

    out = log.read()
    assert out[0]["entry_date"] == "2024-01-08"
    assert out[0]["exit_date"] == "2024-01-11"


def test_dedupe_keeps_first_occurrence(tmp_path):
    path = tmp_path / "trades.jsonl"
    log = TradeLog(path)

    rec = make_record(pnl_usd=50.0)
    line1 = json.dumps(rec, default=str, separators=(",", ":")) + "\n"
    rec2 = dict(rec)
    rec2["pnl_usd"] = 999.0
    line2 = json.dumps(rec2, default=str, separators=(",", ":")) + "\n"

    with open(path, "a", encoding="utf-8") as f:
        f.write(line1)
        f.write(line2)

    out = log.read()
    assert len(out) == 1
    assert out[0]["pnl_usd"] == 50.0


def test_corrupt_line_is_skipped_not_fatal(tmp_path, caplog):
    path = tmp_path / "trades.jsonl"
    log1 = TradeLog(path)
    good1 = make_record(symbol="AAPL")
    log1.append(good1)

    with open(path, "ab") as f:
        f.write(b'{"truncated\n')

    log2 = TradeLog(path)
    good2 = make_record(symbol="TSLA")
    log2.append(good2)

    with caplog.at_level("WARNING"):
        out = log1.read()

    ids = {r["id"] for r in out}
    assert ids == {good1["id"], good2["id"]}


def test_two_writers_interleaved_no_data_loss(tmp_path):
    path = tmp_path / "trades.jsonl"
    log_a = TradeLog(path)
    log_b = TradeLog(path)

    ids = set()
    for i in range(10):
        rec_a = make_record(symbol="AAPL", pnl_usd=float(i))
        rec_b = make_record(symbol="TSLA", pnl_usd=float(i))
        ids.add(log_a.append(rec_a))
        ids.add(log_b.append(rec_b))

    out = log_a.read()
    assert len(out) == 20
    assert {r["id"] for r in out} == ids


def test_merge_from_appends_missing_and_is_idempotent(tmp_path):
    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"
    log_a = TradeLog(path_a)
    log_b = TradeLog(path_b)

    r1 = make_record(symbol="AAPL")
    r2 = make_record(symbol="TSLA")
    r3 = make_record(symbol="NVDA")

    log_a.append(r1)
    log_a.append(r2)
    log_b.append(r2)
    log_b.append(r3)

    appended = log_a.merge_from(path_b)
    assert appended == 1

    out_ids = {r["id"] for r in log_a.read()}
    assert out_ids == {r1["id"], r2["id"], r3["id"]}

    appended_again = log_a.merge_from(path_b)
    assert appended_again == 0
    assert len(log_a.read()) == 3


def test_read_missing_file_returns_empty_list(tmp_path):
    log = TradeLog(tmp_path / "does_not_exist.jsonl")
    assert log.read() == []
