import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import forward_fill

from sts.forward import sync
from sts.forward.broker import StubPaperBroker, actual_fill_geometry
from sts.forward.ledger import Ledger, LedgerPaths, entry_id
from sts.forward.pipeline import generate_signals, run_upkeep

VERSION = "success-v2.phase2-test"
GEOMETRY = {
    "h1": {"stop_atr_multiple": 2.0, "target_atr_multiple": 4.0},
    "h2": {"stop_atr_multiple": 2.0, "target_atr_multiple": 4.0},
}


class EmptyCatalyst:
    def catalyst_within(self, *args, **kwargs):
        return None


def _prices(asof: dt.date, symbols: list[str]) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range(end=asof, periods=30)
    return {
        symbol: pd.DataFrame(
            {
                "open": [100.0] * len(dates),
                "high": [101.0] * len(dates),
                "low": [99.0] * len(dates),
                "close": [100.0] * len(dates),
                "volume": [1_000_000] * len(dates),
            },
            index=dates,
        )
        for symbol in symbols
    }


def _candidate(symbol: str, family: str, asof: dt.date, rank: int = 0) -> dict:
    rec = {
        "symbol": symbol,
        "family": family,
        "signal_date": asof,
    }
    if family == "h1":
        rec.update(
            {
                "is_seed": False,
                "rsi2_at_trigger": float(rank),
                "reclaim_wait_sessions": 1,
            }
        )
    return rec


def _versioned_ledger(tmp_path: Path, name: str = "ledger") -> Ledger:
    return Ledger(
        LedgerPaths.success_v2(VERSION, base_root=tmp_path / name)
    )


def test_versioned_identity_and_local_root_are_disjoint(tmp_path):
    legacy = LedgerPaths(root=tmp_path / "ledger")
    versioned = LedgerPaths.success_v2(VERSION, base_root=tmp_path / "ledger")

    assert versioned.root == tmp_path / "ledger" / "success-v2" / VERSION
    assert versioned.root != legacy.root
    assert entry_id(
        "shared",
        "h1",
        "AAA",
        dt.date(2026, 7, 26),
        strategy_version=VERSION,
    ) == f"sv2|{VERSION}|shared:h1:AAA:2026-07-26"


def test_legacy_rows_remain_readable_without_mutation(tmp_path):
    paths = LedgerPaths(root=tmp_path / "legacy")
    paths.h1.parent.mkdir(parents=True)
    legacy = {
        "entry_id": "shared:h1:AAA:2026-07-24",
        "family": "h1",
        "source": "local-shared",
        "book": "shared",
        "ticker": "AAA",
        "signal_date": "2026-07-24",
        "timestamp": "2026-07-25T13:30:00+00:00",
        "qty": 1,
        "entry_ref": 100.0,
        "entry_fill": 100.0,
        "entry_price_range": [99.0, 101.0],
        "stop_initial": 95.0,
        "sl": 95.0,
        "tp1": 110.0,
        "tp2": None,
        "status": "open",
        "usd_deployed": 100.0,
        "exit_price": None,
        "exit_timestamp": None,
        "exit_reason": None,
        "fees_total": 1.05,
        "pnl_usd": None,
        "r_net": None,
        "schema_version": 1,
        "seq": 1,
        "updated_at": "2026-07-25T13:30:00+00:00",
    }
    raw = json.dumps(legacy, sort_keys=True) + "\n"
    paths.h1.write_text(raw)

    ledger = Ledger(paths)
    assert "strategy_version" not in ledger.open_rows()[0]
    assert ledger.open_rows()[0]["entry_id"] == legacy["entry_id"]
    assert paths.h1.read_text() == raw


def test_success_v2_ledger_rejects_missing_or_cross_version_contracts(tmp_path):
    ledger = _versioned_ledger(tmp_path)
    base = {
        "kind": "candidate",
        "book": "shared",
        "entry_id": "x",
        "signal_date": "2026-07-26",
    }
    with pytest.raises(ValueError, match="strategy_version"):
        ledger.append_signal(base)
    with pytest.raises(ValueError, match="does not match"):
        ledger.append_signal({**base, "strategy_version": "success-v2.other"})

    legacy = Ledger(LedgerPaths(root=tmp_path / "legacy"))
    with pytest.raises(ValueError, match="legacy ledger root"):
        legacy.append_signal({**base, "strategy_version": VERSION})


