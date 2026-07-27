"""Locked walk-forward folds and downstream economic evaluation."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from sts.ml.contracts import ContractViolation
from sts.ml.controls import (
    fixed_control_scores,
    random_top_k_controls,
    select_top_k,
)


@dataclass(frozen=True)
class WalkForwardFold:
    name: str
    train_start: dt.date
    train_end: dt.date
    validation_start: dt.date
    validation_end: dt.date


LOCKED_FOLDS = (
    WalkForwardFold(
        "F1", dt.date(2010, 1, 1), dt.date(2016, 1, 1),
        dt.date(2016, 1, 1), dt.date(2018, 1, 1),
    ),
    WalkForwardFold(
        "F2", dt.date(2010, 1, 1), dt.date(2018, 1, 1),
        dt.date(2018, 1, 1), dt.date(2020, 1, 1),
    ),
    WalkForwardFold(
        "F3", dt.date(2010, 1, 1), dt.date(2020, 1, 1),
        dt.date(2020, 1, 1), dt.date(2022, 1, 1),
    ),
    WalkForwardFold(
        "F4", dt.date(2010, 1, 1), dt.date(2022, 1, 1),
        dt.date(2022, 1, 1), dt.date(2024, 1, 1),
    ),
)


def split_fold(
    frame: pd.DataFrame,
    fold: WalkForwardFold,
    *,
    exchange_sessions: Sequence[dt.date],
    embargo_sessions: int = 15,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Apply date split, outcome purge, and 15-session validation embargo."""
    if embargo_sessions != 15:
        raise ContractViolation("validation embargo must remain 15 sessions")
    required = {"signal_session", "label_end_session"}
    if not required.issubset(frame):
        raise ContractViolation(f"fold frame lacks {sorted(required - set(frame))}")
    signal = pd.to_datetime(frame["signal_session"])
    train = frame[
        (signal >= pd.Timestamp(fold.train_start))
        & (signal < pd.Timestamp(fold.train_end))
    ].copy()
    validation = frame[
        (signal >= pd.Timestamp(fold.validation_start))
        & (signal < pd.Timestamp(fold.validation_end))
    ].copy()
    before_purge = len(train)
    train = train[
        pd.to_datetime(train["label_end_session"]) < pd.Timestamp(fold.validation_start)
    ]
    normalized_sessions = tuple(pd.Timestamp(day).date() for day in exchange_sessions)
    if tuple(sorted(set(normalized_sessions))) != normalized_sessions:
        raise ContractViolation("exchange_sessions must be unique and strictly ordered")
    validation_dates = [
        pd.Timestamp(day)
        for day in normalized_sessions
        if fold.validation_start <= day < fold.validation_end
    ]
    embargoed = set(validation_dates[:embargo_sessions])
    before_embargo = len(validation)
    validation = validation[
        ~pd.to_datetime(validation["signal_session"]).isin(embargoed)
    ]
    return (
        train.sort_values(["signal_session", "symbol"], kind="mergesort"),
        validation.sort_values(["signal_session", "symbol"], kind="mergesort"),
        {
            "purged_training_rows": before_purge - len(train),
            "embargoed_validation_rows": before_embargo - len(validation),
            "embargoed_validation_sessions": min(
                embargo_sessions, len(validation_dates)
            ),
        },
    )


