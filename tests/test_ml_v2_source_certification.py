from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sts.ml_v2.contracts import REQUIRED_SOURCE_KINDS, ContractViolation
from sts.ml_v2.source_certification import (
    Gate2SourceManifest,
    SourceCertification,
    unavailable_source,
)

START = dt.date(2002, 1, 1)
END = dt.date(2026, 1, 1)


def _certified(kind: str) -> SourceCertification:
    return SourceCertification(
        kind=kind,
        provider="fixture-vendor",
        license_use_constraint="research use",
        schema_version="fixture-v1",
        covered_start=dt.date(2000, 1, 1),
        covered_end_exclusive=END,
        as_of_semantics="effective and publication timestamps retained",
        revision_policy="immutable content-addressed extraction",
        row_count=1,
        content_hash=hashlib.sha256(kind.encode()).hexdigest(),
        disposition="point_in_time_certified",
    )


def _passing_manifest() -> Gate2SourceManifest:
    return Gate2SourceManifest(
        START,
        END,
        tuple(_certified(kind) for kind in REQUIRED_SOURCE_KINDS),
    )


def test_complete_certified_manifest_passes_and_is_order_stable():
    manifest = _passing_manifest()
    reordered = Gate2SourceManifest(START, END, tuple(reversed(manifest.sources)))
    assert manifest.status == "PASS"
    assert manifest.failed_kinds == ()
    assert reordered.sources == manifest.sources
    assert reordered.identity == manifest.identity


def test_any_unavailable_critical_source_stops_input():
    passing = _passing_manifest()
    sources = list(passing.sources)
    sources[0] = unavailable_source(
        sources[0].kind,
        provider="candidate-vendor",
        failure="licensed extract absent",
    )
    result = Gate2SourceManifest(START, END, tuple(sources))
    assert result.status == "STOP_INPUT"
    assert result.failed_kinds == ("security_master",)
    assert result.identity != passing.identity


def test_certified_source_requires_complete_metadata_and_coverage():
    record = _certified("daily_market_data")
    with pytest.raises(ContractViolation, match="lacks required metadata"):
        replace(record, content_hash=None)
    with pytest.raises(ContractViolation, match="cover"):
        Gate2SourceManifest(
            START,
            END,
            tuple(
                replace(record, covered_start=dt.date(2004, 1, 1))
                if kind == record.kind
                else _certified(kind)
                for kind in REQUIRED_SOURCE_KINDS
            ),
        )
    with pytest.raises(ContractViolation, match="cannot retain"):
        replace(record, failures=("unresolved defect",))
    with pytest.raises(ContractViolation, match="cannot be empty"):
        replace(record, row_count=0)
    with pytest.raises(ContractViolation, match="non-negative integer"):
        replace(record, row_count=1.5)


def test_failed_source_cannot_hide_its_reason_or_forge_hash():
    with pytest.raises(ContractViolation, match="at least one failure"):
        replace(
            _certified("benchmark"),
            disposition="rejected_leakage_risk",
            failures=(),
        )
    with pytest.raises(ContractViolation, match="SHA-256"):
        replace(_certified("benchmark"), content_hash="not-a-hash")


def test_manifest_requires_exact_source_roster():
    with pytest.raises(ContractViolation, match="source mismatch"):
        Gate2SourceManifest(START, END, _passing_manifest().sources[:-1])


def test_committed_gate_2_manifest_reproduces_its_identity():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "evidence"
        / "ml-v2"
        / "gate-2-source-manifest.json"
    )
    payload = json.loads(path.read_text())
    records = []
    for item in payload["sources"]:
        record = dict(item)
        for name in ("covered_start", "covered_end_exclusive"):
            if record[name] is not None:
                record[name] = dt.date.fromisoformat(record[name])
        records.append(SourceCertification(**record))
    manifest = Gate2SourceManifest(
        dt.date.fromisoformat(payload["authorized_start"]),
        dt.date.fromisoformat(payload["authorized_end_exclusive"]),
        tuple(records),
        study_id=payload["study_id"],
        schema_version=payload["schema_version"],
    )
    assert manifest.status == payload["status"]
    assert manifest.failed_kinds == tuple(payload["failed_kinds"])
    assert manifest.identity == payload["identity"]
