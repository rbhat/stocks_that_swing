from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from sts.swing_ranking.source_inputs import (
    SourceInputViolation,
    atomic_write,
    investing_search_query,
    merge_earnings_snapshots,
    normalize_earnings_inputs,
    normalize_security_inputs,
    select_investing_instrument,
    select_openfigi_security,
)


def _figi_result(
    *,
    symbol: str = "AAA",
    share_class: str = "BBG001234567",
    composite: str = "BBG009876543",
) -> dict[str, object]:
    return {
        "data": [
            {
                "figi": composite,
                "name": "AAA CORPORATION",
                "ticker": symbol,
                "exchCode": "US",
                "compositeFIGI": composite,
                "securityType": "Common Stock",
                "marketSector": "Equity",
                "shareClassFIGI": share_class,
                "securityType2": "Common Stock",
                "securityDescription": symbol,
            }
        ]
    }


def test_openfigi_share_class_is_the_permanent_id_and_ticker_is_not_identity():
    selected = select_openfigi_security("AAA", _figi_result())
    assert selected["permanent_id"] == "BBG001234567"
    assert selected["permanent_id_type"] == "ID_BB_GLOBAL_SHARE_CLASS_LEVEL"
    assert selected["permanent_id"] != selected["symbol"]

    ambiguous = _figi_result()
    ambiguous["data"].append(
        _figi_result(share_class="BBG001234568", composite="BBG009876544")[
            "data"
        ][0]
    )
    with pytest.raises(SourceInputViolation, match="exactly one"):
        select_openfigi_security("AAA", ambiguous)


def test_security_inputs_cover_each_cache_symbol_with_permanent_ids():
    security_master, symbol_history = normalize_security_inputs(
        symbols=("AAA",),
        mapping_results=(_figi_result(),),
        roster_manifest={
            "symbols": {
                "AAA": {
                    "first_session": "2020-01-02",
                    "last_session": "2025-01-03",
                    "n_bars": 1,
                    "file_sha256": "a" * 64,
                }
            }
        },
        raw_sha256="b" * 64,
        retrieved_at="2025-01-04T00:00:00+00:00",
        coverage_end_exclusive=dt.date(2025, 1, 4),
    )
    assert security_master["securities"][0]["permanent_id"] == "BBG001234567"
    assert symbol_history["history"] == [
        {
            "permanent_id": "BBG001234567",
            "symbol": "AAA",
            "start": "2020-01-02",
            "end_exclusive": "2025-01-04",
        }
    ]


def test_investing_mapping_is_exact_and_earnings_knowledge_is_causal():
    assert investing_search_query("BF-B") == "BFb"
    assert investing_search_query("AAPL") == "AAPL"
    search = {
        "quotes": [
            {
                "id": 42,
                "url": "/equities/aaa",
                "description": "AAA Corporation",
                "symbol": "AAA",
                "exchange": "NYSE",
                "flag": "USA",
                "type": "Stock - NYSE",
            },
            {
                "id": 43,
                "url": "/equities/aaa-canada",
                "description": "AAA Canada",
                "symbol": "AAA",
                "exchange": "Toronto",
                "flag": "Canada",
                "type": "Stock - Toronto",
            },
        ]
    }
    instrument = select_investing_instrument("AAA", search)
    normalized = normalize_earnings_inputs(
        securities=(
            {"permanent_id": "BBG001234567", "symbol": "AAA"},
        ),
        instruments=(instrument,),
        earnings_by_instrument={
            42: (
                {
                    "instrument_id": 42,
                    "date": "2025-01-03",
                    "earning_date_type": "OFFICIAL",
                    "market_phase": "AFTER_HOURS",
                    "eps_actual": 1.25,
                    "eps_forecast": 1.2,
                    "revenue_actual": 100,
                    "revenue_forecast": 90,
                },
                {
                    "instrument_id": 42,
                    "date": "2025-02-01",
                    "earning_date_type": "PROJECTED",
                    "market_phase": "PRE_MARKET",
                    "eps_forecast": 1.3,
                },
            )
        },
        raw_sha256="c" * 64,
        retrieved_at="2025-01-06T12:00:00+00:00",
        snapshot_date=dt.date(2025, 1, 6),
        coverage_start=dt.date(2025, 1, 1),
        coverage_end_exclusive=dt.date(2025, 2, 4),
    )
    historical, scheduled = normalized["events"]
    assert historical["knowledge_kind"] == "historical_result"
    assert historical["known_session"] == historical["earnings_session"]
    assert scheduled["knowledge_kind"] == "scheduled_snapshot"
    assert scheduled["known_session"] == "2025-01-06"
    assert scheduled["calendar_date"] == "2025-02-01"
    assert scheduled["earnings_session"] == "2025-02-03"
    assert scheduled["eps_forecast"] == "1.3"


def test_append_only_source_write_refuses_unequal_replacement(tmp_path: Path):
    path = tmp_path / "snapshot.json"
    atomic_write(path, b"one\n", replace=False)
    atomic_write(path, b"one\n", replace=False)
    with pytest.raises(SourceInputViolation, match="append-only"):
        atomic_write(path, b"two\n", replace=False)


def test_daily_schedule_snapshots_retain_first_known_and_supersession():
    base_event = {
        "permanent_id": "BBG001234567",
        "symbol": "AAA",
        "investing_instrument_id": 42,
        "calendar_date": "2025-02-03",
        "earnings_session": "2025-02-03",
        "known_session": "2025-01-06",
        "superseded_session": None,
        "knowledge_kind": "scheduled_snapshot",
        "provider_row_count": 1,
        "provider_selection": "official_then_fiscal_quarter_then_completeness",
        "date_type": "PROJECTED",
        "market_phase": "AFTER_HOURS",
        "eps_actual": None,
        "eps_forecast": "1.2",
        "revenue_actual": None,
        "revenue_forecast": None,
    }
    coverage = [
        {
            "permanent_id": "BBG001234567",
            "coverage_start": "2025-01-06",
            "coverage_end_exclusive": "2025-03-01",
        }
    ]
    first = {
        "source": {
            "snapshot_date": "2025-01-06",
            "raw_sha256": "a" * 64,
        },
        "coverage": coverage,
        "events": [base_event],
    }
    revised_event = dict(
        base_event,
        calendar_date="2025-02-04",
        earnings_session="2025-02-04",
        known_session="2025-01-07",
    )
    second = {
        "source": {
            "snapshot_date": "2025-01-07",
            "raw_sha256": "b" * 64,
        },
        "coverage": coverage,
        "events": [revised_event],
    }

    merged = merge_earnings_snapshots((second, first))
    old, new = merged["events"]
    assert old["earnings_session"] == "2025-02-03"
    assert old["known_session"] == "2025-01-06"
    assert old["superseded_session"] == "2025-01-07"
    assert new["earnings_session"] == "2025-02-04"
    assert new["known_session"] == "2025-01-07"
    assert new["superseded_session"] is None