def circular_blocked_bootstrap(
    values: np.ndarray | list[float],
    *,
    seed: int,
    block_size: int = 20,
    replicates: int = 2000,
) -> dict[str, float]:
    """Seeded circular moving-block interval over ordered date differences."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise ContractViolation("bootstrap values must be finite and non-empty")
    if block_size != 20 or replicates != 2000:
        raise ContractViolation("bootstrap must use 20-session blocks and 2,000 replicates")
    rng = np.random.default_rng(seed)
    sample_means = np.empty(replicates, dtype=float)
    blocks_needed = int(np.ceil(len(array) / block_size))
    offsets = np.arange(block_size)
    for replicate in range(replicates):
        starts = rng.integers(0, len(array), size=blocks_needed)
        positions = ((starts[:, None] + offsets) % len(array)).ravel()[: len(array)]
        sample_means[replicate] = array[positions].mean()
    return {
        "mean": float(array.mean()),
        "lower90": float(np.quantile(sample_means, 0.05)),
        "upper90": float(np.quantile(sample_means, 0.95)),
    }


def _bootstrap_seed(config_hash: str, fold: str) -> int:
    return int(
        hashlib.sha256(f"{config_hash}|{fold}|blocked_bootstrap".encode()).hexdigest()[
            :16
        ],
        16,
    )


def evaluate_scores(
    frame: pd.DataFrame,
    *,
    scores: np.ndarray | pd.Series,
    config_hash: str,
    fold: str,
    track: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """Evaluate selected economics against exact same-date random controls."""
    judged = frame.copy()
    judged["score"] = np.asarray(scores, dtype=float)
    if not np.isfinite(judged["score"]).all():
        raise ContractViolation("scores must be finite")
    selected = select_top_k(
        judged, score_column="score", top_k=top_k, track=track
    )
    controls = random_top_k_controls(
        judged,
        config_hash=config_hash,
        fold=fold,
        track=track,
        top_k=top_k,
    )
    selected_by_date = selected.groupby("signal_session", sort=True)[
        "net_r_2x"
    ].mean()
    control_by_date = controls.groupby("signal_session", sort=True)["mean_value"].mean()
    common = selected_by_date.index.intersection(control_by_date.index)
    differences = (selected_by_date.loc[common] - control_by_date.loc[common]).sort_index()
    if differences.empty:
        return {
            "state": "not_run_inadequate_cross_section",
            "selected_rows": 0,
            "unique_dates": 0,
        }
    interval = circular_blocked_bootstrap(
        differences.to_numpy(),
        seed=_bootstrap_seed(config_hash, fold),
    )
    return {
        "state": "evaluated",
        "fold": fold,
        "top_k": top_k,
        "selected_rows": len(selected),
        "unique_dates": len(common),
        "unique_symbols": int(selected["symbol"].nunique()),
        "selected_identities": selected["row_id"].astype(str).tolist(),
        "selected_net_r_2x_mean": float(selected["net_r_2x"].mean()),
        "selected_net_profit_base": float(
            (
                selected["gross_profit"] - selected["friction_base"]
            ).sum()
        ),
        "selected_net_profit_2x": float(
            (
                selected["gross_profit"] - selected["friction_2x"]
            ).sum()
        ),
        "selected_raw_h15_mean": float(selected["raw_h15_return"].mean()),
        "date_differences": [
            {"signal_session": pd.Timestamp(day).date().isoformat(), "difference": value}
            for day, value in differences.items()
        ],
        "incremental": interval,
    }


def evaluate_fixed_baselines(
    frame: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
    track: str,
) -> dict[str, float | None]:
    result = {}
    for name, scores in fixed_control_scores(frame).items():
        judged = evaluate_scores(
            frame,
            scores=scores,
            config_hash=config_hash,
            fold=fold,
            track=track,
        )
        result[name] = (
            judged["incremental"]["mean"] if judged["state"] == "evaluated" else None
        )
    return result


@dataclass(frozen=True)
class PromotionControls:
    future_feature_canary_rejected: bool
    post_wall_canary_rejected: bool
    fold_local_transforms: bool
    permutation_arm_cleared: bool
    deterministic_candidate_identity: bool
    data_integrity_passed: bool

    @property
    def passed(self) -> bool:
        return (
            self.future_feature_canary_rejected
            and self.post_wall_canary_rejected
            and self.fold_local_transforms
            and not self.permutation_arm_cleared
            and self.deterministic_candidate_identity
            and self.data_integrity_passed
        )


def assess_development_credibility(
    fold_incremental_means: list[float],
    *,
    pooled_lower90: float,
    selected_net_profit_base: float,
    selected_net_profit_2x: float,
    selected_raw_h15_mean: float,
    geometry_and_hold_valid: bool,
    selected_n: int,
    unique_dates: int,
    primary_incremental_mean: float,
    baseline_incremental_means: dict[str, float],
    controls: PromotionControls,
) -> dict[str, Any]:
    required_baselines = {
        "momentum_20_desc",
        "pullback_5_asc",
        "activity_desc",
        "constant_equal",
    }
    bars = {
        "positive_at_least_3_folds": (
            len(fold_incremental_means) == 4
            and sum(value > 0 for value in fold_incremental_means) >= 3
        ),
        "pooled_lower90_positive": pooled_lower90 > 0,
        "base_net_profit_positive": selected_net_profit_base > 0,
        "double_net_profit_positive": selected_net_profit_2x > 0,
        "raw_h15_positive": selected_raw_h15_mean > 0,
        "geometry_and_hold_valid": geometry_and_hold_valid,
        "adequate_rows_and_dates": selected_n >= 100 and unique_dates >= 60,
        "beats_all_fixed_baselines": (
            set(baseline_incremental_means) == required_baselines
            and all(
                primary_incremental_mean > value
                for value in baseline_incremental_means.values()
            )
        ),
        "required_controls_pass": controls.passed,
    }
    return {
        "credible": all(bars.values()),
        "bars": bars,
    }


def rank_credible_arms(
    arm_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Apply the locked arm ordering and one-candidate-per-family cap."""
    model_order = {"M1": 0, "M2": 1, "M3": 2}
    track_order = {"A": 0, "B": 1}
    target_order = {"T1": 0, "T2": 1, "T3": 2}
    required = {
        "credible",
        "median_fold_incremental_mean",
        "pooled_lower90",
        "median_fold_absolute_net_r_2x",
        "model",
        "track",
        "target",
        "canonical_config_id",
    }
    for result in arm_results:
        if not required.issubset(result):
            raise ContractViolation(
                f"arm result lacks {sorted(required - set(result))}"
            )
        if result["model"] not in model_order:
            raise ContractViolation("unknown model family in arm result")
        if result["track"] not in track_order or result["target"] not in target_order:
            raise ContractViolation("unknown track or target in arm result")
    ordered = sorted(
        (result for result in arm_results if result["credible"]),
        key=lambda result: (
            -float(result["median_fold_incremental_mean"]),
            -float(result["pooled_lower90"]),
            -float(result["median_fold_absolute_net_r_2x"]),
            model_order[result["model"]],
            track_order[result["track"]],
            target_order[result["target"]],
            str(result["canonical_config_id"]),
        ),
    )
    selected = []
    used_models = set()
    for result in ordered:
        if result["model"] in used_models:
            continue
        selected.append(result)
        used_models.add(result["model"])
        if len(selected) == 3:
            break
    return tuple(selected)
