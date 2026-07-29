"""Pre-performance construction of the frozen swing-ranking study bundle."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from sts import calendar
from sts.swing_ranking.contracts import ADJUSTMENT_BASIS
from sts.swing_ranking.preflight import (
    ResolvedParquet,
    parquet_inventory_identity,
    security_identity_inputs_hash,
)
from sts.swing_ranking.source_inputs import sha256_bytes
from sts.swing_ranking.split import (
    derive_evaluation_split,
    evaluation_split_document,
)

PROTOCOL_VERSION = "retrospective-current-roster-2026-07-v1"
GRAMMAR_VERSION = "readable-multitimeframe-grid-v1"
OUTCOME_BUFFER_SESSIONS = 21


class StudyBundleViolation(ValueError):
    """The frozen non-performance metadata cannot form a complete study."""


def _fail(message: str) -> None:
    raise StudyBundleViolation(message)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value.strip()


def _date(value: object, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(_text(value, label))
    except ValueError as exc:
        _fail(f"{label} must be an ISO date: {exc}")
    raise AssertionError("unreachable")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _rows(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail(f"{label} must be a list")
    result = tuple(_mapping(item, f"{label} row") for item in value)
    if not result:
        _fail(f"{label} cannot be empty")
    return result


def read_roster(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _fail(f"roster is unreadable: {exc}")
    return _mapping(value, "roster")


def derive_study_dates(
    *,
    manifest: Mapping[str, Any],
    data_cutoff: dt.date,
) -> tuple[dt.date, dt.date, dt.date]:
    """Return evaluation start/end and source coverage end without price reads."""
    entries = _mapping(manifest.get("symbols"), "roster manifest symbols")
    starts = tuple(
        _date(_mapping(row, f"{symbol} manifest row").get("first_session"), "first_session")
        for symbol, row in entries.items()
    )
    lasts = tuple(
        _date(_mapping(row, f"{symbol} manifest row").get("last_session"), "last_session")
        for symbol, row in entries.items()
    )
    if not starts or set(lasts) != {data_cutoff}:
        _fail("every manifest member must end exactly at the data cutoff")
    evaluation_start = max(starts)
    sessions = tuple(
        item.date()
        for item in calendar.sessions_between(evaluation_start, data_cutoff)
    )
    if len(sessions) <= OUTCOME_BUFFER_SESSIONS:
        _fail("market-data range is too short for the 21-session outcome buffer")
    evaluation_end_exclusive = sessions[-OUTCOME_BUFFER_SESSIONS]
    derive_evaluation_split(evaluation_start, evaluation_end_exclusive)
    return (
        evaluation_start,
        evaluation_end_exclusive,
        data_cutoff + dt.timedelta(days=1),
    )


def build_exchange_calendar(
    evaluation_start: dt.date,
    coverage_end_exclusive: dt.date,
) -> dict[str, object]:
    sessions = calendar.sessions_between(
        evaluation_start,
        coverage_end_exclusive - dt.timedelta(days=1),
    )
    return {
        "schema_version": "swing-ranking-v1.exchange-calendar.v1",
        "exchange": "XNYS",
        "coverage_start": evaluation_start.isoformat(),
        "coverage_end_exclusive": coverage_end_exclusive.isoformat(),
        "sessions": [item.date().isoformat() for item in sessions],
    }


def build_corporate_actions(
    *,
    securities: Sequence[Mapping[str, Any]],
    evaluation_start: dt.date,
    coverage_end_exclusive: dt.date,
    data_cutoff: dt.date,
    roster_manifest_sha256: str,
) -> dict[str, object]:
    permanent_ids = sorted(
        _text(row.get("permanent_id"), "security permanent_id")
        for row in securities
    )
    if len(permanent_ids) != len(set(permanent_ids)):
        _fail("security master contains duplicate permanent IDs")
    return {
        "schema_version": "swing-ranking-v1.corporate-actions.v1",
        "adjustment_basis": ADJUSTMENT_BASIS,
        "adjustment_vintage": data_cutoff.isoformat(),
        "source": {
            "provider": "Yahoo adjusted daily history",
            "method": "auto_adjust=True; actions embedded in OHLC history",
            "roster_manifest_sha256": roster_manifest_sha256,
        },
        "coverage": [
            {
                "permanent_id": permanent_id,
                "coverage_start": evaluation_start.isoformat(),
                "coverage_end_exclusive": coverage_end_exclusive.isoformat(),
            }
            for permanent_id in permanent_ids
        ],
    }


def resolved_parquets_from_manifest(
    *,
    roster: Mapping[str, Any],
    manifest: Mapping[str, Any],
    securities: Sequence[Mapping[str, Any]],
) -> tuple[ResolvedParquet, ...]:
    raw_symbols = roster.get("symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        _fail("roster must contain symbols")
    symbols = tuple(_text(value, "roster symbol").upper() for value in raw_symbols)
    if roster.get("count") != len(symbols) or len(symbols) != len(set(symbols)):
        _fail("roster count or symbol uniqueness is invalid")
    entries = _mapping(manifest.get("symbols"), "roster manifest symbols")
    if set(entries) != set(symbols):
        _fail("roster manifest must exactly match the roster")
    permanent_by_symbol: dict[str, str] = {}
    for row in securities:
        symbol = _text(row.get("symbol"), "security symbol").upper()
        permanent_id = _text(row.get("permanent_id"), "security permanent_id")
        if symbol in permanent_by_symbol:
            _fail("security master contains duplicate symbols")
        permanent_by_symbol[symbol] = permanent_id
    if set(permanent_by_symbol) != set(symbols):
        _fail("security master must exactly match the roster")
    values: list[ResolvedParquet] = []
    for symbol in symbols:
        row = _mapping(entries[symbol], f"{symbol} manifest row")
        values.append(
            ResolvedParquet(
                permanent_id=permanent_by_symbol[symbol],
                symbol=symbol,
                file_sha256=_text(row.get("file_sha256"), f"{symbol} file_sha256"),
                first_session=_date(row.get("first_session"), f"{symbol} first_session"),
                last_session=_date(row.get("last_session"), f"{symbol} last_session"),
                n_bars=row.get("n_bars"),
            )
        )
    return tuple(values)


def _feature(
    name: str,
    timeframe: str,
    operation: str,
    source: str,
    lookback: int,
) -> dict[str, object]:
    return {
        "name": name,
        "timeframe": timeframe,
        "operation": operation,
        "source": source,
        "lookback": lookback,
    }


def _condition(
    left: str,
    comparator: str,
    *,
    right_feature: str | None = None,
    right_threshold: str | None = None,
) -> dict[str, object]:
    return {
        "left": left,
        "comparator": comparator,
        "right_feature": right_feature,
        "right_threshold": right_threshold,
    }


def _formula(
    kind: str,
    *,
    primary_fact: str | None,
    multiple: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "primary_fact": primary_fact,
        "secondary_fact": None,
        "multiple": multiple,
    }


def build_strategy_grid() -> list[dict[str, object]]:
    """Enumerate the initial readable grammar without inspecting performance."""
    contexts = (
        ("weekly", "ema", 13, "gt", "above"),
        ("weekly", "ema", 13, "lt", "below"),
        ("monthly", "ema", 6, "gt", "above"),
        ("monthly", "ema", 6, "lt", "below"),
    )
    triggers = (
        ("close-cross-ema5", "ema", 5),
        ("close-cross-sma10", "sma", 10),
        ("return5-cross-zero", "return", 5),
    )
    stops = (
        ("atr14x1", "entry_minus_fact_multiple", "daily_atr14", "1"),
        ("atr14x1p5", "entry_minus_fact_multiple", "daily_atr14", "1.5"),
        ("rolling-low10", "fact_value", "daily_rolling_low10", "1"),
        ("rolling-low20", "fact_value", "daily_rolling_low20", "1"),
    )
    targets = (
        ("risk1p75", "entry_plus_risk_multiple", None, "1.75"),
        ("risk2p5", "entry_plus_risk_multiple", None, "2.5"),
        ("rolling-high20", "fact_value", "daily_rolling_high20", "1"),
    )
    strategies: list[dict[str, object]] = []
    for timeframe, method, lookback, relation, relation_text in contexts:
        context_close = f"{timeframe}_close"
        context_average = f"{timeframe}_{method}{lookback}"
        for trigger_slug, trigger_operation, trigger_lookback in triggers:
            for stop_slug, stop_kind, stop_fact, stop_multiple in stops:
                for target_slug, target_kind, target_fact, target_multiple in targets:
                    features = [
                        _feature(context_close, timeframe, "raw", "close", 1),
                        _feature(
                            context_average,
                            timeframe,
                            method,
                            "close",
                            lookback,
                        ),
                        _feature("daily_close", "daily", "raw", "close", 1),
                        _feature("daily_return20", "daily", "return", "close", 20),
                    ]
                    if trigger_operation == "return":
                        trigger_left = "daily_return5"
                        features.append(
                            _feature(
                                trigger_left,
                                "daily",
                                "return",
                                "close",
                                trigger_lookback,
                            )
                        )
                        trigger_condition = _condition(
                            trigger_left,
                            "crosses_above",
                            right_threshold="0",
                        )
                        trigger_rule = "5-session return crosses above zero"
                    else:
                        trigger_left = "daily_close"
                        trigger_average = (
                            f"daily_{trigger_operation}{trigger_lookback}"
                        )
                        features.append(
                            _feature(
                                trigger_average,
                                "daily",
                                trigger_operation,
                                "close",
                                trigger_lookback,
                            )
                        )
                        trigger_condition = _condition(
                            trigger_left,
                            "crosses_above",
                            right_feature=trigger_average,
                        )
                        trigger_rule = (
                            f"daily close crosses above its "
                            f"{trigger_operation.upper()}{trigger_lookback}"
                        )
                    required_geometry_facts = {
                        value for value in (stop_fact, target_fact) if value is not None
                    }
                    if "daily_atr14" in required_geometry_facts:
                        features.append(
                            _feature("daily_atr14", "daily", "atr", "close", 14)
                        )
                    if "daily_rolling_low10" in required_geometry_facts:
                        features.append(
                            _feature(
                                "daily_rolling_low10",
                                "daily",
                                "rolling_min",
                                "low",
                                10,
                            )
                        )
                    if "daily_rolling_low20" in required_geometry_facts:
                        features.append(
                            _feature(
                                "daily_rolling_low20",
                                "daily",
                                "rolling_min",
                                "low",
                                20,
                            )
                        )
                    if "daily_rolling_high20" in required_geometry_facts:
                        features.append(
                            _feature(
                                "daily_rolling_high20",
                                "daily",
                                "rolling_max",
                                "high",
                                20,
                            )
                        )
                    context_slug = (
                        f"{timeframe}-{method}{lookback}-{relation_text}"
                    )
                    name = (
                        f"{context_slug}__{trigger_slug}__"
                        f"{stop_slug}__target-{target_slug}"
                    )
                    stop_rule = (
                        f"initial stop uses {stop_slug}; reject geometry beyond "
                        "the charter stop bound"
                    )
                    target_rule = (
                        f"entry target uses {target_slug}; reject planned "
                        "reward/risk at or below 1.5"
                    )
                    strategies.append(
                        {
                            "name": name,
                            "revision": "r1",
                            "readable_rules": [
                                (
                                    f"{timeframe} close is {relation_text} its "
                                    f"{method.upper()}{lookback}"
                                ),
                                trigger_rule,
                                "signal at a completed close; enter next session open",
                                stop_rule,
                                target_rule,
                                "exit at stop, target, or the 21st session close",
                            ],
                            "program": {
                                "version": "strategy-program-v1",
                                "features": features,
                                "where": [
                                    _condition(
                                        context_close,
                                        relation,
                                        right_feature=context_average,
                                    )
                                ],
                                "when": [trigger_condition],
                                "priority_feature": "daily_return20",
                                "priority_direction": "descending",
                                "average_dollar_volume_lookback": 20,
                            },
                            "geometry": {
                                "version": "entry-geometry-v1",
                                "stop": _formula(
                                    stop_kind,
                                    primary_fact=stop_fact,
                                    multiple=stop_multiple,
                                ),
                                "target": _formula(
                                    target_kind,
                                    primary_fact=target_fact,
                                    multiple=target_multiple,
                                ),
                                "hold_sessions": 21,
                            },
                        }
                    )
    return strategies


def source_fact(
    *,
    kind: str,
    content_hash: str,
    data_cutoff: dt.date,
    evaluation_start: dt.date,
    coverage_end_exclusive: dt.date,
) -> dict[str, str]:
    return {
        "kind": kind,
        "content_hash": content_hash,
        "as_of": data_cutoff.isoformat(),
        "coverage_start": evaluation_start.isoformat(),
        "coverage_end_exclusive": coverage_end_exclusive.isoformat(),
        "adjustment_basis": ADJUSTMENT_BASIS,
    }


def build_study_bundle(
    *,
    source_hashes: Mapping[str, str],
    evaluation_start: dt.date,
    evaluation_end_exclusive: dt.date,
    data_cutoff: dt.date,
    coverage_end_exclusive: dt.date,
    roster_as_of: str,
) -> dict[str, object]:
    split = derive_evaluation_split(evaluation_start, evaluation_end_exclusive)
    limitations = [
        {
            "kind": "current_roster_survivorship",
            "statement": (
                f"The accepted roster is the current roster as of {roster_as_of}; "
                "retrospective results therefore contain survivorship bias and "
                "are not untouched out-of-sample evidence."
            ),
        },
        {
            "kind": "symbol_history",
            "statement": (
                "Ticker intervals identify the Yahoo adjusted-cache namespace, "
                "not a complete point-in-time exchange ticker history."
            ),
        },
        {
            "kind": "delisting_coverage",
            "statement": (
                "The current-roster cache excludes securities delisted before "
                "roster construction and does not model their terminal outcomes."
            ),
        },
        {
            "kind": "adjustment_vintage",
            "statement": (
                f"Yahoo auto-adjusted OHLC values use the adjustment vintage "
                f"frozen through {data_cutoff.isoformat()}; later provider "
                "restatements are not represented."
            ),
        },
        {
            "kind": "historical_earnings_calendar",
            "statement": (
                "Historical report sessions and results are archived, but their "
                "prior scheduled dates were not reconstructed. Historical rows "
                "become known on the event session; the two-session entry blackout "
                "is enforceable only for separately archived schedule snapshots."
            ),
        },
    ]
    return {
        "evidence_window": "development",
        "protocol": {
            "study_id": "swing-ranking-v1",
            "protocol_version": PROTOCOL_VERSION,
            "evidence_label": "retrospective_screening",
            "evaluation_start": evaluation_start.isoformat(),
            "evaluation_end_exclusive": evaluation_end_exclusive.isoformat(),
            "data_cutoff": data_cutoff.isoformat(),
            "prospective_wall": coverage_end_exclusive.isoformat(),
            "evaluation_split": evaluation_split_document(split),
            "grammar_version": GRAMMAR_VERSION,
            "charter": {
                "starting_capital": "100000",
                "risk_fraction": "0.0075",
                "maximum_notional_fraction": "0.15",
                "maximum_positions": 8,
                "maximum_deployed_fraction": "0.80",
                "minimum_price": "5",
                "minimum_average_dollar_volume": "20000000",
                "maximum_stop_fraction": "0.12",
                "minimum_planned_reward_risk": "1.5",
                "minimum_hold_sessions": 3,
                "maximum_hold_sessions": 21,
                "earnings_blackout_sessions": 2,
                "long_only": True,
                "paper_only": True,
            },
            "source_facts": [
                source_fact(
                    kind=kind,
                    content_hash=source_hashes[kind],
                    data_cutoff=data_cutoff,
                    evaluation_start=evaluation_start,
                    coverage_end_exclusive=coverage_end_exclusive,
                )
                for kind in (
                    "security_master",
                    "current_roster",
                    "daily_market_data",
                    "corporate_actions",
                    "earnings_calendar",
                    "exchange_calendar",
                )
            ],
            "limitations": limitations,
        },
        "strategies": build_strategy_grid(),
    }


def build_source_hashes(
    *,
    roster_bytes: bytes,
    security_master_bytes: bytes,
    symbol_history_bytes: bytes,
    corporate_actions_bytes: bytes,
    earnings_calendar_bytes: bytes,
    exchange_calendar_bytes: bytes,
    resolved_parquets: Sequence[ResolvedParquet],
) -> dict[str, str]:
    return {
        "security_master": security_identity_inputs_hash(
            sha256_bytes(security_master_bytes),
            sha256_bytes(symbol_history_bytes),
        ),
        "current_roster": sha256_bytes(roster_bytes),
        "daily_market_data": parquet_inventory_identity(resolved_parquets),
        "corporate_actions": sha256_bytes(corporate_actions_bytes),
        "earnings_calendar": sha256_bytes(earnings_calendar_bytes),
        "exchange_calendar": sha256_bytes(exchange_calendar_bytes),
    }


__all__ = [
    "GRAMMAR_VERSION",
    "OUTCOME_BUFFER_SESSIONS",
    "PROTOCOL_VERSION",
    "StudyBundleViolation",
    "build_corporate_actions",
    "build_exchange_calendar",
    "build_source_hashes",
    "build_strategy_grid",
    "build_study_bundle",
    "derive_study_dates",
    "read_roster",
    "resolved_parquets_from_manifest",
]