def test_summary_and_candidate_carry_immutable_strategy_version(tmp_path):
    ledger = _versioned_ledger(tmp_path)
    asof = dt.date(2023, 12, 29)
    prices = _prices(asof, ["AAA"])

    result = generate_signals(
        ledger,
        prices,
        asof,
        EmptyCatalyst(),
        candidate_source=lambda *_: {
            "h2": [],
            "h1": [_candidate("AAA", "h1", asof)],
        },
        strategy_geometry=GEOMETRY,
    )

    candidate = result["queued"][0]
    assert candidate["strategy_version"] == VERSION
    assert candidate["stop_atr_multiple"] == 2.0
    assert candidate["target_atr_multiple"] == 4.0
    done = next(r for r in ledger.signals(asof) if r["kind"] == "signals_done")
    assert done["strategy_version"] == VERSION
    assert done["summary"]["strategy_version"] == VERSION

    with pytest.raises(ValueError, match="immutable signal"):
        ledger.append_signal({**candidate, "qty": candidate["qty"] + 1})


def test_actual_fill_geometry_strict_boundaries_and_no_stop_widening():
    accepted = actual_fill_geometry(
        {
            "strategy_version": VERSION,
            "atr_sig": 2.0,
            "stop_atr_multiple": 2.0,
            "target_atr_multiple": 4.0,
        },
        100.0,
    )
    assert accepted["accepted"]
    assert accepted["stop_initial"] == 96.0
    assert accepted["target_initial"] == 108.0
    assert accepted["metrics"]["planned_r"] == 2.0

    exact_15r = actual_fill_geometry(
        {
            "strategy_version": VERSION,
            "atr_sig": 2.0,
            "stop_atr_multiple": 2.0,
            "target_atr_multiple": 3.0,
        },
        100.0,
    )
    assert not exact_15r["accepted"]
    assert "planned_r_not_strictly_gt_1_5" in exact_15r["reason"]

    exact_12pct = actual_fill_geometry(
        {
            "strategy_version": VERSION,
            "atr_sig": 6.0,
            "stop_atr_multiple": 2.0,
            "target_atr_multiple": 4.0,
        },
        100.0,
    )
    assert not exact_12pct["accepted"]
    assert exact_12pct["stop_initial"] == 88.0
    assert "12pct_charter" in exact_12pct["reason"]


@pytest.mark.parametrize(
    ("target_multiple", "expected", "reason_fragment"),
    [(4.0, "filled", None), (3.0, "skipped", "planned_r_not_strictly_gt_1_5")],
)
def test_versioned_actual_fill_is_opened_or_durably_rejected(
    tmp_path, target_multiple, expected, reason_fragment
):
    ledger = _versioned_ledger(tmp_path)
    signal_date = dt.date(2023, 12, 28)
    fill_date = dt.date(2023, 12, 29)
    eid = entry_id(
        "shared",
        "h1",
        "AAA",
        signal_date,
        strategy_version=VERSION,
    )
    candidate = {
        "kind": "candidate",
        "book": "shared",
        "family": "h1",
        "entry_id": eid,
        "signal_date": signal_date.isoformat(),
        "ticker": "AAA",
        "qty": 10,
        "entry_price_range": [99.5, 100.5],
        "sl": 96.0,
        "tp1": 100.0 + target_multiple * 2.0,
        "atr_sig": 2.0,
        "close_sig": 100.0,
        "config_name": "phase2_test",
        "stop_atr_multiple": 2.0,
        "target_atr_multiple": target_multiple,
        "strategy_version": VERSION,
    }
    ledger.append_signal(candidate)

    class EmptyStore:
        def load(self, symbol):
            return None

    outcome = forward_fill._process_candidate(
        ledger,
        EmptyStore(),
        StubPaperBroker(lambda symbol, date: 101.0),
        candidate,
        fill_date,
        0.1,
        lambda seconds: None,
        lambda message: None,
    )
    assert outcome == expected

    if expected == "filled":
        row = ledger.state()[eid]
        assert row["strategy_version"] == VERSION
        assert row["entry_fill"] == 101.0
        assert row["stop_initial"] == 97.0
        assert row["target_initial"] == 109.0
        assert row["geometry"]["planned_r"] == 2.0
    else:
        assert eid not in ledger.state()
        reject = next(
            rec
            for rec in ledger.signals()
            if rec["kind"] == "geometry_reject"
        )
        assert reject["reason"] == "invalid_actual_fill_geometry"
        assert reason_fragment in reject["geometry_reason"]


