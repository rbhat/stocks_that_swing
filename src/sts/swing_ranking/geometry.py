"""Generic, configuration-driven entry geometry resolution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sts.swing_ranking.contracts import (
    Candidate,
    Charter,
    ContractViolation,
    EntryGeometry,
)
from sts.swing_ranking.identity import identity_hash

_KINDS = (
    "entry_minus_fact_multiple",
    "fact_minus_fact_multiple",
    "entry_plus_fact_multiple",
    "fact_plus_fact_multiple",
    "fact_value",
    "entry_plus_risk_multiple",
)


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class PriceFormula:
    """One explicit formula for a stop or target price."""

    kind: Literal[
        "entry_minus_fact_multiple",
        "fact_minus_fact_multiple",
        "entry_plus_fact_multiple",
        "fact_plus_fact_multiple",
        "fact_value",
        "entry_plus_risk_multiple",
    ]
    primary_fact: str | None
    secondary_fact: str | None
    multiple: Decimal

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ContractViolation(f"unsupported price formula {self.kind!r}")
        if not isinstance(self.multiple, Decimal) or not self.multiple.is_finite():
            raise ContractViolation("price formula multiple must be a finite Decimal")
        if self.kind == "entry_plus_risk_multiple":
            if self.primary_fact is not None or self.secondary_fact is not None:
                raise ContractViolation("risk-multiple formula cannot name signal facts")
        elif self.kind == "fact_value":
            if self.primary_fact is None or self.secondary_fact is not None:
                raise ContractViolation("fact-value formula requires only primary_fact")
            object.__setattr__(
                self,
                "primary_fact",
                _text(self.primary_fact, "primary_fact"),
            )
            if self.multiple != Decimal(1):
                raise ContractViolation("fact-value formula requires multiple=1")
        elif self.kind.startswith("entry_"):
            if self.primary_fact is None or self.secondary_fact is not None:
                raise ContractViolation("entry formula requires only primary_fact")
            object.__setattr__(
                self,
                "primary_fact",
                _text(self.primary_fact, "primary_fact"),
            )
        else:
            if self.primary_fact is None or self.secondary_fact is None:
                raise ContractViolation("fact formula requires primary and secondary facts")
            object.__setattr__(
                self,
                "primary_fact",
                _text(self.primary_fact, "primary_fact"),
            )
            object.__setattr__(
                self,
                "secondary_fact",
                _text(self.secondary_fact, "secondary_fact"),
            )
        if self.kind != "fact_value" and self.multiple <= 0:
            raise ContractViolation("price formula multiple must be positive")


@dataclass(frozen=True)
class GeometrySpec:
    """A complete, versioned stop/target/time program."""

    version: str
    stop: PriceFormula
    target: PriceFormula
    hold_sessions: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, "geometry version"))
        if not isinstance(self.stop, PriceFormula) or not isinstance(
            self.target,
            PriceFormula,
        ):
            raise ContractViolation("geometry stop and target must be PriceFormula values")
        if (
            isinstance(self.hold_sessions, bool)
            or not isinstance(self.hold_sessions, int)
            or self.hold_sessions != 21
        ):
            raise ContractViolation("geometry hold_sessions must equal 21")

    @property
    def definition(self) -> dict:
        return {
            "version": self.version,
            "stop": self.stop,
            "target": self.target,
            "hold_sessions": self.hold_sessions,
        }

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/geometry-spec/v1", self.definition)

    @property
    def signal_fact_names(self) -> tuple[str, ...]:
        """Return the declared candidate facts consumed by either formula."""
        return tuple(
            sorted(
                {
                    name
                    for formula in (self.stop, self.target)
                    for name in (formula.primary_fact, formula.secondary_fact)
                    if name is not None
                }
            )
        )


def _fact(candidate: Candidate, name: str | None) -> Decimal:
    if name is None or name not in candidate.signal_facts:
        raise ContractViolation(f"geometry requires missing signal fact {name!r}")
    return candidate.signal_facts[name].value


def _evaluate(
    formula: PriceFormula,
    candidate: Candidate,
    entry_price: Decimal,
    risk_per_share: Decimal | None,
) -> Decimal:
    if formula.kind == "entry_minus_fact_multiple":
        return entry_price - _fact(candidate, formula.primary_fact) * formula.multiple
    if formula.kind == "fact_minus_fact_multiple":
        return _fact(candidate, formula.primary_fact) - (
            _fact(candidate, formula.secondary_fact) * formula.multiple
        )
    if formula.kind == "entry_plus_fact_multiple":
        return entry_price + _fact(candidate, formula.primary_fact) * formula.multiple
    if formula.kind == "fact_plus_fact_multiple":
        return _fact(candidate, formula.primary_fact) + (
            _fact(candidate, formula.secondary_fact) * formula.multiple
        )
    if formula.kind == "fact_value":
        return _fact(candidate, formula.primary_fact)
    if risk_per_share is None:
        raise ContractViolation("target risk multiple requires a resolved stop")
    return entry_price + risk_per_share * formula.multiple


def resolve_geometry(
    *,
    candidate: Candidate,
    entry_price: Decimal,
    spec: GeometrySpec,
    charter: Charter,
) -> EntryGeometry:
    """Resolve and validate geometry at the actual next-session opening fill."""
    if not isinstance(entry_price, Decimal) or not entry_price.is_finite():
        raise ContractViolation("entry_price must be a finite Decimal")
    stop = _evaluate(spec.stop, candidate, entry_price, None)
    risk = entry_price - stop
    target = _evaluate(spec.target, candidate, entry_price, risk)
    geometry = EntryGeometry(
        candidate_identity=candidate.identity,
        entry_price=entry_price,
        initial_stop_price=stop,
        target_price=target,
        planned_hold_sessions=spec.hold_sessions,
    )
    geometry.validate_against(candidate, charter)
    return geometry
