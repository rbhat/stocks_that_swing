"""IS-only success-v2 discovery with a hard pre-2024 data wall.

The loader predicate-filters parquet before returning a frame and refuses
any returned bar on or after ``end_exclusive``.  The screen consumes only
the supplied frames; it has no fallback fetch path and never opens a
post-wall report.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from sts import risk
from sts.forward.broker import cost_side
from sts.models import SignalEvent
from sts.signals import resolve_detector
from sts.study.success_gate import entry_geometry, summarize_events

ARTIFACT_SCHEMA = "success-v2.phase3-discovery.v1"
SUPPORTED_DETECTORS = frozenset({"trend_pullback", "vol_squeeze"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def load_config(path: Path | str) -> dict:
    config = yaml.safe_load(Path(path).read_text())
    if config.get("schema") != "success-v2.phase3-screen.v1":
        raise ValueError("unexpected Phase-3 screen schema")
    return config


def _frame_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(
        frame[["open", "high", "low", "close", "volume"]],
        index=True,
    ).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def load_is_frames(
    root: Path | str,
    *,
    start_inclusive: dt.date,
    end_exclusive: dt.date,
    minimum_filtered_rows: int,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Load only predicate-filtered IS rows and return a content manifest."""
    root = Path(root)
    frames: dict[str, pd.DataFrame] = {}
    manifest: list[dict] = []
    filters = [
        ("date", ">=", pd.Timestamp(start_inclusive)),
        ("date", "<", pd.Timestamp(end_exclusive)),
    ]
    for path in sorted(root.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path, filters=filters)
        except Exception as exc:  # noqa: BLE001 — unreadable input is durable evidence
            manifest.append(
                {
                    "symbol": path.stem,
                    "status": "unreadable",
                    "reason": str(exc),
                }
            )
            continue
        if not isinstance(frame.index, pd.DatetimeIndex):
            manifest.append(
                {
                    "symbol": path.stem,
                    "status": "invalid_index",
                    "reason": "DatetimeIndex required",
                }
            )
            continue
        if not frame.empty and max(frame.index.date) >= end_exclusive:
            raise RuntimeError(
                f"data-wall violation: {path} returned a bar >= {end_exclusive}"
            )
        if not frame.empty and min(frame.index.date) < start_inclusive:
            raise RuntimeError(
                f"data-wall violation: {path} returned a bar < {start_inclusive}"
            )
        if len(frame) < minimum_filtered_rows:
            manifest.append(
                {
                    "symbol": path.stem,
                    "status": "insufficient_history",
                    "rows": len(frame),
                }
            )
            continue
        clean = frame.sort_index()
        frames[path.stem] = clean
        manifest.append(
            {
                "symbol": path.stem,
                "status": "loaded",
                "rows": len(clean),
                "first_date": clean.index[0].date().isoformat(),
                "last_date": clean.index[-1].date().isoformat(),
                "filtered_content_sha256": _frame_hash(clean),
            }
        )
    if not frames:
        raise RuntimeError("no adequate pre-wall price frames")
    return frames, manifest


def _spy_regimes(frames: dict[str, pd.DataFrame]) -> dict[dt.date, str]:
    spy = frames.get("SPY")
    if spy is None or spy.empty:
        return {}
    ma = spy["close"].rolling(200, min_periods=200).mean()
    return {
        date: ("spy_above_200d" if close > avg else "spy_at_or_below_200d")
        for date, close, avg in zip(spy.index.date, spy["close"], ma)
        if math.isfinite(float(avg))
    }


