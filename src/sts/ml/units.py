"""Eligibility and research-unit contracts for Tracks A and B."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, replace
from typing import Any

from sts.ml.contracts import (
    ContractViolation,
    normalize_symbol,
    require_date,
    row_identity,
)

MIN_CAUSAL_BARS = 300
MIN_ADJUSTED_CLOSE = 5.0
MIN_AVERAGE_DOLLAR_VOLUME_20 = 20_000_000.0
MIN_TRACK_A_CROSS_SECTION = 20
MIN_TRACK_B_TOP3_CROSS_SECTION = 4

LOCKED_TRACK_B_DETECTORS = frozenset(
    {
        "tp-rsi6-w5",
        "tp-rsi10-w7",
        "tp-rsi14-w10",
        "vc-tight",
        "vc-core",
        "vc-broad",
    }
)


def _finite(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class EligibilityFacts:
    symbol: str
    signal_session: dt.date
    in_frozen_roster: bool | None
    causal_bars: int | None
    adjusted_close: float | None
    average_dollar_volume_20: float | None
    next_session_open: float | None
    geometry_valid: bool | None
    label_path_complete: bool | None


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str | None


def evaluate_eligibility(facts: EligibilityFacts) -> EligibilityDecision:
    """Evaluate the locked Track A eligibility facts without imputation."""
    normalize_symbol(facts.symbol)
    require_date(facts.signal_session, "signal_session")
    for field in (
        "in_frozen_roster",
        "causal_bars",
        "adjusted_close",
        "average_dollar_volume_20",
        "next_session_open",
        "geometry_valid",
        "label_path_complete",
    ):
        if getattr(facts, field) is None:
            return EligibilityDecision(False, f"missing_fact:{field}")

    if facts.in_frozen_roster is not True:
        return EligibilityDecision(False, "not_in_frozen_roster")
    if (
        isinstance(facts.causal_bars, bool)
        or not isinstance(facts.causal_bars, int)
        or facts.causal_bars < MIN_CAUSAL_BARS
    ):
        return EligibilityDecision(False, "insufficient_causal_bars")
    if not _finite(facts.adjusted_close):
        return EligibilityDecision(False, "invalid_adjusted_close")
    if float(facts.adjusted_close) < MIN_ADJUSTED_CLOSE:
        return EligibilityDecision(False, "adjusted_close_below_5")
    if not _finite(facts.average_dollar_volume_20):
        return EligibilityDecision(False, "invalid_average_dollar_volume_20")
    if (
        float(facts.average_dollar_volume_20)
        < MIN_AVERAGE_DOLLAR_VOLUME_20
    ):
        return EligibilityDecision(
            False, "average_dollar_volume_20_below_20m"
        )
    if not _finite(facts.next_session_open) or float(facts.next_session_open) <= 0:
        return EligibilityDecision(False, "invalid_next_session_open")
    if facts.geometry_valid is not True:
        return EligibilityDecision(False, "invalid_fixed_geometry")
    if facts.label_path_complete is not True:
        return EligibilityDecision(False, "incomplete_label_path")
    return EligibilityDecision(True, None)


@dataclass(frozen=True)
class TrackAUnit:
    symbol: str
    signal_session: dt.date
    selection_status: str = "eligible"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        require_date(self.signal_session, "signal_session")

    @property
    def row_id(self) -> str:
        return row_identity("A", self.symbol, self.signal_session)


def group_track_a(
    rows: list[TrackAUnit] | tuple[TrackAUnit, ...],
) -> dict[dt.date, tuple[TrackAUnit, ...]]:
    """Group unique Track A rows by date and attach adequacy state."""
    grouped: dict[dt.date, list[TrackAUnit]] = {}
    seen: set[tuple[str, dt.date]] = set()
    for row in rows:
        key = (row.symbol, row.signal_session)
        if key in seen:
            raise ContractViolation(
                f"duplicate Track A unit: {row.symbol} {row.signal_session}"
            )
        seen.add(key)
        grouped.setdefault(row.signal_session, []).append(row)

    result = {}
    for day in sorted(grouped):
        units = sorted(grouped[day], key=lambda item: item.symbol)
        status = (
            "eligible"
            if len(units) >= MIN_TRACK_A_CROSS_SECTION
            else "not_run_inadequate_cross_section"
        )
        result[day] = tuple(replace(unit, selection_status=status) for unit in units)
    return result


@dataclass(frozen=True)
class TrackBEvent:
    symbol: str
    signal_session: dt.date
    detector_source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        require_date(self.signal_session, "signal_session")
        if self.detector_source not in LOCKED_TRACK_B_DETECTORS:
            raise ContractViolation(
                f"unknown detector source: {self.detector_source!r}"
            )


@dataclass(frozen=True)
class TrackBUnit:
    symbol: str
    signal_session: dt.date
    detector_sources: tuple[str, ...]
    selection_status: str

    @property
    def row_id(self) -> str:
        return row_identity("B", self.symbol, self.signal_session)


def deduplicate_track_b(
    events: list[TrackBEvent] | tuple[TrackBEvent, ...],
) -> tuple[TrackBUnit, ...]:
    """Create the deterministic union of the six locked event streams."""
    sources: dict[tuple[str, dt.date], set[str]] = {}
    for event in events:
        key = (event.symbol, event.signal_session)
        sources.setdefault(key, set()).add(event.detector_source)

    date_counts: dict[dt.date, int] = {}
    for _symbol, day in sources:
        date_counts[day] = date_counts.get(day, 0) + 1

    units = []
    for (symbol, day), provenance in sorted(
        sources.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        status = (
            "eligible"
            if date_counts[day] >= MIN_TRACK_B_TOP3_CROSS_SECTION
            else "not_run_inadequate_track_cross_section"
        )
        units.append(
            TrackBUnit(
                symbol=symbol,
                signal_session=day,
                detector_sources=tuple(sorted(provenance)),
                selection_status=status,
            )
        )
    return tuple(units)