@pytest.mark.parametrize("crash_after", [1, 2, 4])
def test_versioned_signal_retry_is_byte_identical(
    tmp_path, crash_after: int
):
    asof = dt.date(2023, 12, 29)
    symbols = ["H2A", "H2B", "H1A", "H1B"]
    prices = _prices(asof, symbols)

    def source(*_):
        return {
            "h2": [_candidate("H2A", "h2", asof), _candidate("H2B", "h2", asof)],
            "h1": [_candidate("H1A", "h1", asof), _candidate("H1B", "h1", asof, 1)],
        }

    uninterrupted = _versioned_ledger(tmp_path, "uninterrupted")
    run_upkeep(uninterrupted, prices, asof)
    generate_signals(
        uninterrupted,
        prices,
        asof,
        EmptyCatalyst(),
        candidate_source=source,
        strategy_geometry=GEOMETRY,
    )

    resumed = _versioned_ledger(tmp_path, "resumed")
    run_upkeep(resumed, prices, asof)
    original = resumed.append_signal
    count = 0

    def append_then_crash(rec):
        nonlocal count
        original(rec)
        if rec.get("kind") in {"candidate", "skip"}:
            count += 1
            if count == crash_after:
                raise RuntimeError("injected crash")

    resumed.append_signal = append_then_crash
    with pytest.raises(RuntimeError, match="injected"):
        generate_signals(
            resumed,
            prices,
            asof,
            EmptyCatalyst(),
            candidate_source=source,
            strategy_geometry=GEOMETRY,
        )
    resumed.append_signal = original
    generate_signals(
        resumed,
        prices,
        asof,
        EmptyCatalyst(),
        candidate_source=source,
        strategy_geometry=GEOMETRY,
    )

    for filename in ("h1.jsonl", "h2.jsonl", "equity.jsonl", "signals.jsonl"):
        expected_path = uninterrupted.paths.root / filename
        actual_path = resumed.paths.root / filename
        assert (
            expected_path.read_bytes() if expected_path.exists() else b""
        ) == (
            actual_path.read_bytes() if actual_path.exists() else b""
        )


def test_versioned_eod_candidate_source_sees_no_future_bar(tmp_path):
    ledger = _versioned_ledger(tmp_path)
    asof = dt.date(2023, 12, 29)
    prices = _prices(asof, ["AAA"])
    prices["AAA"].loc[pd.Timestamp("2024-01-02")] = prices["AAA"].iloc[-1]

    def source(causal, *_):
        assert max(causal["AAA"].index.date) == asof
        return {"h1": [], "h2": []}

    generate_signals(
        ledger,
        prices,
        asof,
        EmptyCatalyst(),
        candidate_source=source,
        strategy_geometry=GEOMETRY,
    )


def test_success_v2_sync_namespace_is_disjoint_and_rejects_legacy_rows(
    tmp_path, monkeypatch
):
    paths = LedgerPaths.success_v2(VERSION, base_root=tmp_path / "ledger")
    paths.root.mkdir(parents=True)
    paths.h1.write_text(json.dumps({"entry_id": "legacy", "seq": 1}) + "\n")
    calls = []

    def fake_rc(args, folder_id, dry_run=False):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, returncode=3, stdout="", stderr="not found"
        )

    monkeypatch.setattr(sync, "_rc", fake_rc)
    monkeypatch.setattr(sync.alerts, "send", lambda *args, **kwargs: True)
    outcomes = sync.sync_ledgers(paths, dry_run=True)

    assert outcomes["h1.jsonl"].startswith("error")
    assert any(f":success-v2/{VERSION}/" in call[1] for call in calls)