def _simulate_dates(
    frames: dict[str, pd.DataFrame],
    dates: list[tuple[str, dt.date]],
    *,
    config_name: str,
    geometry: dict,
    costs: dict,
    regimes: dict[dt.date, str],
) -> tuple[list[dict], list[float], dict[str, int]]:
    events: list[dict] = []
    raw_h15: list[float] = []
    rejects: Counter[str] = Counter()
    atr_cache: dict[str, pd.Series] = {}
    iloc_cache: dict[str, dict[dt.date, int]] = {}

    for symbol, signal_date in dates:
        frame = frames.get(symbol)
        if frame is None or frame.empty:
            rejects["missing_frame"] += 1
            continue
        if symbol not in iloc_cache:
            iloc_cache[symbol] = {
                date: index for index, date in enumerate(frame.index.date)
            }
        iloc_by_date = iloc_cache[symbol]
        signal_iloc = iloc_by_date.get(signal_date)
        if signal_iloc is None:
            rejects["missing_signal_bar"] += 1
            continue
        entry_iloc = signal_iloc + 1
        h15_iloc = entry_iloc + 15
        if h15_iloc >= len(frame):
            rejects["insufficient_forward_15"] += 1
            continue
        entry = float(frame["open"].iloc[entry_iloc])
        if not math.isfinite(entry) or entry <= 0:
            rejects["invalid_entry"] += 1
            continue
        if symbol not in atr_cache:
            atr_cache[symbol] = risk.atr(
                frame,
                window=int(geometry["atr_window"]),
            )
        atr_series = atr_cache[symbol]
        atr_value = float(atr_series.iloc[signal_iloc])
        if not math.isfinite(atr_value) or atr_value <= 0:
            rejects["atr_not_warm"] += 1
            continue
        stop = risk.atr_stop(
            entry,
            atr_value,
            float(geometry["stop_atr_multiple"]),
        )
        target = risk.atr_target(
            entry,
            atr_value,
            float(geometry["target_atr_multiple"]),
        )
        judged = entry_geometry(entry, stop, target)
        if not judged["valid"]:
            rejects[f"geometry:{judged['reason']}"] += 1
            continue
        qty = risk.position_size(risk.START_CAPITAL, entry, stop)
        if qty <= 0:
            rejects["size_zero"] += 1
            continue
        try:
            position = risk.Position(
                symbol=symbol,
                entry=entry,
                shares=qty,
                stop=stop,
                target=target,
                opened=frame.index[entry_iloc].date(),
                config=config_name,
            )
        except (ValueError, risk.RuleViolation) as exc:
            rejects[f"position:{exc}"] += 1
            continue

        exit_price = None
        exit_reason = None
        exit_iloc = None
        lows: list[float] = []
        for index in range(entry_iloc, min(len(frame), entry_iloc + 15)):
            bar = frame.iloc[index]
            lows.append(float(bar["low"]))
            resolved = risk.manage_bar(
                position,
                bar_open=float(bar["open"]),
                bar_high=float(bar["high"]),
                bar_low=float(bar["low"]),
                bar_close=float(bar["close"]),
            )
            if resolved:
                exit_reason, exit_price, _ = resolved[0]
                exit_iloc = index
                break
        if exit_price is None or exit_iloc is None:
            rejects["unresolved_by_time_stop"] += 1
            continue

        gross_profit = qty * (exit_price - entry)
        friction = cost_side(entry, qty, bps=float(costs["bps_per_side"])) + cost_side(
            exit_price,
            qty,
            bps=float(costs["bps_per_side"]),
        )
        # cost_side's default flat fee is explicit in the config; adjust it
        # when a non-default value is selected.
        friction += 2 * (float(costs["per_order_usd"]) - 1.0)
        initial_risk = entry - stop
        mae_r = max(0.0, (entry - min(lows)) / initial_risk)
        raw_return = float(frame["close"].iloc[h15_iloc]) / entry - 1.0
        raw_h15.append(raw_return)
        events.append(
            {
                "symbol": symbol,
                "signal_date": signal_date.isoformat(),
                "entry_date": frame.index[entry_iloc].date().isoformat(),
                "exit_date": frame.index[exit_iloc].date().isoformat(),
                "entry_fill": entry,
                "stop_initial": stop,
                "target_initial": target,
                "gross_profit": gross_profit,
                "friction_base": friction,
                "hold_sessions": exit_iloc - entry_iloc + 1,
                "mae_r": mae_r,
                "raw_h15_return": raw_return,
                "exit_reason": exit_reason,
                "year": signal_date.year,
                "regime": regimes.get(signal_date, "spy_regime_unavailable"),
            }
        )
    return events, raw_h15, dict(sorted(rejects.items()))


