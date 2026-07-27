"""Deterministic, walled construction of the ML development matrices.

The only I/O in this module is explicit: callers provide a frozen roster,
price root, detector config, and output directory.  Every parquet read is
predicate-filtered before materialization and every returned row is checked
again against the locked development wall.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from sts import risk
from sts.ml.contracts import canonical_config_hash, canonical_json, row_identity
from sts.ml.features import (
    DETECTOR_FLAG_FEATURES,
    DOLLAR_VOLUME_MEDIAN_WINDOWS,
    MA_WINDOWS,
    RETURN_HORIZONS,
    SPY_RELATIVE_HORIZONS,
    VOLATILITY_WINDOWS,
    VOLUME_MEDIAN_WINDOWS,
    FeatureFact,
    feature_names,
    make_feature_snapshot,
)
from sts.ml.labels import Bar, calculate_targets, fixed_geometry, simulate_fixed_policy
from sts.ml.units import (
    EligibilityFacts,
    TrackBEvent,
    deduplicate_track_b,
    evaluate_eligibility,
)
from sts.ml.walls import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_START_INCLUSIVE,
    WallViolation,
    require_development_session,
)
from sts.signals import resolve_detector

DATA_SCHEMA = "ml-development-data-v1"
MANIFEST_SCHEMA = "ml-development-manifest-v1"
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
TRACK_B_CELL_TO_FLAG = {
    "tp-rsi6-w5": "detector_flag_tp_rsi6_w5",
    "tp-rsi10-w7": "detector_flag_tp_rsi10_w7",
    "tp-rsi14-w10": "detector_flag_tp_rsi14_w10",
    "vc-tight": "detector_flag_vc_tight",
    "vc-core": "detector_flag_vc_core",
    "vc-broad": "detector_flag_vc_broad",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(
        frame[list(REQUIRED_PRICE_COLUMNS)],
        index=True,
    ).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def load_frozen_roster(path: Path | str) -> tuple[str, ...]:
    """Load the exact frozen development roster, rejecting ambiguity."""
    raw = yaml.safe_load(Path(path).read_text())
    symbols = raw.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("frozen roster must contain a non-empty symbols list")
    normalized = tuple(str(symbol).strip().upper() for symbol in symbols)
    if any(not symbol for symbol in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("frozen roster symbols must be unique and non-empty")
    return tuple(sorted(normalized))


def load_development_frames(
    root: Path | str,
    roster: Sequence[str],
    *,
    start_inclusive: dt.date = DEVELOPMENT_START_INCLUSIVE,
    end_exclusive: dt.date = DEVELOPMENT_END_EXCLUSIVE,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Predicate-filter and validate adjusted OHLCV for the frozen roster."""
    if start_inclusive != DEVELOPMENT_START_INCLUSIVE:
        raise WallViolation("development start must remain locked at 2010-01-01")
    if end_exclusive != DEVELOPMENT_END_EXCLUSIVE:
        raise WallViolation("development end must remain locked at 2024-01-01")
    price_root = Path(root)
    filters = [
        ("date", ">=", pd.Timestamp(start_inclusive)),
        ("date", "<", pd.Timestamp(end_exclusive)),
    ]
    frames: dict[str, pd.DataFrame] = {}
    inventory: list[dict[str, Any]] = []
    for symbol in sorted(set(roster)):
        path = price_root / f"{symbol}.parquet"
        if not path.exists():
            inventory.append(
                {"symbol": symbol, "status": "not_run_input_failure", "reason": "missing"}
            )
            continue
        try:
            frame = pd.read_parquet(
                path,
                columns=list(REQUIRED_PRICE_COLUMNS),
                filters=filters,
            )
        except Exception as exc:  # noqa: BLE001 - input failure is evidence
            inventory.append(
                {
                    "symbol": symbol,
                    "status": "not_run_input_failure",
                    "reason": f"unreadable:{type(exc).__name__}",
                }
            )
            continue
        if not isinstance(frame.index, pd.DatetimeIndex):
            inventory.append(
                {
                    "symbol": symbol,
                    "status": "rejected_leakage_risk",
                    "reason": "DatetimeIndex required",
                }
            )
            continue
        frame = frame.sort_index()
        if frame.index.has_duplicates:
            inventory.append(
                {
                    "symbol": symbol,
                    "status": "rejected_leakage_risk",
                    "reason": "duplicate sessions",
                }
            )
            continue
        returned_dates = tuple(frame.index.date)
        if any(day < start_inclusive or day >= end_exclusive for day in returned_dates):
            raise WallViolation(f"predicate backend returned out-of-wall row for {symbol}")
        if frame.empty:
            inventory.append(
                {
                    "symbol": symbol,
                    "status": "not_run_input_failure",
                    "reason": "no development rows",
                }
            )
            continue
        frames[symbol] = frame
        inventory.append(
            {
                "symbol": symbol,
                "status": "survivor_only_development",
                "rows": len(frame),
                "first_session": returned_dates[0].isoformat(),
                "last_session": returned_dates[-1].isoformat(),
                "filtered_content_sha256": _frame_hash(frame),
            }
        )
    if "SPY" not in frames:
        raise RuntimeError("SPY is required for locked relative features and T2")
    return frames, inventory


