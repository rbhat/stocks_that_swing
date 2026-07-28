from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from sts.ml_v2.contracts import (
    REQUIRED_AS_OF_FACTS,
    REQUIRED_SOURCE_KINDS,
    Bar,
    Candidate,
    ContractViolation,
    PointInTimeManifest,
    SessionFrame,
    SourceRecord,
    locked_setup_contract,
    validate_synthetic_inputs,
)
from sts.ml_v2.identity import (
    candidate_identity,
    canonical_bytes,
    identity_hash,
    tie_breaker,
)


def _manifest() -> PointInTimeManifest:
    return PointInTimeManifest(
        dt.date(2024, 1, 1),
        dt.date(2025, 1, 1),
        tuple(
            SourceRecord(
                kind=kind,
                content_hash=hashlib.sha256(kind.encode()).hexdigest(),
                schema_version="synthetic-v1",
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
    )


def _candidate(
    manifest: PointInTimeManifest,
    *,
    permanent_id: str = "perm-1",
    symbol: str = "ZZZ",
    score: str = "1",
) -> Candidate:
    signal = dt.date(2024, 1, 2)
    return Candidate(
        setup_id="P-D",
        fold_id="F1",
        permanent_id=permanent_id,
        symbol=symbol,
        signal_session=signal,
        entry_session=dt.date(2024, 1, 3),
        score=Decimal(score),
        signal_close=Decimal(100),
        atr14=Decimal(2),
        mdv20=Decimal(100000000),
        source_identity=manifest.identity,
        facts_as_of={name: signal for name in REQUIRED_AS_OF_FACTS},
    )


def test_six_complete_setup_identities_are_locked_and_distinct():
    contracts = [locked_setup_contract(setup_id) for setup_id in (
        "P-D", "P-R", "P-H", "B-D", "B-R", "B-H"
    )]
    assert len({contract.identity for contract in contracts}) == 6
    assert all(contract.starting_cash == Decimal(1000000) for contract in contracts)
    assert all(contract.risk_fraction == Decimal("0.005") for contract in contracts)
    with pytest.raises(ContractViolation, match="one of"):
        locked_setup_contract("P-X")


def test_canonical_identity_is_order_independent_and_decimal_stable():
    left = {"amount": Decimal("1.2300"), "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "amount": Decimal("1.23")}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert identity_hash("fixture", left) == identity_hash("fixture", right)
    with pytest.raises(ValueError, match="finite"):
        canonical_bytes({"bad": Decimal("NaN")})
    with pytest.raises(ValueError, match="float"):
        canonical_bytes({"bad": 1.25})


def test_tie_break_never_uses_symbol_text():
    day = dt.date(2024, 1, 2)
    assert tie_breaker("P-D", day, "perm-1") == tie_breaker(
        "P-D", day, "perm-1"
    )
    assert tie_breaker("P-D", day, "perm-1") != tie_breaker(
        "P-D", day, "perm-2"
    )
    manifest = _manifest()
    candidate = _candidate(manifest, symbol="OLD")
    assert candidate_identity(candidate) == candidate_identity(
        replace(candidate, symbol="NEW")
    )


def test_manifest_and_candidate_fail_closed_on_missing_or_future_facts():
    sources = _manifest().sources
    reordered = PointInTimeManifest(
        dt.date(2024, 1, 1),
        dt.date(2025, 1, 1),
        tuple(reversed(sources)),
    )
    assert reordered.identity == _manifest().identity
    assert [source.kind for source in reordered.sources] == list(
        REQUIRED_SOURCE_KINDS
    )
    with pytest.raises(ContractViolation, match="lacks required"):
        PointInTimeManifest(
            dt.date(2024, 1, 1),
            dt.date(2025, 1, 1),
            sources[:-1],
        )
    with pytest.raises(ContractViolation, match="synthetic"):
        replace(sources[0], provider="vendor", synthetic=False)

    manifest = _manifest()
    candidate = _candidate(manifest)
    future_facts = dict(candidate.facts_as_of)
    future_facts["security_master"] = dt.date(2024, 1, 3)
    with pytest.raises(ContractViolation, match="future fact"):
        replace(candidate, facts_as_of=future_facts)
    with pytest.raises(ContractViolation, match="source identity"):
        replace(candidate, source_identity="0" * 64).validate_against(manifest)


def test_synthetic_input_interface_rejects_config_drift_and_duplicate_facts():
    manifest = _manifest()
    candidate = _candidate(manifest)
    bar = Bar(
        "perm-1",
        "ZZZ",
        Decimal(100),
        Decimal(101),
        Decimal(99),
        Decimal(100),
    )
    frame = SessionFrame(dt.date(2024, 1, 3), (bar,))
    validate_synthetic_inputs(
        setup=locked_setup_contract("P-D"),
        manifest=manifest,
        sessions=(frame,),
        candidates=(candidate,),
    )
    with pytest.raises(ContractViolation, match="differs"):
        validate_synthetic_inputs(
            setup=replace(locked_setup_contract("P-D"), risk_fraction=Decimal("0.01")),
            manifest=manifest,
            sessions=(frame,),
            candidates=(candidate,),
        )
    with pytest.raises(ContractViolation, match="duplicate"):
        validate_synthetic_inputs(
            setup=locked_setup_contract("P-D"),
            manifest=manifest,
            sessions=(frame, frame),
            candidates=(candidate,),
        )
    with pytest.raises(ContractViolation, match="candidate.*duplicate"):
        validate_synthetic_inputs(
            setup=locked_setup_contract("P-D"),
            manifest=manifest,
            sessions=(frame,),
            candidates=(candidate, replace(candidate, score=Decimal(2))),
        )


def test_ohlc_and_halt_contracts_fail_closed():
    with pytest.raises(ContractViolation, match="OHLC"):
        Bar("perm", "X", Decimal(10), Decimal(9), Decimal(8), Decimal(9))
    halted = Bar(
        "perm",
        "X",
        None,
        None,
        None,
        None,
        executable_open=False,
        documented_halt=True,
    )
    assert halted.open is None