def _detected_dates(
    frames: dict[str, pd.DataFrame],
    *,
    detector: str,
    config_name: str,
    params: dict,
    end_exclusive: dt.date,
) -> list[tuple[str, dt.date]]:
    if detector not in SUPPORTED_DETECTORS:
        raise ValueError(f"unsupported discovery detector: {detector}")
    detect = resolve_detector(config_name)
    dates: list[tuple[str, dt.date]] = []
    for symbol in sorted(frames):
        frame = frames[symbol]
        found: list[SignalEvent] = detect(symbol, frame, params, config_name)
        for event in found:
            if event.date >= end_exclusive:
                raise RuntimeError(
                    f"detector emitted post-wall event {event.date}"
                )
            dates.append((symbol, event.date))
    return sorted(dates, key=lambda value: (value[1], value[0]))


def _matched_random_dates(
    frames: dict[str, pd.DataFrame],
    detected: list[tuple[str, dt.date]],
    *,
    seed: int,
) -> list[tuple[str, dt.date]]:
    """One deterministic random eligible session for each detected symbol."""
    rng = np.random.default_rng(seed)
    result: list[tuple[str, dt.date]] = []
    eligible: dict[str, list[dt.date]] = {}
    for symbol, frame in frames.items():
        # 252-session warmup and 16 sessions after the signal for entry+h15.
        eligible[symbol] = list(frame.index.date[252:-16])
    for symbol, _ in detected:
        choices = eligible.get(symbol, [])
        if choices:
            result.append((symbol, choices[int(rng.integers(0, len(choices)))]))
    return result