def load_locked_detector_cells(path: Path | str) -> tuple[dict[str, Any], ...]:
    """Return the six exact non-catalyst Phase-3 detector cells."""
    config = yaml.safe_load(Path(path).read_text())
    if config.get("schema") != "success-v2.phase3-screen.v1":
        raise ValueError("unexpected Phase-3 detector config schema")
    cells = []
    for family in config["families"].values():
        if family["detector"] not in {"trend_pullback", "vol_squeeze"}:
            continue
        for cell in family["cells"]:
            if cell["id"] not in TRACK_B_CELL_TO_FLAG:
                raise ValueError(f"unexpected locked detector cell {cell['id']}")
            cells.append(
                {
                    "cell_id": cell["id"],
                    "detector": family["detector"],
                    "config_name": cell["config_name"],
                    "params": cell["params"],
                }
            )
    if {cell["cell_id"] for cell in cells} != set(TRACK_B_CELL_TO_FLAG):
        raise ValueError("locked detector config must contain exactly six cells")
    return tuple(sorted(cells, key=lambda cell: cell["cell_id"]))


def detect_locked_events(
    frames: Mapping[str, pd.DataFrame],
    cells: Sequence[Mapping[str, Any]],
) -> tuple[TrackBEvent, ...]:
    events: list[TrackBEvent] = []
    for symbol in sorted(frames):
        frame = frames[symbol]
        for cell in cells:
            detector = resolve_detector(str(cell["config_name"]))
            found = detector(
                symbol,
                frame,
                dict(cell["params"]),
                str(cell["config_name"]),
            )
            for event in found:
                require_development_session(event.date)
                events.append(
                    TrackBEvent(
                        symbol=symbol,
                        signal_session=event.date,
                        detector_source=str(cell["cell_id"]),
                    )
                )
    return tuple(
        sorted(events, key=lambda item: (item.signal_session, item.symbol, item.detector_source))
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0.0, np.nan)


