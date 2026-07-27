"""Locked feature dictionary and signal-close availability checks."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sts.ml.contracts import (
    ContractViolation,
    normalize_track,
    require_date,
)

WARMUP_SESSIONS = 300

RETURN_HORIZONS = (1, 2, 5, 10, 20, 60, 126, 252)
MA_WINDOWS = (10, 20, 50, 100, 200)
VOLATILITY_WINDOWS = (5, 10, 20, 60)
VOLUME_MEDIAN_WINDOWS = (5, 20, 60)
DOLLAR_VOLUME_MEDIAN_WINDOWS = (20, 60)
SPY_RELATIVE_HORIZONS = (5, 20, 60, 126, 252)

DETECTOR_FLAG_FEATURES = (
    "detector_flag_tp_rsi6_w5",
    "detector_flag_tp_rsi10_w7",
    "detector_flag_tp_rsi14_w10",
    "detector_flag_vc_tight",
    "detector_flag_vc_core",
    "detector_flag_vc_broad",
)

_BASE_FEATURES = (
    *(f"adjusted_return_{horizon}" for horizon in RETURN_HORIZONS),
    *(f"close_to_ma_{window}" for window in MA_WINDOWS),
    *(
        f"realized_volatility_{window}"
        for window in VOLATILITY_WINDOWS
    ),
    "atr14_over_close",
    "atr14_percentile_60",
    "range_over_close",
    "close_location_in_range",
    "gap_open_to_prior_close",
    "gap_abs_open_to_prior_close",
    *(
        f"volume_to_median_{window}"
        for window in VOLUME_MEDIAN_WINDOWS
    ),
    *(
        f"dollar_volume_to_median_{window}"
        for window in DOLLAR_VOLUME_MEDIAN_WINDOWS
    ),
    *(
        f"spy_relative_return_{horizon}"
        for horizon in SPY_RELATIVE_HORIZONS
    ),
    "spy_above_ma_200",
)

TRACK_A_FEATURES = (*_BASE_FEATURES, *DETECTOR_FLAG_FEATURES)
TRACK_B_FEATURES = _BASE_FEATURES
BINARY_FEATURES = frozenset((*DETECTOR_FLAG_FEATURES, "spy_above_ma_200"))


class FutureFeatureViolation(ContractViolation):
    """A feature was not available by the completed signal close."""


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    lookback_sessions: int
    source: str
    definition: str
    available_at: str = "signal_close"


def _lookback(name: str) -> int:
    if name.startswith("adjusted_return_"):
        return int(name.rsplit("_", 1)[1])
    if name.startswith("close_to_ma_"):
        return int(name.rsplit("_", 1)[1])
    if name.startswith("realized_volatility_"):
        return int(name.rsplit("_", 1)[1])
    if name == "atr14_over_close":
        return 14
    if name == "atr14_percentile_60":
        return 73
    if name in {
        "range_over_close",
        "close_location_in_range",
        "spy_above_ma_200",
    }:
        return 200 if name == "spy_above_ma_200" else 1
    if name.startswith("gap_"):
        return 2
    if "_to_median_" in name:
        return int(name.rsplit("_", 1)[1])
    if name.startswith("spy_relative_return_"):
        return int(name.rsplit("_", 1)[1])
    if name.startswith("detector_flag_"):
        return 1
    raise AssertionError(f"unclassified locked feature {name}")


def _source(name: str) -> str:
    if name.startswith("spy_"):
        return "spy_adjusted_ohlcv"
    if name.startswith("detector_flag_"):
        return "locked_phase3_detector"
    return "symbol_adjusted_ohlcv"


def _definition(name: str) -> str:
    if name.startswith("adjusted_return_"):
        horizon = int(name.rsplit("_", 1)[1])
        return f"adjusted_close_t / adjusted_close_t_minus_{horizon} - 1"
    if name.startswith("close_to_ma_"):
        window = int(name.rsplit("_", 1)[1])
        return (
            f"adjusted_close_t / mean(adjusted_close, trailing_{window}_including_t) - 1"
        )
    if name.startswith("realized_volatility_"):
        window = int(name.rsplit("_", 1)[1])
        return (
            f"sample_std(adjusted_close_return_1, trailing_{window}_including_t)"
        )
    definitions = {
        "atr14_over_close": "simple_atr14_through_t / adjusted_close_t",
        "atr14_percentile_60": (
            "average_tie_percentile_rank(simple_atr14_t, "
            "trailing_60_atr14_values_including_t)"
        ),
        "range_over_close": "(adjusted_high_t - adjusted_low_t) / adjusted_close_t",
        "close_location_in_range": (
            "(adjusted_close_t - adjusted_low_t) / "
            "(adjusted_high_t - adjusted_low_t)"
        ),
        "gap_open_to_prior_close": (
            "adjusted_open_t / adjusted_close_t_minus_1 - 1"
        ),
        "gap_abs_open_to_prior_close": "abs(gap_open_to_prior_close)",
        "spy_above_ma_200": (
            "int(spy_adjusted_close_t > "
            "mean(spy_adjusted_close, trailing_200_including_t))"
        ),
    }
    if name in definitions:
        return definitions[name]
    if name.startswith("volume_to_median_"):
        window = int(name.rsplit("_", 1)[1])
        return f"volume_t / median(volume, trailing_{window}_including_t)"
    if name.startswith("dollar_volume_to_median_"):
        window = int(name.rsplit("_", 1)[1])
        return (
            "adjusted_close_t_times_volume_t / "
            f"median(adjusted_close_times_volume, trailing_{window}_including_t)"
        )
    if name.startswith("spy_relative_return_"):
        horizon = int(name.rsplit("_", 1)[1])
        return (
            f"symbol_adjusted_return_{horizon} - spy_adjusted_return_{horizon}"
        )
    if name.startswith("detector_flag_"):
        return "binary_exact_locked_phase3_detector_fired_on_signal_session"
    raise AssertionError(f"undefined locked feature {name}")


FEATURE_SPECS = MappingProxyType(
    {
        name: FeatureSpec(
            name=name,
            lookback_sessions=_lookback(name),
            source=_source(name),
            definition=_definition(name),
        )
        for name in TRACK_A_FEATURES
    }
)


@dataclass(frozen=True)
class FeatureFact:
    value: float | int | bool | None
    available_session: dt.date

    def __post_init__(self) -> None:
        require_date(self.available_session, "available_session")


@dataclass(frozen=True)
class FeatureSnapshot:
    track: str
    signal_session: dt.date
    causal_bars: int
    values: Mapping[str, float | int | None]
    missing: tuple[str, ...]


def feature_names(track: str) -> tuple[str, ...]:
    return TRACK_A_FEATURES if normalize_track(track) == "A" else TRACK_B_FEATURES


def _normalize_feature_value(name: str, value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        normalized: float | int = int(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return None
        normalized = value
    else:
        raise ContractViolation(f"{name} must be numeric, boolean, or missing")
    if name in BINARY_FEATURES and normalized not in (0, 1):
        raise ContractViolation(f"{name} must be binary 0/1 or missing")
    return normalized


def make_feature_snapshot(
    track: str,
    signal_session: dt.date,
    *,
    causal_bars: int,
    facts: Mapping[str, FeatureFact],
) -> FeatureSnapshot:
    """Seal one causal snapshot and reject omissions or future facts."""
    normalized_track = normalize_track(track)
    day = require_date(signal_session, "signal_session")
    if (
        isinstance(causal_bars, bool)
        or not isinstance(causal_bars, int)
        or causal_bars < WARMUP_SESSIONS
    ):
        raise ContractViolation(
            f"feature warmup requires {WARMUP_SESSIONS} completed sessions"
        )
    if not isinstance(facts, Mapping):
        raise ContractViolation("facts must be a mapping")

    required = feature_names(normalized_track)
    required_set = set(required)
    provided_set = set(facts)
    missing_facts = sorted(required_set - provided_set)
    unknown_facts = sorted(provided_set - required_set)
    if missing_facts:
        raise ContractViolation(
            f"missing feature facts: {','.join(missing_facts)}"
        )
    if unknown_facts:
        raise ContractViolation(
            f"unknown feature facts: {','.join(unknown_facts)}"
        )

    values: dict[str, float | int | None] = {}
    missing_values = []
    for name in required:
        fact = facts[name]
        if not isinstance(fact, FeatureFact):
            raise ContractViolation(f"{name} must be a FeatureFact")
        if fact.available_session > day:
            raise FutureFeatureViolation(
                f"{name} is available on {fact.available_session}, after {day}"
            )
        value = _normalize_feature_value(name, fact.value)
        values[name] = value
        if value is None:
            missing_values.append(name)

    return FeatureSnapshot(
        track=normalized_track,
        signal_session=day,
        causal_bars=causal_bars,
        values=MappingProxyType(values),
        missing=tuple(missing_values),
    )