def _slice(events: list[dict], field: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for event in events:
        grouped.setdefault(str(event[field]), []).append(event)
    result = {}
    for label, rows in sorted(grouped.items()):
        base = [row["gross_profit"] - row["friction_base"] for row in rows]
        doubled = [
            row["gross_profit"] - 2 * row["friction_base"] for row in rows
        ]
        result[label] = {
            "n": len(rows),
            "net_profit_base": sum(base),
            "net_profit_2x": sum(doubled),
            "mean_net_r_base": float(
                np.mean(
                    [
                        profit
                        / (
                            row["entry_fill"] - row["stop_initial"]
                        )
                        / risk.position_size(
                            risk.START_CAPITAL,
                            row["entry_fill"],
                            row["stop_initial"],
                        )
                        for profit, row in zip(base, rows)
                    ]
                )
            ),
        }
    return result


def _cell_report(
    frames: dict[str, pd.DataFrame],
    *,
    family_name: str,
    family: dict,
    cell: dict,
    geometry: dict,
    costs: dict,
    end_exclusive: dt.date,
    regimes: dict[dt.date, str],
    negative_seed: int,
    min_events: int,
) -> dict:
    detected = _detected_dates(
        frames,
        detector=family["detector"],
        config_name=cell["config_name"],
        params=cell["params"],
        end_exclusive=end_exclusive,
    )
    events, raw_h15, rejects = _simulate_dates(
        frames,
        detected,
        config_name=cell["config_name"],
        geometry=geometry,
        costs=costs,
        regimes=regimes,
    )
    gate = summarize_events(events, raw_h15_returns=raw_h15, min_events=min_events)

    cell_seed = negative_seed + int(sha256_json(cell)[:8], 16)
    random_dates = _matched_random_dates(frames, detected, seed=cell_seed)
    control_events, control_raw, control_rejects = _simulate_dates(
        frames,
        random_dates,
        config_name=f"{cell['config_name']}_random_control",
        geometry=geometry,
        costs=costs,
        regimes=regimes,
    )
    control_gate = summarize_events(
        control_events,
        raw_h15_returns=control_raw,
        min_events=min_events,
    )
    event_2x_mean = gate["metrics"]["win_loss"]["2x_net_profit"]["mean"]
    control_2x_mean = control_gate["metrics"]["win_loss"]["2x_net_profit"][
        "mean"
    ]
    beats_control = (
        event_2x_mean is not None
        and control_2x_mean is not None
        and event_2x_mean > control_2x_mean
    )
    return {
        "family": family_name,
        "cell_id": cell["id"],
        "config_name": cell["config_name"],
        "detector_params": cell["params"],
        "geometry": geometry,
        "detected_events": len(detected),
        "simulation_rejections": rejects,
        "event_gate": gate,
        "slices": {
            "year": _slice(events, "year"),
            "regime": _slice(events, "regime"),
            "exit_reason": _slice(events, "exit_reason"),
        },
        "negative_control": {
            "kind": "symbol_matched_random_session",
            "seed": cell_seed,
            "sampled_events": len(random_dates),
            "simulation_rejections": control_rejects,
            "event_gate": control_gate,
            "event_2x_net_profit_mean_minus_control": (
                event_2x_mean - control_2x_mean
                if event_2x_mean is not None and control_2x_mean is not None
                else None
            ),
            "beats_control": beats_control,
        },
    }


def run_discovery(
    config: dict,
    frames: dict[str, pd.DataFrame],
    *,
    input_manifest: list[dict],
    catalyst_exists: bool,
) -> dict:
    data = config["data"]
    end_exclusive = dt.date.fromisoformat(data["end_exclusive"])
    for symbol, frame in frames.items():
        if not frame.empty and max(frame.index.date) >= end_exclusive:
            raise RuntimeError(f"data-wall violation in supplied frame {symbol}")

    regimes = _spy_regimes(frames)
    geometry = config["geometry"]
    costs = config["costs"]
    selection = config["selection"]
    negative_seed = int(config["negative_control"]["seed"])
    family_reports: dict[str, dict] = {}
    passing_cells: list[dict] = []

    for family_name, family in config["families"].items():
        if family["detector"] == "pead_catalyst_required":
            family_reports[family_name] = {
                "state": "not_run_input_failure",
                "reason": (
                    "catalyst_cache_missing"
                    if not catalyst_exists
                    else "catalyst_coverage_not_certified"
                ),
                "required_input": family["required_input"],
                "cells": [],
                "selected": None,
            }
            continue
        cells = [
            _cell_report(
                frames,
                family_name=family_name,
                family=family,
                cell=cell,
                geometry=geometry,
                costs=costs,
                end_exclusive=end_exclusive,
                regimes=regimes,
                negative_seed=negative_seed,
                min_events=int(selection["min_closed_events"]),
            )
            for cell in family["cells"]
        ]
        base_pass = [
            cell
            for cell in cells
            if cell["event_gate"]["passes"]
            and cell["negative_control"]["beats_control"]
        ]
        neighborhood_pass = len(base_pass) >= int(
            selection["min_passing_neighbor_cells"]
        )
        selected = None
        if neighborhood_pass:
            selected = max(
                base_pass,
                key=lambda cell: (
                    cell["event_gate"]["metrics"]["win_loss"][
                        "2x_net_profit"
                    ]["mean"],
                    cell["cell_id"],
                ),
            )
            passing_cells.append(
                {
                    "candidate_id": (
                        f"{family_name}.{selected['cell_id']}.g"
                        f"{geometry['stop_atr_multiple']:g}x"
                        f"{geometry['target_atr_multiple']:g}"
                    ),
                    "family": family_name,
                    "mechanism": family["mechanism"],
                    "cell_id": selected["cell_id"],
                    "config_name": selected["config_name"],
                    "detector_params": selected["detector_params"],
                    "geometry": geometry,
                    "ranking": family["ranking"],
                    "selection_facts": {
                        "event_gate_pass": True,
                        "beats_matched_random": True,
                        "passing_neighbor_cells": len(base_pass),
                    },
                }
            )
        family_reports[family_name] = {
            "state": "evaluated",
            "mechanism": family["mechanism"],
            "cells": cells,
            "passing_cells": [cell["cell_id"] for cell in base_pass],
            "neighborhood_pass": neighborhood_pass,
            "selected": selected["cell_id"] if selected else None,
            "rejection_reason": (
                None
                if selected
                else (
                    f"only {len(base_pass)} cells passed event/control bars; "
                    f"{selection['min_passing_neighbor_cells']} required"
                )
            ),
        }

    candidates = passing_cells[:3]
    return {
        "schema": ARTIFACT_SCHEMA,
        "data_wall": {
            "start_inclusive": data["start_inclusive"],
            "end_exclusive": data["end_exclusive"],
            "enforced": True,
            "post_wall_rows_seen": 0,
        },
        "config_sha256": sha256_json(config),
        "inputs": {
            "loaded_frames": len(frames),
            "manifest": input_manifest,
            "catalyst_path": data["catalyst_path"],
            "catalyst_exists": catalyst_exists,
        },
        "families": family_reports,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "verdict": "PROCEED_TO_PREREG" if candidates else "STOP",
    }
