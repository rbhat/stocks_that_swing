from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from sts import calendar
from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_LIMITATION_KINDS,
    REQUIRED_SOURCE_KINDS,
    CandidateGrammar,
    DiscoveryProtocol,
    SourceFact,
    SourceLimitation,
    swing_ranking_charter,
)
from sts.swing_ranking.identity import identity_hash
from sts.swing_ranking.preflight import (
    PreflightPaths,
    PreflightViolation,
    ResolvedParquet,
    resolve_inputs,
)
from sts.swing_ranking.split import derive_evaluation_split

START = dt.date(2024, 1, 2)
CUTOFF = dt.date(2025, 1, 3)
END = dt.date(2025, 1, 4)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _frame(days: tuple[dt.date, ...] | None = None) -> pd.DataFrame:
    if days is None:
        days = tuple(
            session.date()
            for session in calendar.sessions_between(START, CUTOFF)
        )
    index = pd.DatetimeIndex(pd.to_datetime(days))
    return pd.DataFrame(
        {
            "open": [10.0] * len(index),
            "high": [11.0] * len(index),
            "low": [9.0] * len(index),
            "close": [10.5] * len(index),
            "volume": [100] * len(index),
        },
        index=index,
    )


def _protocol(source_hashes: dict[str, str]) -> DiscoveryProtocol:
    return DiscoveryProtocol(
        study_id="swing-ranking-v1",
        protocol_version="preflight-test-v1",
        evidence_label="retrospective_screening",
        evaluation_start=START,
        evaluation_end_exclusive=END,
        data_cutoff=CUTOFF,
        prospective_wall=dt.date(2025, 1, 6),
        evaluation_split=derive_evaluation_split(START, END),
        charter=swing_ranking_charter(),
        candidate_grammar=CandidateGrammar(version="v1", definition={"test": "fixture"}),
        source_facts=tuple(
            SourceFact(
                kind=kind,
                content_hash=source_hashes[kind],
                as_of=CUTOFF,
                coverage_start=START,
                coverage_end_exclusive=END,
                adjustment_basis=ADJUSTMENT_BASIS,
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
        limitations=tuple(
            SourceLimitation(kind=kind, statement=f"{kind} limitation")
            for kind in REQUIRED_LIMITATION_KINDS
        ),
    )


@pytest.fixture
def cache_inputs(tmp_path: Path) -> tuple[DiscoveryProtocol, PreflightPaths]:
    parquet_root = tmp_path / "parquets"
    parquet_root.mkdir()
    roster = tmp_path / "roster.yaml"
    roster.write_text(yaml.safe_dump({"symbols": ["AAA"], "count": 1}), encoding="utf-8")
    parquet = parquet_root / "AAA.parquet"
    frame = _frame()
    frame.to_parquet(parquet)
    roster_manifest = tmp_path / "roster_manifest.json"
    _write_json(
        roster_manifest,
        {
            "adjustment_basis": "split+dividend adjusted total return (auto_adjust=True)",
            "symbols": {
                "AAA": {
                    "file_sha256": _sha(parquet),
                    "first_session": START.isoformat(),
                    "last_session": CUTOFF.isoformat(),
                    "n_bars": len(frame),
                }
            },
        },
    )
    security_master = tmp_path / "security_master.json"
    _write_json(security_master, {"securities": [{"permanent_id": "id-aaa", "symbol": "AAA"}]})
    symbol_history = tmp_path / "symbol_history.json"
    _write_json(
        symbol_history,
        {"history": [{"permanent_id": "id-aaa", "symbol": "AAA", "start": START.isoformat(), "end_exclusive": END.isoformat()}]},
    )
    corporate_actions = tmp_path / "corporate_actions.json"
    _write_json(
        corporate_actions,
        {
            "adjustment_basis": ADJUSTMENT_BASIS,
            "adjustment_vintage": CUTOFF.isoformat(),
            "coverage": [{"permanent_id": "id-aaa", "coverage_start": START.isoformat(), "coverage_end_exclusive": END.isoformat()}],
        },
    )
    earnings = tmp_path / "earnings.json"
    _write_json(
        earnings,
        {
            "coverage": [
                {
                    "permanent_id": "id-aaa",
                    "coverage_start": START.isoformat(),
                    "coverage_end_exclusive": END.isoformat(),
                }
            ],
            "events": [
                {
                    "permanent_id": "id-aaa",
                    "earnings_session": CUTOFF.isoformat(),
                    "known_session": START.isoformat(),
                }
            ],
        },
    )
    exchange = tmp_path / "exchange.json"
    _write_json(
        exchange,
        {
            "exchange": "XNYS",
            "coverage_start": START.isoformat(),
            "coverage_end_exclusive": END.isoformat(),
            "sessions": [item.date().isoformat() for item in calendar.sessions_between(START, CUTOFF)],
        },
    )
    inventory_hash = identity_hash(
        "swing-ranking-v1/parquet-inventory/v1",
        (
            ResolvedParquet(
                permanent_id="id-aaa",
                symbol="AAA",
                file_sha256=_sha(parquet),
                first_session=START,
                last_session=CUTOFF,
                n_bars=len(frame),
            ),
        ),
    )
    source_hashes = {
        "security_master": identity_hash(
            "swing-ranking-v1/security-identity-inputs/v1",
            {
                "security_master_sha256": _sha(security_master),
                "symbol_history_sha256": _sha(symbol_history),
            },
        ),
        "current_roster": _sha(roster),
        "daily_market_data": inventory_hash,
        "corporate_actions": _sha(corporate_actions),
        "earnings_calendar": _sha(earnings),
        "exchange_calendar": _sha(exchange),
    }
    protocol = _protocol(source_hashes)
    source_manifest = tmp_path / "source_manifest.json"
    _write_json(
        source_manifest,
        {
            "sources": {
                kind: {
                    "content_sha256": source_hashes[kind],
                    "as_of": CUTOFF.isoformat(),
                    "coverage_start": START.isoformat(),
                    "coverage_end_exclusive": END.isoformat(),
                    "adjustment_basis": ADJUSTMENT_BASIS,
                }
                for kind in REQUIRED_SOURCE_KINDS
            }
        },
    )
    return protocol, PreflightPaths(
        roster=roster,
        roster_manifest=roster_manifest,
        source_manifest=source_manifest,
        security_master=security_master,
        symbol_history=symbol_history,
        corporate_actions=corporate_actions,
        earnings_calendar=earnings,
        exchange_calendar=exchange,
        parquet_root=parquet_root,
    )


def test_resolve_inputs_returns_immutable_metadata_without_price_frames(cache_inputs):
    protocol, paths = cache_inputs
    resolved = resolve_inputs(protocol, paths)
    assert resolved.protocol_identity == protocol.identity
    assert resolved.securities[0].permanent_id == "id-aaa"
    assert resolved.parquets[0].last_session == CUTOFF
    assert resolved.earnings_events[0].known_session == START
    assert resolved.identity
    with pytest.raises((AttributeError, TypeError)):
        resolved.securities += ()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ("ticker_id", "cannot be the ticker"),
        ("missing_earnings", "earnings calendar"),
        ("missing_parquet", "parquet inventory has absent"),
        ("extra_parquet", "parquet inventory has absent or extra"),
        ("altered_parquet", "parquet hash differs"),
        ("unreadable_parquet", "parquet is unreadable"),
        ("incomplete_parquet", "does not cover protocol evaluation start"),
        ("source_identity", "source manifest identity mismatch"),
    ],
)
def test_resolve_inputs_fails_closed_for_identity_and_cache_damage(cache_inputs, mutate, message):
    protocol, paths = cache_inputs
    parquet = paths.parquet_root / "AAA.parquet"
    if mutate == "ticker_id":
        _write_json(paths.security_master, {"securities": [{"permanent_id": "AAA", "symbol": "AAA"}]})
    elif mutate == "missing_earnings":
        _write_json(paths.earnings_calendar, {"coverage": [], "events": []})
    elif mutate == "missing_parquet":
        parquet.unlink()
    elif mutate == "extra_parquet":
        _frame().to_parquet(paths.parquet_root / "EXTRA.parquet")
    elif mutate == "altered_parquet":
        _frame().assign(close=10.6).to_parquet(parquet)
    elif mutate == "unreadable_parquet":
        parquet.write_bytes(b"not parquet")
        manifest = json.loads(paths.roster_manifest.read_text())
        manifest["symbols"]["AAA"]["file_sha256"] = _sha(parquet)
        _write_json(paths.roster_manifest, manifest)
    elif mutate == "incomplete_parquet":
        _frame((CUTOFF,)).to_parquet(parquet)
        manifest = json.loads(paths.roster_manifest.read_text())
        manifest["symbols"]["AAA"].update(
            file_sha256=_sha(parquet), first_session=CUTOFF.isoformat(), n_bars=1
        )
        _write_json(paths.roster_manifest, manifest)
    elif mutate == "source_identity":
        manifest = json.loads(paths.source_manifest.read_text())
        manifest["sources"]["security_master"]["content_sha256"] = "0" * 64
        _write_json(paths.source_manifest, manifest)
    else:
        raise AssertionError(mutate)
    with pytest.raises(PreflightViolation, match=message):
        resolve_inputs(protocol, paths)
