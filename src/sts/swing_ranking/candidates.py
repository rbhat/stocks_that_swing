"""Causal, configuration-driven candidate generation for swing-ranking-v1."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd

from sts import calendar
from sts.swing_ranking.contracts import (
    REQUIRED_SOURCE_KINDS,
    Candidate,
    ContractViolation,
    DiscoveryProtocol,
    SignalFact,
    StrategyRevision,
)
from sts.swing_ranking.identity import canonical_bytes, identity_hash

_TIMEFRAMES = ("daily", "weekly", "monthly")
_OPERATIONS = (
    "raw",
    "sma",
    "ema",
    "rolling_min",
    "rolling_max",
    "atr",
    "return",
)
_COMPARATORS = ("gt", "gte", "lt", "lte", "crosses_above", "crosses_below")
_OHLCV = ("open", "high", "low", "close", "volume")


def _name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{field} must be a non-empty string")
    return value.strip()


def _count(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractViolation(f"{field} must be a positive integer")
    return value


def _decimal_from_number(value: object, field: str) -> Decimal:
    """Convert a completed pandas calculation into the Decimal contract boundary."""
    if isinstance(value, bool):
        raise ContractViolation(f"{field} must not be a boolean")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, np.integer)):
        result = Decimal(int(value))
    else:
        result = Decimal(str(value))
    if not result.is_finite():
        raise ContractViolation(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class FeatureSpec:
    """One declared feature; no operation or lookback is implicit."""

    name: str
    timeframe: Literal["daily", "weekly", "monthly"]
    operation: str
    source: str
    lookback: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _name(self.name, "feature name"))
        if self.timeframe not in _TIMEFRAMES:
            raise ContractViolation(f"unsupported timeframe {self.timeframe!r}")
        if self.operation not in _OPERATIONS:
            raise ContractViolation(f"unsupported feature operation {self.operation!r}")
        if self.source not in _OHLCV:
            raise ContractViolation(f"unsupported feature source {self.source!r}")
        object.__setattr__(self, "lookback", _count(self.lookback, "feature lookback"))
        if self.operation == "raw" and self.lookback != 1:
            raise ContractViolation("raw features require lookback=1")


@dataclass(frozen=True)
class ConditionSpec:
    """A comparison between a feature and exactly one feature or threshold."""

    left: str
    comparator: str
    right_feature: str | None
    right_threshold: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "left", _name(self.left, "condition left"))
        if self.comparator not in _COMPARATORS:
            raise ContractViolation(f"unsupported comparator {self.comparator!r}")
        has_feature = self.right_feature is not None
        has_threshold = self.right_threshold is not None
        if has_feature == has_threshold:
            raise ContractViolation(
                "condition requires exactly one right_feature or right_threshold"
            )
        if has_feature:
            object.__setattr__(
                self,
                "right_feature",
                _name(self.right_feature, "condition right_feature"),
            )
        else:
            if not isinstance(self.right_threshold, Decimal):
                raise ContractViolation("condition right_threshold must be a Decimal")
            if not self.right_threshold.is_finite():
                raise ContractViolation("condition right_threshold must be finite")


@dataclass(frozen=True)
class StrategyProgram:
    """Executable grammar member with higher-timeframe where and daily when."""

    version: str
    features: tuple[FeatureSpec, ...]
    where: tuple[ConditionSpec, ...]
    when: tuple[ConditionSpec, ...]
    priority_feature: str
    priority_direction: Literal["ascending", "descending"]
    average_dollar_volume_lookback: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _name(self.version, "program version"))
        features = tuple(self.features)
        if not features:
            raise ContractViolation("program features cannot be empty")
        names = [feature.name for feature in features]
        if len(names) != len(set(names)):
            raise ContractViolation("feature names must be unique")
        object.__setattr__(self, "features", features)
        where = tuple(self.where)
        when = tuple(self.when)
        if not where or not when:
            raise ContractViolation("program requires where and when conditions")
        by_name = {feature.name: feature for feature in features}
        used_where = _validate_conditions(where, by_name)
        used_when = _validate_conditions(when, by_name)
        if not any(by_name[name].timeframe in ("weekly", "monthly") for name in used_where):
            raise ContractViolation("where must use a weekly or monthly feature")
        if any(by_name[name].timeframe != "daily" for name in used_when):
            raise ContractViolation("when conditions must use daily features only")
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "when", when)
        priority = _name(self.priority_feature, "priority_feature")
        if priority not in by_name:
            raise ContractViolation("priority_feature must name a declared feature")
        object.__setattr__(self, "priority_feature", priority)
        if self.priority_direction not in ("ascending", "descending"):
            raise ContractViolation("priority_direction must be ascending or descending")
        object.__setattr__(
            self,
            "average_dollar_volume_lookback",
            _count(
                self.average_dollar_volume_lookback,
                "average_dollar_volume_lookback",
            ),
        )

    @property
    def definition(self) -> dict:
        return {
            "version": self.version,
            "features": self.features,
            "where": self.where,
            "when": self.when,
            "priority_feature": self.priority_feature,
            "priority_direction": self.priority_direction,
            "average_dollar_volume_lookback": self.average_dollar_volume_lookback,
        }

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/strategy-program/v1", self.definition)


def _validate_conditions(
    conditions: tuple[ConditionSpec, ...],
    features: dict[str, FeatureSpec],
) -> set[str]:
    used: set[str] = set()
    for condition in conditions:
        if condition.left not in features:
            raise ContractViolation(f"unknown condition feature {condition.left!r}")
        used.add(condition.left)
        if condition.right_feature is not None:
            if condition.right_feature not in features:
                raise ContractViolation(
                    f"unknown condition feature {condition.right_feature!r}"
                )
            used.add(condition.right_feature)
    return used


@dataclass(frozen=True)
class FeatureMatrix:
    values: pd.DataFrame
    available_sessions: pd.DataFrame


@dataclass(frozen=True)
class ScheduledEarnings:
    """A scheduled earnings session and when that schedule was known."""

    earnings_session: dt.date
    known_session: dt.date
    superseded_session: dt.date | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.earnings_session, dt.datetime)
            or not isinstance(self.earnings_session, dt.date)
            or isinstance(self.known_session, dt.datetime)
            or not isinstance(self.known_session, dt.date)
        ):
            raise ContractViolation("earnings sessions must be datetime.date values")
        if self.known_session > self.earnings_session:
            raise ContractViolation("earnings known_session cannot follow the event")
        superseded = self.superseded_session
        if superseded is not None:
            if isinstance(superseded, dt.datetime) or not isinstance(
                superseded,
                dt.date,
            ):
                raise ContractViolation("earnings superseded_session must be a date")
            if superseded <= self.known_session:
                raise ContractViolation(
                    "earnings superseded_session must follow known_session"
                )


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ContractViolation("price frame must be a pandas DataFrame")
    if tuple(frame.columns) != _OHLCV:
        raise ContractViolation(f"price frame columns must equal {_OHLCV!r}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ContractViolation("price frame must use a DatetimeIndex")
    if frame.index.tz is not None:
        raise ContractViolation("price frame index must be timezone-naive")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ContractViolation("price frame index must be sorted and unique")
    if frame.empty:
        raise ContractViolation("price frame cannot be empty")
    if frame.isna().any().any():
        raise ContractViolation("price frame cannot contain missing OHLCV values")
    if not all(calendar.is_session(session.date()) for session in frame.index):
        raise ContractViolation("price frame index must contain exchange sessions only")
    return frame


def _completed_period_bars(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    periods = frame.index.to_period(frequency)
    grouped = frame.groupby(periods, sort=True)
    labels: list[pd.Timestamp] = []
    rows: list[dict[str, object]] = []
    period_keys = list(grouped.groups)
    for period in period_keys:
        part = grouped.get_group(period)
        labels.append(part.index[-1])
        rows.append(
            {
                "open": part["open"].iloc[0],
                "high": part["high"].max(),
                "low": part["low"].min(),
                "close": part["close"].iloc[-1],
                "volume": part["volume"].sum(),
            }
        )
    last_label = labels[-1]
    period_end = period_keys[-1].end_time.date()
    later_sessions = calendar.sessions_between(last_label.date(), period_end)
    if any(session > last_label for session in later_sessions):
        labels.pop()
        rows.pop()
    return pd.DataFrame(rows, index=pd.DatetimeIndex(labels), columns=_OHLCV)


def _feature(frame: pd.DataFrame, spec: FeatureSpec) -> pd.Series:
    source = frame[spec.source]
    if spec.operation == "raw":
        return source
    if spec.operation == "sma":
        return source.rolling(spec.lookback, min_periods=spec.lookback).mean()
    if spec.operation == "ema":
        return source.ewm(span=spec.lookback, adjust=False, min_periods=spec.lookback).mean()
    if spec.operation == "rolling_min":
        return source.rolling(spec.lookback, min_periods=spec.lookback).min()
    if spec.operation == "rolling_max":
        return source.rolling(spec.lookback, min_periods=spec.lookback).max()
    if spec.operation == "return":
        return source / source.shift(spec.lookback) - 1
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(spec.lookback, min_periods=spec.lookback).mean()


def _align_to_daily(
    values: pd.Series,
    daily_index: pd.DatetimeIndex,
) -> tuple[pd.Series, pd.Series]:
    source = pd.DataFrame(
        {
            "available_session": values.index,
            "value": values.to_numpy(),
        }
    ).sort_values("available_session")
    daily = pd.DataFrame({"daily_session": daily_index}).sort_values("daily_session")
    aligned = pd.merge_asof(
        daily,
        source,
        left_on="daily_session",
        right_on="available_session",
        direction="backward",
        allow_exact_matches=True,
    ).set_index("daily_session")
    return aligned["value"].reindex(daily_index), aligned["available_session"].reindex(
        daily_index
    )


def build_feature_matrix(frame: pd.DataFrame, program: StrategyProgram) -> FeatureMatrix:
    """Compute declared features using only bars complete at each daily close."""
    daily = _validate_frame(frame)
    timeframe_frames = {
        "daily": daily,
        "weekly": _completed_period_bars(daily, "W-FRI"),
        "monthly": _completed_period_bars(daily, "M"),
    }
    values: dict[str, pd.Series] = {}
    available: dict[str, pd.Series] = {}
    for spec in program.features:
        feature = _feature(timeframe_frames[spec.timeframe], spec)
        if spec.timeframe == "daily":
            values[spec.name] = feature.reindex(daily.index)
            available[spec.name] = pd.Series(daily.index, index=daily.index)
        else:
            aligned_value, aligned_session = _align_to_daily(feature, daily.index)
            values[spec.name] = aligned_value
            available[spec.name] = aligned_session
    return FeatureMatrix(
        values=pd.DataFrame(values, index=daily.index),
        available_sessions=pd.DataFrame(available, index=daily.index),
    )


def _condition_mask(values: pd.DataFrame, condition: ConditionSpec) -> pd.Series:
    left = values[condition.left]
    right: pd.Series | Decimal
    if condition.right_feature is not None:
        right = values[condition.right_feature]
    else:
        assert condition.right_threshold is not None
        right = float(condition.right_threshold)
    if condition.comparator == "gt":
        return left > right
    if condition.comparator == "gte":
        return left >= right
    if condition.comparator == "lt":
        return left < right
    if condition.comparator == "lte":
        return left <= right
    if condition.comparator == "crosses_above":
        return (left > right) & (left.shift(1) <= _shift_right(right))
    return (left < right) & (left.shift(1) >= _shift_right(right))


def _shift_right(value: pd.Series | Decimal) -> pd.Series | Decimal:
    return value.shift(1) if isinstance(value, pd.Series) else value


def _next_session(session: pd.Timestamp) -> dt.date:
    return calendar.nyse().next_session(session).date()


def _session_distance(start: dt.date, end: dt.date) -> int:
    sessions = calendar.sessions_between(start, end)
    return sum(session.date() > start for session in sessions)


def generate_candidates(
    *,
    frame: pd.DataFrame,
    permanent_id: str,
    symbol: str,
    protocol: DiscoveryProtocol,
    strategy: StrategyRevision,
    program: StrategyProgram,
    geometry_fact_names: tuple[str, ...],
    facts_as_of: dict[str, dt.date],
    scheduled_earnings: tuple[ScheduledEarnings, ...],
) -> tuple[Candidate, ...]:
    """Return every triggered intent; eligibility rejections belong to the simulator."""
    strategy.validate_against(protocol)
    allowed_programs = protocol.candidate_grammar.definition.get("program_identities")
    if not isinstance(allowed_programs, tuple) or program.identity not in allowed_programs:
        raise ContractViolation("strategy program is not declared by the candidate grammar")
    if canonical_bytes(strategy.parameters) != canonical_bytes(
        {"program": program.definition}
    ):
        raise ContractViolation("strategy parameters do not match the strategy program")
    geometry_facts = tuple(geometry_fact_names)
    if (
        not all(isinstance(name, str) and name.strip() for name in geometry_facts)
        or len(geometry_facts) != len(set(geometry_facts))
    ):
        raise ContractViolation("geometry_fact_names must be unique non-empty strings")
    declared_features = {feature.name for feature in program.features}
    if not set(geometry_facts).issubset(declared_features):
        raise ContractViolation("geometry facts must name declared strategy features")
    if set(facts_as_of) != set(REQUIRED_SOURCE_KINDS):
        raise ContractViolation("facts_as_of must include every required source kind")
    daily = _validate_frame(frame)
    matrix = build_feature_matrix(daily, program)
    mask = pd.Series(True, index=daily.index)
    for condition in (*program.where, *program.when):
        mask &= _condition_mask(matrix.values, condition).fillna(False)
    adv = (daily["close"] * daily["volume"]).rolling(
        program.average_dollar_volume_lookback,
        min_periods=program.average_dollar_volume_lookback,
    ).mean()
    candidates: list[Candidate] = []
    earnings = tuple(
        sorted(
            scheduled_earnings,
            key=lambda item: (item.earnings_session, item.known_session),
        )
    )
    if not all(isinstance(item, ScheduledEarnings) for item in earnings):
        raise ContractViolation(
            "scheduled_earnings must contain ScheduledEarnings values"
        )
    used_features = {
        condition.left for condition in (*program.where, *program.when)
    } | {
        condition.right_feature
        for condition in (*program.where, *program.when)
        if condition.right_feature is not None
    } | {program.priority_feature, *geometry_facts}
    for session in daily.index[mask]:
        if not (
            protocol.evaluation_start
            <= session.date()
            < protocol.evaluation_end_exclusive
        ):
            continue
        priority = matrix.values.at[session, program.priority_feature]
        dollar_volume = adv.at[session]
        if pd.isna(priority) or pd.isna(dollar_volume):
            continue
        entry_session = _next_session(session)
        if entry_session >= protocol.evaluation_end_exclusive:
            continue
        next_earnings = next(
            (
                item.earnings_session
                for item in earnings
                if item.known_session <= session.date()
                and (
                    item.superseded_session is None
                    or session.date() < item.superseded_session
                )
                and item.earnings_session >= entry_session
            ),
            None,
        )
        before_earnings = (
            _session_distance(entry_session, next_earnings)
            if next_earnings is not None
            else None
        )
        signal_facts = {
            name: SignalFact(
                value=_decimal_from_number(matrix.values.at[session, name], name),
                available_session=pd.Timestamp(
                    matrix.available_sessions.at[session, name]
                ).date(),
            )
            for name in sorted(used_features)
        }
        candidates.append(
            Candidate(
                strategy_revision_identity=strategy.identity,
                input_manifest_identity=protocol.input_manifest_identity,
                permanent_id=permanent_id,
                symbol=symbol,
                signal_session=session.date(),
                entry_session=entry_session,
                signal_close=_decimal_from_number(daily.at[session, "close"], "signal_close"),
                average_dollar_volume=_decimal_from_number(
                    dollar_volume,
                    "average_dollar_volume",
                ),
                scheduled_earnings_session=next_earnings,
                sessions_before_earnings=before_earnings,
                facts_as_of=MappingProxyType(dict(facts_as_of)),
                signal_facts=MappingProxyType(signal_facts),
                priority_value=_decimal_from_number(priority, "priority_value"),
            )
        )
    reverse = program.priority_direction == "descending"
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.signal_session,
                -item.priority_value if reverse else item.priority_value,
                item.tie_break,
            ),
        )
    )