def _feature_frame(
    frame: pd.DataFrame,
    spy: pd.DataFrame,
    event_flags: Mapping[tuple[str, dt.date], set[str]],
    symbol: str,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    open_price = frame["open"].astype(float)
    volume = frame["volume"].astype(float)
    dollar_volume = close * volume
    result = pd.DataFrame(index=frame.index)

    returns: dict[int, pd.Series] = {}
    for horizon in RETURN_HORIZONS:
        returns[horizon] = close.pct_change(horizon, fill_method=None)
        result[f"adjusted_return_{horizon}"] = returns[horizon]
    for window in MA_WINDOWS:
        result[f"close_to_ma_{window}"] = (
            _safe_ratio(close, close.rolling(window, min_periods=window).mean()) - 1
        )
    return_1 = close.pct_change(fill_method=None)
    for window in VOLATILITY_WINDOWS:
        result[f"realized_volatility_{window}"] = return_1.rolling(
            window, min_periods=window
        ).std(ddof=1)
    atr14 = risk.atr(frame, window=14)
    result["atr14_over_close"] = _safe_ratio(atr14, close)
    result["atr14_percentile_60"] = atr14.rolling(
        60, min_periods=60
    ).rank(method="average", pct=True)
    result["range_over_close"] = _safe_ratio(high - low, close)
    result["close_location_in_range"] = _safe_ratio(close - low, high - low)
    gap = _safe_ratio(open_price, close.shift(1)) - 1
    result["gap_open_to_prior_close"] = gap
    result["gap_abs_open_to_prior_close"] = gap.abs()
    for window in VOLUME_MEDIAN_WINDOWS:
        result[f"volume_to_median_{window}"] = _safe_ratio(
            volume, volume.rolling(window, min_periods=window).median()
        )
    for window in DOLLAR_VOLUME_MEDIAN_WINDOWS:
        result[f"dollar_volume_to_median_{window}"] = _safe_ratio(
            dollar_volume,
            dollar_volume.rolling(window, min_periods=window).median(),
        )

    spy_close = spy["close"].astype(float).reindex(frame.index)
    for horizon in SPY_RELATIVE_HORIZONS:
        spy_return = spy_close.pct_change(horizon, fill_method=None)
        result[f"spy_relative_return_{horizon}"] = returns[horizon] - spy_return
    spy_ma = spy_close.rolling(200, min_periods=200).mean()
    result["spy_above_ma_200"] = (spy_close > spy_ma).astype(float).where(spy_ma.notna())
    for detector, flag_name in TRACK_B_CELL_TO_FLAG.items():
        result[flag_name] = [
            int(detector in event_flags.get((symbol, session), set()))
            for session in frame.index.date
        ]
    return result.replace([np.inf, -np.inf], np.nan), atr14, dollar_volume.rolling(
        20, min_periods=20
    ).mean()


def _forward_bars(frame: pd.DataFrame, signal_iloc: int) -> tuple[Bar, ...]:
    rows = frame.iloc[signal_iloc + 1 : signal_iloc + 17]
    return tuple(
        Bar(
            session=index.date(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for index, row in rows.iterrows()
    )


def _spy_h15_return(
    spy: pd.DataFrame,
    entry_session: dt.date,
    horizon_session: dt.date,
) -> float:
    try:
        entry = float(spy.loc[pd.Timestamp(entry_session), "open"])
        horizon = float(spy.loc[pd.Timestamp(horizon_session), "close"])
    except KeyError as exc:
        raise ValueError("SPY lacks a matching entry/h15 session") from exc
    if not math.isfinite(entry) or not math.isfinite(horizon) or entry <= 0:
        raise ValueError("SPY matching return is invalid")
    return horizon / entry - 1


def build_development_matrices(
    frames: Mapping[str, pd.DataFrame],
    detector_events: Sequence[TrackBEvent],
    *,
    config_hash: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build Track A/B rows without fitting a transform or model."""
    if not frames:
        raise ValueError("frames must not be empty")
    for symbol, frame in frames.items():
        if any(
            day < DEVELOPMENT_START_INCLUSIVE or day >= DEVELOPMENT_END_EXCLUSIVE
            for day in frame.index.date
        ):
            raise WallViolation(f"supplied frame crosses development wall: {symbol}")
    spy = frames.get("SPY")
    if spy is None:
        raise ValueError("SPY frame is required")
    event_sources: dict[tuple[str, dt.date], set[str]] = {}
    for event in detector_events:
        event_sources.setdefault((event.symbol, event.signal_session), set()).add(
            event.detector_source
        )

    raw_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    for symbol in sorted(frames):
        frame = frames[symbol]
        features, atr14, adv20 = _feature_frame(frame, spy, event_sources, symbol)
        for signal_iloc in range(len(frame)):
            signal_session = frame.index[signal_iloc].date()
            require_development_session(signal_session)
            causal_bars = signal_iloc + 1
            next_open = (
                float(frame["open"].iloc[signal_iloc + 1])
                if signal_iloc + 1 < len(frame)
                else None
            )
            atr_value = (
                float(atr14.iloc[signal_iloc])
                if pd.notna(atr14.iloc[signal_iloc])
                else None
            )
            geometry_valid = False
            if next_open is not None and atr_value is not None:
                try:
                    fixed_geometry(next_open, atr_value)
                    geometry_valid = True
                except ValueError:
                    pass
            complete = signal_iloc + 16 < len(frame)
            decision = evaluate_eligibility(
                EligibilityFacts(
                    symbol=symbol,
                    signal_session=signal_session,
                    in_frozen_roster=True,
                    causal_bars=causal_bars,
                    adjusted_close=float(frame["close"].iloc[signal_iloc]),
                    average_dollar_volume_20=(
                        float(adv20.iloc[signal_iloc])
                        if pd.notna(adv20.iloc[signal_iloc])
                        else None
                    ),
                    next_session_open=next_open,
                    geometry_valid=geometry_valid,
                    label_path_complete=complete,
                )
            )
            if not decision.eligible:
                rejection_counts[decision.reason or "unknown"] += 1
                continue
            try:
                feature_row = features.iloc[signal_iloc]
                facts = {
                    name: FeatureFact(
                        None
                        if pd.isna(feature_row[name])
                        else float(feature_row[name]),
                        signal_session,
                    )
                    for name in feature_names("A")
                }
                snapshot = make_feature_snapshot(
                    "A",
                    signal_session,
                    causal_bars=causal_bars,
                    facts=facts,
                )
                forward = _forward_bars(frame, signal_iloc)
                outcome = simulate_fixed_policy(
                    signal_session=signal_session,
                    atr14=float(atr_value),
                    forward_bars=forward,
                )
                spy_return = _spy_h15_return(
                    spy,
                    outcome.entry_session,
                    forward[15].session,
                )
            except (ValueError, KeyError) as exc:
                rejection_counts[f"row_build:{type(exc).__name__}"] += 1
                continue
            raw_rows.append(
                {
                    "schema": DATA_SCHEMA,
                    "config_hash": config_hash,
                    "row_id": row_identity("A", symbol, signal_session),
                    "track": "A",
                    "symbol": symbol,
                    "signal_session": signal_session,
                    "label_end_session": forward[15].session,
                    "entry_session": outcome.entry_session,
                    "exit_session": outcome.exit_session,
                    "selection_status": "eligible",
                    "detector_sources": "|".join(
                        sorted(event_sources.get((symbol, signal_session), set()))
                    ),
                    "causal_bars": causal_bars,
                    "entry_fill": outcome.entry_fill,
                    "stop_initial": outcome.stop_initial,
                    "target_initial": outcome.target_initial,
                    "initial_risk_pct": (
                        (outcome.entry_fill - outcome.stop_initial) / outcome.entry_fill
                    ),
                    "planned_r": (
                        (outcome.target_initial - outcome.entry_fill)
                        / (outcome.entry_fill - outcome.stop_initial)
                    ),
                    "exit_reason": outcome.exit_reason,
                    "hold_sessions": outcome.hold_sessions,
                    "gross_profit": outcome.gross_profit,
                    "friction_base": outcome.friction_base,
                    "friction_2x": outcome.friction_2x,
                    "net_r_base": outcome.net_r_base,
                    "net_r_2x": outcome.net_r_2x,
                    "raw_h15_return": outcome.raw_h15_return,
                    "spy_h15_return": spy_return,
                    **snapshot.values,
                }
            )
    if not raw_rows:
        raise RuntimeError("no eligible Track A development rows")
    track_a = pd.DataFrame(raw_rows).sort_values(
        ["signal_session", "symbol"], kind="mergesort"
    )
    if track_a.duplicated(["symbol", "signal_session"]).any():
        raise RuntimeError("duplicate Track A keys")
    medians = track_a.groupby("signal_session", sort=True)["net_r_2x"].transform("median")
    targets = [
        calculate_targets(
            net_r_2x=float(row.net_r_2x),
            track_a_median_net_r_2x=float(median),
            raw_h15_return=float(row.raw_h15_return),
            spy_h15_return=float(row.spy_h15_return),
        )
        for row, median in zip(track_a.itertuples(index=False), medians)
    ]
    track_a["relative_net_r_2x"] = [target.relative_net_r_2x for target in targets]
    track_a["spy_residual_h15"] = [target.spy_residual_h15 for target in targets]
    track_a["useful_opportunity"] = [target.useful_opportunity for target in targets]

    track_a_date_counts = track_a.groupby("signal_session")["symbol"].transform("size")
    track_a["selection_status"] = np.where(
        track_a_date_counts >= 20,
        "eligible",
        "not_run_inadequate_cross_section",
    )

    track_a_keys = set(
        zip(track_a["symbol"], track_a["signal_session"], strict=True)
    )
    eligible_detector_events = tuple(
        event
        for event in detector_events
        if (event.symbol, event.signal_session) in track_a_keys
    )
    b_units = deduplicate_track_b(eligible_detector_events)
    b_lookup = {(unit.symbol, unit.signal_session): unit for unit in b_units}
    track_b = track_a[
        [
            (row.symbol, row.signal_session) in b_lookup
            for row in track_a[["symbol", "signal_session"]].itertuples(index=False)
        ]
    ].copy()
    if not track_b.empty:
        track_b["track"] = "B"
        track_b["row_id"] = [
            row_identity("B", row.symbol, row.signal_session)
            for row in track_b[["symbol", "signal_session"]].itertuples(index=False)
        ]
        track_b["detector_sources"] = [
            "|".join(b_lookup[(row.symbol, row.signal_session)].detector_sources)
            for row in track_b[["symbol", "signal_session"]].itertuples(index=False)
        ]
        track_b["selection_status"] = [
            b_lookup[(row.symbol, row.signal_session)].selection_status
            for row in track_b[["symbol", "signal_session"]].itertuples(index=False)
        ]
        track_b = track_b.drop(columns=list(DETECTOR_FLAG_FEATURES))

    for matrix in (track_a, track_b):
        for column in ("signal_session", "label_end_session", "entry_session", "exit_session"):
            if column in matrix:
                matrix[column] = pd.to_datetime(matrix[column])
    track_a_parent_keys = set(
        zip(track_a["symbol"], track_a["signal_session"], strict=True)
    )
    track_b_keys = set(
        zip(track_b["symbol"], track_b["signal_session"], strict=True)
    )
    checks = {
        "track_a_duplicate_keys": int(
            track_a.duplicated(["symbol", "signal_session"]).sum()
        ),
        "track_b_duplicate_keys": int(
            track_b.duplicated(["symbol", "signal_session"]).sum()
        ),
        "track_b_missing_track_a_parent": len(track_b_keys - track_a_parent_keys),
        "post_wall_rows_observed": int(
            (track_a["signal_session"] >= pd.Timestamp(DEVELOPMENT_END_EXCLUSIVE)).sum()
        ),
        "rejections": dict(sorted(rejection_counts.items())),
    }
    if any(
        checks[key]
        for key in (
            "track_a_duplicate_keys",
            "track_b_duplicate_keys",
            "track_b_missing_track_a_parent",
            "post_wall_rows_observed",
        )
    ):
        raise RuntimeError(f"matrix integrity failure: {checks}")
    return (
        track_a.reset_index(drop=True),
        track_b.reset_index(drop=True),
        checks,
    )


def development_config(
    roster: Sequence[str],
    detector_cells: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": DATA_SCHEMA,
        "development_start_inclusive": DEVELOPMENT_START_INCLUSIVE,
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "roster": sorted(roster),
        "features_a": list(feature_names("A")),
        "features_b": list(feature_names("B")),
        "detector_cells": list(detector_cells),
        "label_policy": {
            "entry": "next_session_open",
            "atr_window": 14,
            "stop_atr": 2.0,
            "target_atr": 4.0,
            "time_stop_sessions": 15,
            "base_bps_per_side": 5.0,
            "base_per_order_usd": 1.0,
            "double_bps_per_side": 10.0,
            "double_per_order_usd": 2.0,
        },
    }


def _matrix_summary(matrix: pd.DataFrame) -> dict[str, Any]:
    dates = matrix["signal_session"].dt.date
    feature_columns = [
        column for column in feature_names(matrix["track"].iloc[0])
        if column in matrix
    ] if not matrix.empty else []
    return {
        "rows": len(matrix),
        "unique_dates": int(dates.nunique()) if len(matrix) else 0,
        "unique_symbols": int(matrix["symbol"].nunique()) if len(matrix) else 0,
        "first_session": min(dates).isoformat() if len(matrix) else None,
        "last_session": max(dates).isoformat() if len(matrix) else None,
        "selection_status_counts": (
            dict(sorted(matrix["selection_status"].value_counts().to_dict().items()))
            if len(matrix)
            else {}
        ),
        "row_counts_by_date": (
            {
                pd.Timestamp(day).date().isoformat(): int(count)
                for day, count in matrix.groupby("signal_session", sort=True).size().items()
            }
            if len(matrix)
            else {}
        ),
        "row_counts_by_symbol": (
            {
                str(symbol): int(count)
                for symbol, count in matrix.groupby("symbol", sort=True).size().items()
            }
            if len(matrix)
            else {}
        ),
        "missing_by_feature": {
            column: int(matrix[column].isna().sum()) for column in feature_columns
        },
    }


def _write_parquet_deterministic(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=3,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
    )


def _write_matrix_shards(
    frame: pd.DataFrame,
    output: Path,
    track_name: str,
) -> list[dict[str, Any]]:
    """Write stable year shards so every versioned file stays reviewable."""
    for stale in output.glob(f"{track_name}_*.parquet"):
        stale.unlink()
    shards = []
    years = sorted(frame["signal_session"].dt.year.unique()) if len(frame) else []
    for year in years:
        shard = frame[frame["signal_session"].dt.year == year]
        path = output / f"{track_name}_{year}.parquet"
        _write_parquet_deterministic(shard, path)
        shards.append(
            {
                "year": int(year),
                "path": path.name,
                "rows": len(shard),
                "sha256": _sha256_file(path),
            }
        )
    return shards


def _dataset_sha256(shards: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "year": int(shard["year"]),
            "path": str(shard["path"]),
            "rows": int(shard["rows"]),
            "sha256": str(shard["sha256"]),
        }
        for shard in shards
    ]
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def write_development_artifacts(
    *,
    output_dir: Path | str,
    track_a: pd.DataFrame,
    track_b: pd.DataFrame,
    source_inventory: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    checks: Mapping[str, Any],
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    track_a_shards = _write_matrix_shards(track_a, output, "track_a")
    track_b_shards = _write_matrix_shards(track_b, output, "track_b")
    config_hash = canonical_config_hash(config)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "config_hash": config_hash,
        "walls": {
            "development_start_inclusive": DEVELOPMENT_START_INCLUSIVE.isoformat(),
            "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE.isoformat(),
            "post_wall_rows_observed": 0,
        },
        "data_feasibility": {
            "adjusted_ohlcv": "survivor_only_development",
            "frozen_roster": "survivor_only_development",
            "catalysts": "not_run_input_failure",
            "point_in_time_membership": "rejected_leakage_risk",
            "delisting_history": "rejected_leakage_risk",
            "adjusted_history_vintage": "survivor_only_development",
        },
        "limitations": [
            "Historical roster is survivor-biased and is not clean OOS evidence.",
            "Adjusted price history may reflect source revisions after the observed session.",
            "Point-in-time membership, security-type history, and delistings are uncertified.",
            "Catalyst features are excluded; missing catalyst facts are never encoded as zero.",
        ],
        "source_inventory": list(source_inventory),
        "checks": dict(checks),
        "matrices": {
            "track_a": {
                **_matrix_summary(track_a),
                "shards": track_a_shards,
                "sha256": _dataset_sha256(track_a_shards),
            },
            "track_b": {
                **_matrix_summary(track_b),
                "shards": track_b_shards,
                "sha256": _dataset_sha256(track_b_shards),
            },
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def build_from_paths(
    *,
    roster_path: Path | str,
    price_root: Path | str,
    detector_config_path: Path | str,
    output_dir: Path | str,
) -> dict[str, Any]:
    roster = load_frozen_roster(roster_path)
    cells = load_locked_detector_cells(detector_config_path)
    config = development_config(roster, cells)
    config_hash = canonical_config_hash(config)
    frames, inventory = load_development_frames(price_root, roster)
    events = detect_locked_events(frames, cells)
    track_a, track_b, checks = build_development_matrices(
        frames, events, config_hash=config_hash
    )
    return write_development_artifacts(
        output_dir=output_dir,
        track_a=track_a,
        track_b=track_b,
        source_inventory=inventory,
        config=config,
        checks=checks,
    )


def verify_artifact_determinism(
    *,
    roster_path: Path | str,
    price_root: Path | str,
    detector_config_path: Path | str,
    output_dir: Path | str,
) -> dict[str, Any]:
    """Build twice and require byte-identical manifests and matrices."""
    first = build_from_paths(
        roster_path=roster_path,
        price_root=price_root,
        detector_config_path=detector_config_path,
        output_dir=output_dir,
    )
    with tempfile.TemporaryDirectory(prefix="sts-ml-development-") as temporary:
        second = build_from_paths(
            roster_path=roster_path,
            price_root=price_root,
            detector_config_path=detector_config_path,
            output_dir=temporary,
        )
        first_names = sorted(
            path.name for path in Path(output_dir).glob("*") if path.is_file()
        )
        second_names = sorted(
            path.name for path in Path(temporary).glob("*") if path.is_file()
        )
        if first_names != second_names:
            raise RuntimeError("nondeterministic development artifact file set")
        for name in first_names:
            first_path = Path(output_dir) / name
            second_path = Path(temporary) / name
            if first_path.read_bytes() != second_path.read_bytes():
                raise RuntimeError(f"nondeterministic development artifact: {name}")
    if canonical_json(first) != canonical_json(second):
        raise RuntimeError("nondeterministic development manifest content")
    return first
