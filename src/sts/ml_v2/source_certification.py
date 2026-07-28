"""Fail-closed source certification contracts for ML-v2 Gate 2.

This module describes source evidence only.  It does not download data,
materialize development rows, build features, fit models, or run simulations.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sts.ml_v2.contracts import (
    REQUIRED_SOURCE_KINDS,
    STUDY_ID,
    ContractViolation,
)
from sts.ml_v2.identity import identity_hash, require_sha256

Disposition = Literal[
    "point_in_time_certified",
    "not_run_input_failure",
    "rejected_leakage_risk",
]

_DISPOSITIONS = {
    "point_in_time_certified",
    "not_run_input_failure",
    "rejected_leakage_risk",
}


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be a non-empty string")
    return value.strip()


def _date(value: dt.date, name: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ContractViolation(f"{name} must be a datetime.date")
    return value


@dataclass(frozen=True)
class SourceCertification:
    """One required source's Gate 2 evidence.

    Failed or rejected sources retain nullable acquisition fields so absence
    is represented honestly.  A certified record must provide every locked
    provenance and coverage field.
    """

    kind: str
    provider: str
    license_use_constraint: str
    schema_version: str | None
    covered_start: dt.date | None
    covered_end_exclusive: dt.date | None
    as_of_semantics: str | None
    revision_policy: str | None
    row_count: int | None
    content_hash: str | None
    disposition: Disposition
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "source kind"))
        if self.kind not in REQUIRED_SOURCE_KINDS:
            raise ContractViolation(f"unknown source kind {self.kind!r}")
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(
            self,
            "license_use_constraint",
            _text(self.license_use_constraint, "license_use_constraint"),
        )
        if self.disposition not in _DISPOSITIONS:
            raise ContractViolation(f"invalid source disposition {self.disposition!r}")
        failures = tuple(_text(item, "source failure") for item in self.failures)
        object.__setattr__(self, "failures", failures)

        for name in ("schema_version", "as_of_semantics", "revision_policy"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if self.content_hash is not None:
            try:
                require_sha256(self.content_hash, f"{self.kind} content_hash")
            except ValueError as exc:
                raise ContractViolation(str(exc)) from exc
        if self.row_count is not None and (
            isinstance(self.row_count, bool)
            or not isinstance(self.row_count, int)
            or self.row_count < 0
        ):
            raise ContractViolation("row_count must be a non-negative integer")
        if self.covered_start is not None:
            _date(self.covered_start, "covered_start")
        if self.covered_end_exclusive is not None:
            _date(self.covered_end_exclusive, "covered_end_exclusive")
        if (
            self.covered_start is not None
            and self.covered_end_exclusive is not None
            and self.covered_start >= self.covered_end_exclusive
        ):
            raise ContractViolation("source coverage interval must be non-empty")

        if self.disposition == "point_in_time_certified":
            required = {
                "schema_version": self.schema_version,
                "covered_start": self.covered_start,
                "covered_end_exclusive": self.covered_end_exclusive,
                "as_of_semantics": self.as_of_semantics,
                "revision_policy": self.revision_policy,
                "row_count": self.row_count,
                "content_hash": self.content_hash,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ContractViolation(
                    f"certified {self.kind} lacks required metadata {missing}"
                )
            if self.row_count == 0:
                raise ContractViolation(f"certified {self.kind} cannot be empty")
            if failures:
                raise ContractViolation(
                    f"certified {self.kind} cannot retain source failures"
                )
        elif not failures:
            raise ContractViolation(
                f"non-certified {self.kind} must record at least one failure"
            )

    def validate_coverage(
        self,
        authorized_start: dt.date,
        authorized_end_exclusive: dt.date,
    ) -> None:
        """Require a certified source to cover the full authorized interval."""
        if self.disposition != "point_in_time_certified":
            return
        assert self.covered_start is not None
        assert self.covered_end_exclusive is not None
        if (
            self.covered_start > authorized_start
            or self.covered_end_exclusive < authorized_end_exclusive
        ):
            raise ContractViolation(
                f"certified {self.kind} does not cover the authorized interval"
            )


@dataclass(frozen=True)
class Gate2SourceManifest:
    """Complete, canonical Gate 2 source decision."""

    authorized_start: dt.date
    authorized_end_exclusive: dt.date
    sources: tuple[SourceCertification, ...]
    study_id: str = STUDY_ID
    schema_version: str = "ml-v2-gate-2-source-manifest-v1"

    def __post_init__(self) -> None:
        if self.study_id != STUDY_ID:
            raise ContractViolation(f"study_id must remain {STUDY_ID!r}")
        _text(self.schema_version, "schema_version")
        start = _date(self.authorized_start, "authorized_start")
        end = _date(self.authorized_end_exclusive, "authorized_end_exclusive")
        if start >= end:
            raise ContractViolation("authorized interval must be non-empty")

        kinds = [source.kind for source in self.sources]
        if len(kinds) != len(set(kinds)):
            raise ContractViolation("source kinds must be unique")
        missing = sorted(set(REQUIRED_SOURCE_KINDS) - set(kinds))
        extra = sorted(set(kinds) - set(REQUIRED_SOURCE_KINDS))
        if missing or extra:
            raise ContractViolation(
                f"manifest source mismatch: missing={missing}, extra={extra}"
            )
        by_kind = {source.kind: source for source in self.sources}
        ordered = tuple(by_kind[kind] for kind in REQUIRED_SOURCE_KINDS)
        for source in ordered:
            source.validate_coverage(start, end)
        object.__setattr__(self, "sources", ordered)

    @property
    def status(self) -> Literal["PASS", "STOP_INPUT"]:
        if all(
            source.disposition == "point_in_time_certified" for source in self.sources
        ):
            return "PASS"
        return "STOP_INPUT"

    @property
    def identity(self) -> str:
        return identity_hash("ml-v2/gate-2-source-manifest/v1", self)

    @property
    def failed_kinds(self) -> tuple[str, ...]:
        return tuple(
            source.kind
            for source in self.sources
            if source.disposition != "point_in_time_certified"
        )


def unavailable_source(
    kind: str,
    *,
    provider: str,
    failure: str,
    license_use_constraint: str = "No licensed extract or credentials available",
) -> SourceCertification:
    """Construct an explicit unavailable-source record."""
    return SourceCertification(
        kind=kind,
        provider=provider,
        license_use_constraint=license_use_constraint,
        schema_version=None,
        covered_start=None,
        covered_end_exclusive=None,
        as_of_semantics=None,
        revision_policy=None,
        row_count=None,
        content_hash=None,
        disposition="not_run_input_failure",
        failures=(failure,),
    )
