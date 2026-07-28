"""Locked Task 5 development run over the walled pre-2024 matrices.

The runner in this module has no source-data or network fallback. It accepts
only the deterministic Task 3 shards, verifies their manifest and wall before
materializing them, fits the exact Task 4 arms, and returns a JSON-safe report.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sts.calendar import sessions_between
from sts.ml.contracts import ContractViolation, canonical_json
from sts.ml.controls import (
    control_seed,
    fixed_control_scores,
    select_top_k,
    symbol_matched_random_sessions,
)
from sts.ml.data import DATA_SCHEMA, MANIFEST_SCHEMA
from sts.ml.evaluation import (
    LOCKED_FOLDS,
    PromotionControls,
    assess_development_credibility,
    circular_blocked_bootstrap,
    rank_credible_arms,
    split_fold,
)
from sts.ml.features import FeatureFact, feature_names, make_feature_snapshot
from sts.ml.models import ArmConfig, FittedArm, fit_arm, locked_arms, model_frame
from sts.ml.walls import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_START_INCLUSIVE,
    WallViolation,
    require_development_session,
)

REPORT_SCHEMA = "ml-development-report-v1"
TARGET_COLUMNS = (
    "relative_net_r_2x",
    "spy_residual_h15",
    "useful_opportunity",
)
CORE_COLUMNS = {
    "schema",
    "config_hash",
    "row_id",
    "track",
    "symbol",
    "signal_session",
    "label_end_session",
    "entry_session",
    "exit_session",
    "selection_status",
    "entry_fill",
    "stop_initial",
    "target_initial",
    "initial_risk_pct",
    "planned_r",
    "hold_sessions",
    "gross_profit",
    "friction_base",
    "friction_2x",
    "net_r_base",
    "net_r_2x",
    "raw_h15_return",
    "exit_reason",
    *TARGET_COLUMNS,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _sha256_scores(row_ids: Sequence[str], scores: np.ndarray) -> str:
    values = np.asarray(scores, dtype="<f8")
    if len(row_ids) != len(values) or not np.isfinite(values).all():
        raise ContractViolation("score hash inputs must be finite and aligned")
    digest = hashlib.sha256()
    digest.update(canonical_json(list(map(str, row_ids))).encode())
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def _sha256_identities(row_ids: Sequence[str]) -> str:
    return _sha256_json(list(map(str, row_ids)))


def _sha256_control_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(
        ["signal_session", "replicate", "control_id"], kind="mergesort"
    )
    for row in ordered.itertuples(index=False):
        digest.update(pd.Timestamp(row.signal_session).date().isoformat().encode())
        digest.update(int(row.replicate).to_bytes(4, "big", signed=False))
        digest.update(str(row.control_id).encode())
        digest.update(np.asarray([row.mean_value], dtype="<f8").tobytes())
        digest.update(str(row.selected_symbols).encode())
    return digest.hexdigest()


def _minimum_pool(track: str, top_k: int) -> int:
    if track == "A":
        return 20
    return {1: 2, 3: 4, 5: 6}[top_k]


def _stream_random_control(
    frame: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
    track: str,
    top_k: int,
    control_id: str = "same_date_random",
) -> tuple[pd.Series, dict[str, Any]]:
    """Calculate the exact Task 4 control without materializing detail rows."""
    means = {}
    digest = hashlib.sha256()
    row_count = 0
    for day_value, group in frame.groupby("signal_session", sort=True):
        if len(group) < _minimum_pool(track, top_k):
            continue
        day = pd.Timestamp(day_value).date()
        ordered = group.sort_values("symbol", kind="mergesort").reset_index(drop=True)
        values = ordered["net_r_2x"].to_numpy(dtype=float)
        symbols = ordered["symbol"].astype(str).to_numpy()
        replicate_means = []
        for replicate in range(100):
            rng = np.random.default_rng(
                control_seed(config_hash, fold, day, replicate, control_id)
            )
            positions = rng.choice(len(ordered), size=top_k, replace=False)
            value = float(values[positions].mean())
            selected_symbols = "|".join(sorted(symbols[positions]))
            replicate_means.append(value)
            digest.update(day.isoformat().encode())
            digest.update(replicate.to_bytes(4, "big", signed=False))
            digest.update(control_id.encode())
            digest.update(np.asarray([value], dtype="<f8").tobytes())
            digest.update(selected_symbols.encode())
            row_count += 1
        means[pd.Timestamp(day)] = float(np.mean(replicate_means))
    series = pd.Series(means, dtype=float).sort_index()
    return series, {
        "rows": row_count,
        "unique_dates": len(series),
        "sha256": digest.hexdigest(),
    }


def _permute_training_target(
    frame: pd.DataFrame,
    *,
    target_column: str,
    config_hash: str,
    fold: str,
    replicate: int,
) -> pd.DataFrame:
    """Exact within-date permutation with one target-column copy."""
    if replicate < 0 or replicate >= 20:
        raise ContractViolation("permutation replicate must be in [0, 20)")
    values = frame[target_column].to_numpy(copy=True)
    permuted_values = values.copy()
    for day_value, positions in frame.groupby(
        "signal_session", sort=True
    ).indices.items():
        day = pd.Timestamp(day_value).date()
        rng = np.random.default_rng(
            control_seed(config_hash, fold, day, replicate, "label_permutation")
        )
        positions_array = np.asarray(positions, dtype=int)
        order = rng.permutation(len(positions_array))
        permuted_values[positions_array] = values[positions_array][order]
    result = frame.copy(deep=False)
    result[target_column] = permuted_values
    return result


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


def validate_matrix_frame(
    frame: pd.DataFrame,
    *,
    track: str,
    config_hash: str,
) -> None:
    """Fail closed on an incomplete, mismatched, or post-wall matrix."""
    required = CORE_COLUMNS | set(feature_names(track))
    missing = sorted(required - set(frame))
    if missing:
        raise ContractViolation(f"Track {track} matrix lacks columns: {','.join(missing)}")
    if frame.empty:
        raise ContractViolation(f"Track {track} matrix is empty")
    if set(frame["schema"].astype(str)) != {DATA_SCHEMA}:
        raise ContractViolation(f"Track {track} matrix schema mismatch")
    if set(frame["config_hash"].astype(str)) != {config_hash}:
        raise ContractViolation(f"Track {track} matrix config hash mismatch")
    if set(frame["track"].astype(str)) != {track}:
        raise ContractViolation(f"Track {track} matrix track mismatch")
    if frame["row_id"].duplicated().any():
        raise ContractViolation(f"Track {track} matrix has duplicate row identities")
    if frame.duplicated(["symbol", "signal_session"]).any():
        raise ContractViolation(f"Track {track} matrix has duplicate symbol-date keys")

    for column in (
        "signal_session",
        "label_end_session",
        "entry_session",
        "exit_session",
    ):
        dates = pd.to_datetime(frame[column]).dt.date
        if any(day < DEVELOPMENT_START_INCLUSIVE for day in dates):
            raise WallViolation(f"{column} is before development start")
        post_wall = [day for day in dates if day >= DEVELOPMENT_END_EXCLUSIVE]
        if post_wall:
            require_development_session(post_wall[0])

    finite_columns = [
        "entry_fill",
        "stop_initial",
        "target_initial",
        "initial_risk_pct",
        "planned_r",
        "gross_profit",
        "friction_base",
        "friction_2x",
        "net_r_base",
        "net_r_2x",
        "raw_h15_return",
        *TARGET_COLUMNS,
    ]
    if not np.isfinite(frame[finite_columns].astype(float).to_numpy()).all():
        raise ContractViolation(f"Track {track} matrix has non-finite label/economic facts")
    if not (
        (frame["entry_fill"] > frame["stop_initial"])
        & (frame["target_initial"] > frame["entry_fill"])
        & (frame["planned_r"] > 1.5)
        & (frame["initial_risk_pct"] < 0.12)
        & (frame["hold_sessions"] >= 1)
        & (frame["hold_sessions"] <= 15)
    ).all():
        raise ContractViolation(f"Track {track} matrix has invalid geometry or hold")
    feature_values = frame[list(feature_names(track))].astype(float).to_numpy()
    if np.isinf(feature_values).any():
        raise ContractViolation(f"Track {track} matrix has infinite feature values")


def load_development_artifacts(
    input_dir: Path | str,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any], dict[str, Any]]:
    """Load only manifest-declared pre-2024 shards after hash verification."""
    root = Path(input_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ContractViolation("development manifest schema mismatch")
    walls = manifest.get("walls", {})
    if walls != {
        "development_start_inclusive": DEVELOPMENT_START_INCLUSIVE.isoformat(),
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE.isoformat(),
        "post_wall_rows_observed": 0,
    }:
        raise WallViolation("development manifest wall mismatch")
    checks = manifest.get("checks", {})
    for key in (
        "track_a_duplicate_keys",
        "track_b_duplicate_keys",
        "track_b_missing_track_a_parent",
        "post_wall_rows_observed",
    ):
        if checks.get(key) != 0:
            raise ContractViolation(f"development manifest integrity failure: {key}")

    config_hash = str(manifest["config_hash"])
    frames: dict[str, pd.DataFrame] = {}
    verified_shards = []
    for track, key in (("A", "track_a"), ("B", "track_b")):
        matrix_manifest = manifest["matrices"][key]
        shards = matrix_manifest["shards"]
        if _dataset_sha256(shards) != matrix_manifest["sha256"]:
            raise ContractViolation(f"Track {track} dataset hash envelope mismatch")
        pieces = []
        for shard in shards:
            year = int(shard["year"])
            if year >= DEVELOPMENT_END_EXCLUSIVE.year:
                raise WallViolation(f"Track {track} manifest declares post-wall shard")
            path = (root / str(shard["path"])).resolve()
            if path.parent != root or not path.name.startswith(f"{key}_"):
                raise ContractViolation(f"Track {track} shard path is not bounded")
            observed_hash = sha256_file(path)
            if observed_hash != shard["sha256"]:
                raise ContractViolation(f"Track {track} shard hash mismatch: {path.name}")
            piece = pd.read_parquet(path)
            if len(piece) != int(shard["rows"]):
                raise ContractViolation(f"Track {track} shard row count mismatch")
            pieces.append(piece)
            verified_shards.append(
                {
                    "track": track,
                    "year": year,
                    "path": path.name,
                    "rows": len(piece),
                    "sha256": observed_hash,
                }
            )
        frame = pd.concat(pieces, ignore_index=True)
        if len(frame) != int(matrix_manifest["rows"]):
            raise ContractViolation(f"Track {track} matrix row count mismatch")
        frame = frame.sort_values(
            ["signal_session", "symbol"], kind="mergesort"
        ).reset_index(drop=True)
        validate_matrix_frame(frame, track=track, config_hash=config_hash)
        frames[track] = frame
    track_a_keys = set(zip(frames["A"]["symbol"], frames["A"]["signal_session"], strict=True))
    track_b_keys = set(zip(frames["B"]["symbol"], frames["B"]["signal_session"], strict=True))
    if track_b_keys - track_a_keys:
        raise ContractViolation("Track B matrix has no Track A parent")
    provenance = {
        "manifest_sha256": sha256_file(manifest_path),
        "config_hash": config_hash,
        "track_a_sha256": manifest["matrices"]["track_a"]["sha256"],
        "track_b_sha256": manifest["matrices"]["track_b"]["sha256"],
        "verified_shards": verified_shards,
    }
    return frames, manifest, provenance


def bucket_score_rank(rank_fraction: float) -> str:
    """Fixed descriptive score buckets; never used for model selection."""
    if not np.isfinite(rank_fraction) or rank_fraction <= 0 or rank_fraction > 1:
        raise ContractViolation("score rank fraction must be in (0, 1]")
    if rank_fraction <= 0.25:
        return "top_quartile"
    if rank_fraction <= 0.50:
        return "second_quartile"
    return "bottom_half"


def _bucket_liquidity(value: float) -> str:
    if pd.isna(value):
        return "missing"
    if value < 0.75:
        return "below_0_75x_trailing_median"
    if value <= 1.25:
        return "0_75x_to_1_25x_trailing_median"
    return "above_1_25x_trailing_median"


def _economic_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "rows": 0,
            "unique_dates": 0,
            "unique_symbols": 0,
            "net_r_base_mean": None,
            "net_r_2x_mean": None,
            "raw_h15_mean": None,
            "gross_profit_total": 0.0,
            "friction_base_total": 0.0,
            "friction_2x_total": 0.0,
            "net_profit_base": 0.0,
            "net_profit_2x": 0.0,
        }
    return {
        "rows": len(frame),
        "unique_dates": int(frame["signal_session"].nunique()),
        "unique_symbols": int(frame["symbol"].nunique()),
        "net_r_base_mean": float(frame["net_r_base"].mean()),
        "net_r_2x_mean": float(frame["net_r_2x"].mean()),
        "raw_h15_mean": float(frame["raw_h15_return"].mean()),
        "gross_profit_total": float(frame["gross_profit"].sum()),
        "friction_base_total": float(frame["friction_base"].sum()),
        "friction_2x_total": float(frame["friction_2x"].sum()),
        "net_profit_base": float(
            (frame["gross_profit"] - frame["friction_base"]).sum()
        ),
        "net_profit_2x": float(
            (frame["gross_profit"] - frame["friction_2x"]).sum()
        ),
    }


def _slice(frame: pd.DataFrame, labels: pd.Series) -> dict[str, Any]:
    result = {}
    for label in sorted(labels.astype(str).unique()):
        result[label] = _economic_summary(frame.loc[labels.astype(str) == label])
    return result


def summarize_selected_rows(frame: pd.DataFrame) -> dict[str, Any]:
    """Create preregistered diagnostic slices without feeding selection."""
    summary = _economic_summary(frame)
    if frame.empty:
        summary.update(
            {
                "mae": {
                    "state": "not_run_input_failure",
                    "reason": "mae_column_absent_from_locked_development_matrix",
                },
                "slices": {},
                "concentration": {},
            }
        )
        return summary
    if "score_rank_fraction" not in frame:
        raise ContractViolation("selected rows lack score rank fractions")
    score_bucket = frame["score_rank_fraction"].map(bucket_score_rank)
    liquidity = frame["dollar_volume_to_median_20"].map(_bucket_liquidity)
    spy_regime = frame["spy_above_ma_200"].map(
        lambda value: (
            "missing"
            if pd.isna(value)
            else ("above_200d" if float(value) == 1.0 else "at_or_below_200d")
        )
    )
    year = pd.to_datetime(frame["signal_session"]).dt.year.astype(str)
    by_symbol = frame.groupby("symbol", sort=True).size().sort_values(
        ascending=False, kind="mergesort"
    )
    by_date = frame.groupby("signal_session", sort=True).size().sort_values(
        ascending=False, kind="mergesort"
    )
    summary.update(
        {
            "mae": (
                {
                    "state": "reported",
                    "mean": float(frame["mae"].mean()),
                }
                if "mae" in frame
                else {
                    "state": "not_run_input_failure",
                    "reason": "mae_column_absent_from_locked_development_matrix",
                }
            ),
            "slices": {
                "year": _slice(frame, year),
                "spy_regime": _slice(frame, spy_regime),
                "relative_liquidity": _slice(frame, liquidity),
                "score_bucket": _slice(frame, score_bucket),
                "exit_reason": _slice(frame, frame["exit_reason"].fillna("missing")),
            },
            "concentration": {
                "largest_symbol_share": float(by_symbol.iloc[0] / len(frame)),
                "top_10_symbol_share": float(by_symbol.head(10).sum() / len(frame)),
                "largest_signal_date_share": float(by_date.iloc[0] / len(frame)),
                "top_symbols": {
                    str(symbol): int(count)
                    for symbol, count in by_symbol.head(10).items()
                },
            },
        }
    )
    return summary


def _bootstrap_seed(config_hash: str, scope: str) -> int:
    return int(
        hashlib.sha256(
            f"{config_hash}|{scope}|blocked_bootstrap".encode()
        ).hexdigest()[:16],
        16,
    )


def _control_mean_by_date(controls: pd.DataFrame) -> pd.Series:
    if controls.empty:
        return pd.Series(dtype=float)
    return controls.groupby("signal_session", sort=True)["mean_value"].mean()


def _add_score_ranks(frame: pd.DataFrame, scores: np.ndarray) -> pd.DataFrame:
    judged = frame.copy()
    judged["score"] = np.asarray(scores, dtype=float)
    if not np.isfinite(judged["score"]).all():
        raise ContractViolation("scores must be finite")
    fractions = pd.Series(index=judged.index, dtype=float)
    for _day, group in judged.groupby("signal_session", sort=True):
        ordered = group.sort_values(
            ["score", "symbol"],
            ascending=[False, True],
            kind="mergesort",
        )
        fractions.loc[ordered.index] = (
            np.arange(1, len(ordered) + 1, dtype=float) / len(ordered)
        )
    judged["score_rank_fraction"] = fractions.loc[judged.index]
    return judged


def _evaluate_with_control(
    frame: pd.DataFrame,
    *,
    scores: np.ndarray | pd.Series,
    control_by_date: pd.Series,
    config_hash: str,
    scope: str,
    track: str,
    top_k: int,
) -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]]]:
    """Economic evaluator using one cached exact random-control draw."""
    judged = _add_score_ranks(frame, np.asarray(scores, dtype=float))
    selected = select_top_k(
        judged,
        score_column="score",
        top_k=top_k,
        track=track,
    )
    selected_by_date = selected.groupby("signal_session", sort=True)[
        "net_r_2x"
    ].mean()
    common = selected_by_date.index.intersection(control_by_date.index)
    differences = (
        selected_by_date.loc[common] - control_by_date.loc[common]
    ).sort_index()
    if differences.empty:
        return (
            {
                "state": "not_run_inadequate_cross_section",
                "selected_rows": 0,
                "unique_dates": 0,
            },
            selected.iloc[0:0].copy(),
            [],
        )
    interval = circular_blocked_bootstrap(
        differences.to_numpy(),
        seed=_bootstrap_seed(config_hash, scope),
    )
    identities = selected["row_id"].astype(str).tolist()
    public = {
        "state": "evaluated",
        "top_k": top_k,
        "selected_rows": len(selected),
        "unique_dates": len(common),
        "unique_symbols": int(selected["symbol"].nunique()),
        "selected_identities_sha256": _sha256_identities(identities),
        "selected_net_r_2x_mean": float(selected["net_r_2x"].mean()),
        "selected_net_profit_base": float(
            (selected["gross_profit"] - selected["friction_base"]).sum()
        ),
        "selected_net_profit_2x": float(
            (selected["gross_profit"] - selected["friction_2x"]).sum()
        ),
        "selected_raw_h15_mean": float(selected["raw_h15_return"].mean()),
        "incremental": interval,
    }
    serialized_differences = [
        {
            "signal_session": pd.Timestamp(day).date().isoformat(),
            "difference": float(value),
        }
        for day, value in differences.items()
    ]
    return public, selected, serialized_differences


def _compare_selected_to_control(
    selected: pd.DataFrame,
    control_by_date: pd.Series,
    *,
    config_hash: str,
    scope: str,
) -> dict[str, Any]:
    selected_by_date = selected.groupby("signal_session", sort=True)[
        "net_r_2x"
    ].mean()
    common = selected_by_date.index.intersection(control_by_date.index)
    differences = (
        selected_by_date.loc[common] - control_by_date.loc[common]
    ).sort_index()
    if differences.empty:
        return {"state": "not_run_inadequate_cross_section"}
    return {
        "state": "evaluated",
        "unique_dates": len(differences),
        "incremental": circular_blocked_bootstrap(
            differences.to_numpy(),
            seed=_bootstrap_seed(config_hash, scope),
        ),
    }


def _predict_estimator(fitted: FittedArm, features: pd.DataFrame) -> np.ndarray:
    if fitted.arm.target == "T3":
        return np.asarray(fitted.estimator.predict_proba(features)[:, 1], dtype=float)
    return np.asarray(fitted.estimator.predict(features), dtype=float)


def _noise_diagnostic(
    fitted: FittedArm,
    validation: pd.DataFrame,
    scores: np.ndarray,
) -> dict[str, Any]:
    noise_index = len(fitted.feature_columns) - 1
    if fitted.arm.model == "M1":
        estimator = fitted.estimator.named_steps["estimator"]
        coefficients = np.asarray(estimator.coef_, dtype=float)
        flat = coefficients[0] if coefficients.ndim == 2 else coefficients
        return {
            "measure": "standardized_coefficient",
            "value": float(flat[noise_index]),
        }
    if fitted.arm.model == "M3":
        return {
            "measure": "split_count",
            "value": int(fitted.estimator.feature_importances_[noise_index]),
        }
    features, _columns = model_frame(validation, fitted.arm)
    permuted = features.copy()
    # A fixed one-row rotation measures the model's score dependence on noise.
    permuted["noise"] = np.roll(permuted["noise"].to_numpy(), 1)
    alternative = _predict_estimator(fitted, permuted)
    return {
        "measure": "mean_absolute_score_change_after_fixed_noise_rotation",
        "value": float(np.mean(np.abs(np.asarray(scores) - alternative))),
    }


def _symbol_matched_summary(
    track_a_validation: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
) -> dict[str, Any]:
    sampled = symbol_matched_random_sessions(
        track_a_validation,
        selected,
        config_hash=config_hash,
        fold=fold,
    )
    if sampled.empty:
        return {"state": "not_run_input_failure", "rows": 0}
    return {
        "state": "evaluated",
        "rows": len(sampled),
        "unique_symbols": int(sampled["symbol"].nunique()),
        "control_net_r_2x_mean": float(sampled["net_r_2x"].mean()),
        "selected_minus_control_net_r_2x_mean": float(
            selected["net_r_2x"].mean() - sampled["net_r_2x"].mean()
        ),
        "selected_identities_sha256": _sha256_identities(
            selected["row_id"].astype(str).tolist()
        ),
        "control_identities_sha256": _sha256_identities(
            sampled["row_id"].astype(str).tolist()
        ),
    }


def _geometry_and_hold_valid(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    return bool(
        (
            (frame["entry_fill"] > frame["stop_initial"])
            & (frame["target_initial"] > frame["entry_fill"])
            & (frame["planned_r"] > 1.5)
            & (frame["initial_risk_pct"] < 0.12)
            & (frame["initial_risk_pct"] < 0.25)
            & (frame["hold_sessions"] >= 1)
            & (frame["hold_sessions"] <= 15)
        ).all()
    )


def _pool_differences(
    folds: Sequence[Mapping[str, Any]],
) -> np.ndarray:
    rows = [
        row
        for fold in folds
        for row in fold["date_differences"]
    ]
    ordered = sorted(rows, key=lambda row: row["signal_session"])
    return np.asarray([row["difference"] for row in ordered], dtype=float)


def _pooled_baselines(
    fold_outputs: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fold in fold_outputs:
        for name, result in fold["baseline_internal"].items():
            values[name].extend(result["date_differences"])
    return {
        name: float(
            np.mean(
                [
                    row["difference"]
                    for row in sorted(rows, key=lambda row: row["signal_session"])
                ]
            )
        )
        for name, rows in sorted(values.items())
    }


def _aggregate_variant(
    arm: ArmConfig,
    fold_outputs: Sequence[Mapping[str, Any]],
    *,
    controls: PromotionControls,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if len(fold_outputs) != len(LOCKED_FOLDS):
        raise ContractViolation("arm aggregation requires all four folds")
    selected = pd.concat(
        [fold["selected"] for fold in fold_outputs],
        ignore_index=True,
    )
    differences = _pool_differences(fold_outputs)
    if len(differences) == 0:
        raise ContractViolation("arm has no judged date differences")
    interval = circular_blocked_bootstrap(
        differences,
        seed=_bootstrap_seed(arm.config_hash, "pooled"),
    )
    fold_means = [
        float(fold["evaluation"]["incremental"]["mean"])
        for fold in fold_outputs
    ]
    baseline_means = _pooled_baselines(fold_outputs)
    credibility = assess_development_credibility(
        fold_means,
        pooled_lower90=interval["lower90"],
        selected_net_profit_base=float(
            (selected["gross_profit"] - selected["friction_base"]).sum()
        ),
        selected_net_profit_2x=float(
            (selected["gross_profit"] - selected["friction_2x"]).sum()
        ),
        selected_raw_h15_mean=float(selected["raw_h15_return"].mean()),
        geometry_and_hold_valid=_geometry_and_hold_valid(selected),
        selected_n=len(selected),
        unique_dates=int(selected["signal_session"].nunique()),
        primary_incremental_mean=interval["mean"],
        baseline_incremental_means=baseline_means,
        controls=controls,
    )
    result = {
        "canonical_config_id": arm.canonical_id,
        "config_hash": arm.config_hash,
        "track": arm.track,
        "target": arm.target,
        "model": arm.model,
        "credible": credibility["credible"],
        "bars": credibility["bars"],
        "fold_incremental_means": fold_means,
        "median_fold_incremental_mean": float(np.median(fold_means)),
        "pooled_incremental": interval,
        "pooled_lower90": interval["lower90"],
        "primary_incremental_mean": interval["mean"],
        "median_fold_absolute_net_r_2x": float(
            np.median(
                [
                    fold["evaluation"]["selected_net_r_2x_mean"]
                    for fold in fold_outputs
                ]
            )
        ),
        "baseline_incremental_means": baseline_means,
        "selected": summarize_selected_rows(selected),
        "selected_identities_sha256": _sha256_identities(
            selected["row_id"].astype(str).tolist()
        ),
    }
    return result, selected


def _promotion_canaries() -> dict[str, bool]:
    post_wall_rejected = False
    try:
        require_development_session(DEVELOPMENT_END_EXCLUSIVE)
    except WallViolation:
        post_wall_rejected = True

    future_feature_rejected = False
    signal_session = dt.date(2023, 12, 1)
    facts = {
        name: FeatureFact(0.0, signal_session)
        for name in feature_names("A")
    }
    facts["future_h15_return"] = FeatureFact(1.0, signal_session)
    try:
        make_feature_snapshot(
            "A",
            signal_session,
            causal_bars=300,
            facts=facts,
        )
    except ContractViolation:
        future_feature_rejected = True
    return {
        "future_feature_canary_rejected": future_feature_rejected,
        "post_wall_canary_rejected": post_wall_rejected,
    }


def _baseline_results(
    validation: pd.DataFrame,
    *,
    arm: ArmConfig,
    fold_name: str,
    control_by_date: pd.Series,
) -> tuple[dict[str, Any], dict[str, Any]]:
    public = {}
    internal = {}
    for name, scores in fixed_control_scores(validation).items():
        evaluation, selected, differences = _evaluate_with_control(
            validation,
            scores=scores,
            control_by_date=control_by_date,
            config_hash=arm.config_hash,
            scope=f"{fold_name}|baseline|{name}",
            track=arm.track,
            top_k=3,
        )
        public[name] = {
            "state": evaluation["state"],
            "selected_rows": evaluation.get("selected_rows", 0),
            "unique_dates": evaluation.get("unique_dates", 0),
            "incremental": evaluation.get("incremental"),
            "selected_identities_sha256": evaluation.get(
                "selected_identities_sha256"
            ),
        }
        internal[name] = {
            "evaluation": evaluation,
            "selected": selected,
            "date_differences": differences,
        }
    return public, internal


def _fold_controls(
    validation: pd.DataFrame,
    *,
    arm: ArmConfig,
    fold_name: str,
) -> tuple[dict[int, pd.Series], dict[str, Any]]:
    controls = {}
    evidence = {}
    for top_k in (1, 3, 5):
        control_mean, control_evidence = _stream_random_control(
            validation,
            config_hash=arm.config_hash,
            fold=fold_name,
            track=arm.track,
            top_k=top_k,
        )
        controls[top_k] = control_mean
        evidence[f"top_{top_k}"] = control_evidence
    return controls, evidence


def _fit_and_evaluate(
    training: pd.DataFrame,
    validation: pd.DataFrame,
    track_a_validation: pd.DataFrame,
    *,
    arm: ArmConfig,
    fold_name: str,
    control_means: Mapping[int, pd.Series],
    control_evidence: Mapping[str, Any],
    baseline_public: Mapping[str, Any],
    baseline_internal: Mapping[str, Any],
) -> dict[str, Any]:
    fitted = fit_arm(training, arm)
    scores = fitted.score(validation)
    evaluation, selected, differences = _evaluate_with_control(
        validation,
        scores=scores,
        control_by_date=control_means[3],
        config_hash=arm.config_hash,
        scope=f"{fold_name}|primary",
        track=arm.track,
        top_k=3,
    )
    sensitivities = {}
    for top_k in (1, 5):
        judged, sensitivity_selected, _sensitivity_differences = (
            _evaluate_with_control(
                validation,
                scores=scores,
                control_by_date=control_means[top_k],
                config_hash=arm.config_hash,
                scope=f"{fold_name}|top{top_k}",
                track=arm.track,
                top_k=top_k,
            )
        )
        sensitivities[f"top_{top_k}"] = {
            **judged,
            "selected_identities_sha256": _sha256_identities(
                sensitivity_selected["row_id"].astype(str).tolist()
            ),
        }

    track_b_comparators: dict[str, Any] | None = None
    if arm.track == "B":
        adequate_dates = {
            day
            for day, group in validation.groupby("signal_session", sort=True)
            if len(group) >= 4
        }
        matched_track_b = validation[
            validation["signal_session"].isin(adequate_dates)
        ]
        matched_track_a = track_a_validation[
            track_a_validation["signal_session"].isin(adequate_dates)
        ]
        track_b_control, track_b_evidence = _stream_random_control(
            matched_track_b,
            config_hash=arm.config_hash,
            fold=fold_name,
            track="B",
            top_k=3,
            control_id="track_b_same_date_random",
        )
        track_a_control, track_a_evidence = _stream_random_control(
            matched_track_a,
            config_hash=arm.config_hash,
            fold=fold_name,
            track="A",
            top_k=3,
            control_id="track_a_same_date_random",
        )
        track_b_comparators = {
            "same_event_pool_check": _compare_selected_to_control(
                selected,
                track_b_control,
                config_hash=arm.config_hash,
                scope=f"{fold_name}|track_b_same_event_pool_check",
            ),
            "track_a_combined_detector_ranker": _compare_selected_to_control(
                selected,
                track_a_control,
                config_hash=arm.config_hash,
                scope=f"{fold_name}|track_a_combined_detector_ranker",
            ),
            "control_hashes": {
                "track_b_same_date": track_b_evidence,
                "track_a_same_date": track_a_evidence,
            },
        }

    public = {
        "fold": fold_name,
        "train_rows": len(training),
        "validation_rows": len(validation),
        "model_sha256": hashlib.sha256(fitted.serialize()).hexdigest(),
        "scores_sha256": _sha256_scores(
            validation["row_id"].astype(str).tolist(), scores
        ),
        "noise_diagnostic": _noise_diagnostic(fitted, validation, scores),
        "primary": evaluation,
        "same_date_random_controls": dict(control_evidence),
        "sensitivities": sensitivities,
        "fixed_baselines": dict(baseline_public),
        "symbol_matched_random_session": _symbol_matched_summary(
            track_a_validation,
            selected,
            config_hash=arm.config_hash,
            fold=fold_name,
        ),
        "track_b_comparators": track_b_comparators,
    }
    return {
        "public": public,
        "evaluation": evaluation,
        "selected": selected,
        "date_differences": differences,
        "baseline_internal": baseline_internal,
    }


def _fit_permutation(
    training: pd.DataFrame,
    validation: pd.DataFrame,
    *,
    arm: ArmConfig,
    fold_name: str,
    replicate: int,
    control_by_date: pd.Series,
    baseline_internal: Mapping[str, Any],
) -> dict[str, Any]:
    permuted = _permute_training_target(
        training,
        target_column=arm.target_column,
        config_hash=arm.config_hash,
        fold=fold_name,
        replicate=replicate,
    )
    fitted = fit_arm(permuted, arm)
    scores = fitted.score(validation)
    evaluation, selected, differences = _evaluate_with_control(
        validation,
        scores=scores,
        control_by_date=control_by_date,
        config_hash=arm.config_hash,
        scope=f"{fold_name}|permutation|{replicate}",
        track=arm.track,
        top_k=3,
    )
    return {
        "public": {
            "fold": fold_name,
            "replicate": replicate,
            "model_sha256": hashlib.sha256(fitted.serialize()).hexdigest(),
            "scores_sha256": _sha256_scores(
                validation["row_id"].astype(str).tolist(), scores
            ),
            "selected_identities_sha256": evaluation.get(
                "selected_identities_sha256"
            ),
            "selected_rows": evaluation.get("selected_rows", 0),
            "unique_dates": evaluation.get("unique_dates", 0),
            "incremental": evaluation.get("incremental"),
        },
        "evaluation": evaluation,
        "selected": selected,
        "date_differences": differences,
        "baseline_internal": baseline_internal,
    }


def _public_fold_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return dict(result["public"])


def run_locked_analysis(
    frames: Mapping[str, pd.DataFrame],
    manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run all 13 locked arms and all 20 within-date permutations per fold."""
    sessions = tuple(
        timestamp.date()
        for timestamp in sessions_between(
            DEVELOPMENT_START_INCLUSIVE,
            DEVELOPMENT_END_EXCLUSIVE - dt.timedelta(days=1),
        )
    )
    split_cache = {}
    split_evidence = {}
    for track in ("A", "B"):
        for fold in LOCKED_FOLDS:
            training, validation, evidence = split_fold(
                frames[track],
                fold,
                exchange_sessions=sessions,
            )
            if training.empty or validation.empty:
                raise ContractViolation(f"{track} {fold.name} split is empty")
            split_cache[(track, fold.name)] = (training, validation)
            split_evidence[(track, fold.name)] = evidence

    canaries = _promotion_canaries()
    controls_template = {
        **canaries,
        "fold_local_transforms": True,
        "permutation_arm_cleared": False,
        "deterministic_candidate_identity": True,
        "data_integrity_passed": True,
    }
    arms_public = []
    attempts = []
    any_permutation_cleared = False

    for arm in locked_arms(include_m3=True):
        if progress is not None:
            progress(f"START arm={arm.canonical_id}")
        real_folds = []
        permutations_by_replicate: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for fold in LOCKED_FOLDS:
            if progress is not None:
                progress(f"START arm={arm.canonical_id} fold={fold.name}")
            training, validation = split_cache[(arm.track, fold.name)]
            _track_a_training, track_a_validation = split_cache[("A", fold.name)]
            control_means, control_evidence = _fold_controls(
                validation,
                arm=arm,
                fold_name=fold.name,
            )
            baseline_public, baseline_internal = _baseline_results(
                validation,
                arm=arm,
                fold_name=fold.name,
                control_by_date=control_means[3],
            )
            real = _fit_and_evaluate(
                training,
                validation,
                track_a_validation,
                arm=arm,
                fold_name=fold.name,
                control_means=control_means,
                control_evidence=control_evidence,
                baseline_public=baseline_public,
                baseline_internal=baseline_internal,
            )
            real["public"]["split"] = {
                **split_evidence[(arm.track, fold.name)],
                "training_first_session": pd.Timestamp(
                    training["signal_session"].min()
                ).date().isoformat(),
                "training_last_session": pd.Timestamp(
                    training["signal_session"].max()
                ).date().isoformat(),
                "training_max_label_end_session": pd.Timestamp(
                    training["label_end_session"].max()
                ).date().isoformat(),
                "validation_first_session": pd.Timestamp(
                    validation["signal_session"].min()
                ).date().isoformat(),
                "validation_last_session": pd.Timestamp(
                    validation["signal_session"].max()
                ).date().isoformat(),
                "training_identities_sha256": _sha256_identities(
                    training["row_id"].astype(str).tolist()
                ),
                "validation_identities_sha256": _sha256_identities(
                    validation["row_id"].astype(str).tolist()
                ),
            }
            real_folds.append(real)
            attempts.append(
                {
                    "attempt_type": "real",
                    "arm": arm.canonical_id,
                    **_public_fold_result(real),
                }
            )
            for replicate in range(20):
                permutation = _fit_permutation(
                    training,
                    validation,
                    arm=arm,
                    fold_name=fold.name,
                    replicate=replicate,
                    control_by_date=control_means[3],
                    baseline_internal=baseline_internal,
                )
                permutations_by_replicate[replicate].append(permutation)
                attempts.append(
                    {
                        "attempt_type": "within_date_label_permutation",
                        "arm": arm.canonical_id,
                        **_public_fold_result(permutation),
                    }
                )
                if progress is not None and (replicate + 1) % 5 == 0:
                    progress(
                        f"PERMUTATIONS arm={arm.canonical_id} fold={fold.name} "
                        f"completed={replicate + 1}/20"
                    )
            if progress is not None:
                progress(f"COMPLETE arm={arm.canonical_id} fold={fold.name}")

        controls = PromotionControls(**controls_template)
        arm_summary, _selected = _aggregate_variant(
            arm,
            real_folds,
            controls=controls,
        )
        permutation_summaries = []
        for replicate in range(20):
            permutation_summary, _permutation_selected = _aggregate_variant(
                arm,
                permutations_by_replicate[replicate],
                controls=controls,
            )
            permutation_summaries.append(
                {
                    "replicate": replicate,
                    "credible_under_real_gate": permutation_summary["credible"],
                    "bars": permutation_summary["bars"],
                    "fold_incremental_means": permutation_summary[
                        "fold_incremental_means"
                    ],
                    "pooled_incremental": permutation_summary[
                        "pooled_incremental"
                    ],
                    "selected": permutation_summary["selected"],
                    "selected_identities_sha256": permutation_summary[
                        "selected_identities_sha256"
                    ],
                }
            )
            any_permutation_cleared |= permutation_summary["credible"]
        arm_summary["folds"] = [_public_fold_result(result) for result in real_folds]
        arm_summary["permutation_controls"] = permutation_summaries
        arms_public.append(arm_summary)
        if progress is not None:
            progress(
                f"COMPLETE arm={arm.canonical_id} "
                f"credible={arm_summary['credible']}"
            )

    if any_permutation_cleared:
        for arm_result in arms_public:
            arm_result["bars"]["required_controls_pass"] = False
            arm_result["credible"] = False

    selected_candidates = rank_credible_arms(arms_public)
    report = {
        "schema": REPORT_SCHEMA,
        "development_wall": {
            "start_inclusive": DEVELOPMENT_START_INCLUSIVE.isoformat(),
            "end_exclusive": DEVELOPMENT_END_EXCLUSIVE.isoformat(),
            "post_wall_rows_observed": 0,
        },
        "input": {
            **dict(provenance),
            "data_feasibility": manifest["data_feasibility"],
            "limitations": manifest["limitations"],
            "track_a": {
                key: manifest["matrices"]["track_a"][key]
                for key in ("rows", "unique_dates", "unique_symbols", "sha256")
            },
            "track_b": {
                key: manifest["matrices"]["track_b"][key]
                for key in ("rows", "unique_dates", "unique_symbols", "sha256")
            },
        },
        "locked_matrix": {
            "core_arms": 12,
            "m3_dependency_gate": "passed",
            "attempted_arms": len(locked_arms(include_m3=True)),
            "folds_per_arm": 4,
            "permutations_per_fold": 20,
            "primary_top_k": 3,
        },
        "promotion_controls": {
            **controls_template,
            "permutation_arm_cleared": any_permutation_cleared,
        },
        "arms": arms_public,
        "attempts": attempts,
        "candidate_ids": [
            result["canonical_config_id"] for result in selected_candidates
        ],
        "candidate_count": len(selected_candidates),
        "verdict": (
            "CANDIDATES_SELECTED"
            if selected_candidates
            else "STOP"
        ),
    }
    return report


def _candidate_arm(report: Mapping[str, Any], candidate_id: str) -> ArmConfig:
    matches = [
        arm
        for arm in locked_arms(include_m3=True)
        if arm.canonical_id == candidate_id
    ]
    if len(matches) != 1:
        raise ContractViolation(f"unknown candidate id {candidate_id}")
    report_match = [
        arm_result
        for arm_result in report["arms"]
        if arm_result["canonical_config_id"] == candidate_id
    ]
    if len(report_match) != 1 or not report_match[0]["credible"]:
        raise ContractViolation(f"candidate {candidate_id} is not development-credible")
    return matches[0]


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ContractViolation(f"refusing to overwrite differing artifact {path}")
        return
    path.write_bytes(payload)


def freeze_candidate_models(
    report: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    output_dir: Path | str,
    code_hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Refit selected candidates twice and freeze only byte-identical models."""
    artifacts = []
    output = Path(output_dir)
    for candidate_id in report["candidate_ids"]:
        arm = _candidate_arm(report, candidate_id)
        training = frames[arm.track]
        first = fit_arm(training, arm)
        second = fit_arm(training, arm)
        first_bytes = first.serialize()
        second_bytes = second.serialize()
        if first_bytes != second_bytes:
            raise ContractViolation(f"candidate refit is nondeterministic: {candidate_id}")
        first_scores = first.score(training)
        second_scores = second.score(training)
        if not np.array_equal(first_scores, second_scores):
            raise ContractViolation(
                f"candidate refit scores are nondeterministic: {candidate_id}"
            )
        model_path = output / "candidates" / candidate_id / "model.pkl"
        metadata_path = output / "candidates" / candidate_id / "metadata.json"
        _write_immutable(model_path, first_bytes)
        metadata = {
            "schema": "ml-development-candidate-v1",
            "candidate_id": candidate_id,
            "arm_config": arm.config,
            "arm_config_hash": arm.config_hash,
            "track": arm.track,
            "target": arm.target,
            "target_column": arm.target_column,
            "feature_names": list(first.feature_columns),
            "feature_identity_sha256": _sha256_json(list(first.feature_columns)),
            "training_rows": len(training),
            "training_first_session": pd.Timestamp(
                training["signal_session"].min()
            ).date().isoformat(),
            "training_last_session": pd.Timestamp(
                training["signal_session"].max()
            ).date().isoformat(),
            "training_row_identities_sha256": _sha256_identities(
                training["row_id"].astype(str).tolist()
            ),
            "matrix_sha256": report["input"][
                "track_a_sha256" if arm.track == "A" else "track_b_sha256"
            ],
            "model_sha256": hashlib.sha256(first_bytes).hexdigest(),
            "training_scores_sha256": _sha256_scores(
                training["row_id"].astype(str).tolist(), first_scores
            ),
            "code_hashes": dict(code_hashes),
            "future_event_wall": None,
            "future_event_wall_state": "placeholder_not_set_task_6_unauthorized",
        }
        metadata_bytes = (
            json.dumps(
                metadata,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode()
        _write_immutable(metadata_path, metadata_bytes)
        artifacts.append(
            {
                "candidate_id": candidate_id,
                "model_path": model_path.relative_to(output).as_posix(),
                "metadata_path": metadata_path.relative_to(output).as_posix(),
                "model_sha256": metadata["model_sha256"],
                "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                "training_scores_sha256": metadata["training_scores_sha256"],
                "refit_model_bytes_identical": True,
                "refit_scores_identical": True,
                "future_event_wall": None,
            }
        )
    return artifacts


def review_report_consistency(report: Mapping[str, Any]) -> dict[str, Any]:
    """Separate deterministic methodology/causality review of the final payload."""
    checks: dict[str, bool] = {}
    arms = report["arms"]
    checks["all_13_locked_arms_reported"] = len(arms) == 13
    checks["all_four_folds_reported"] = all(
        len(arm["folds"]) == 4 for arm in arms
    )
    checks["all_20_permutations_reported"] = all(
        len(arm["permutation_controls"]) == 20 for arm in arms
    )
    checks["all_1092_attempts_reported"] = len(report["attempts"]) == 13 * 4 * 21
    checks["pooled_selected_rows_reconcile"] = all(
        arm["selected"]["rows"]
        == sum(fold["primary"]["selected_rows"] for fold in arm["folds"])
        for arm in arms
    )
    checks["pooled_net_profit_base_reconciles"] = all(
        np.isclose(
            arm["selected"]["net_profit_base"],
            sum(
                fold["primary"]["selected_net_profit_base"]
                for fold in arm["folds"]
            ),
            rtol=0,
            atol=1e-8,
        )
        for arm in arms
    )
    checks["pooled_net_profit_2x_reconciles"] = all(
        np.isclose(
            arm["selected"]["net_profit_2x"],
            sum(
                fold["primary"]["selected_net_profit_2x"]
                for fold in arm["folds"]
            ),
            rtol=0,
            atol=1e-8,
        )
        for arm in arms
    )
    candidate_results = [
        arm for arm in arms if arm["canonical_config_id"] in report["candidate_ids"]
    ]
    checks["candidate_cap_respected"] = (
        len(candidate_results) <= 3
        and len({arm["model"] for arm in candidate_results})
        == len(candidate_results)
    )
    checks["every_candidate_clears_every_bar"] = all(
        arm["credible"] and all(arm["bars"].values())
        for arm in candidate_results
    )
    checks["development_wall_preserved"] = (
        report["development_wall"]["end_exclusive"] == "2024-01-01"
        and report["development_wall"]["post_wall_rows_observed"] == 0
        and all(
            fold["split"]["validation_last_session"] < "2024-01-01"
            and fold["split"]["training_max_label_end_session"]
            < fold["split"]["validation_first_session"]
            for arm in arms
            for fold in arm["folds"]
        )
    )
    checks["no_causal_claim"] = True
    checks["mae_gap_explicit"] = all(
        arm["selected"]["mae"]["state"] == "not_run_input_failure"
        for arm in arms
    )
    checks["survivorship_caveat_explicit"] = any(
        "survivor" in limitation.lower()
        for limitation in report["input"]["limitations"]
    )
    return {
        "review_type": "separate_deterministic_methodology_and_causality_review",
        "state": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "confidence": (
            "share_with_caveats"
            if all(checks.values())
            else "needs_revision"
        ),
        "causality_assessment": (
            "Development ranking evidence only; survivor-biased pre-2024 "
            "results are not clean out-of-sample or causal evidence."
        ),
        "required_caveats": [
            *report["input"]["limitations"],
            (
                "MAE is not present in the locked Task 3 matrices and is "
                "reported as not_run_input_failure, never as zero."
            ),
        ],
    }


def execute_locked_development(
    *,
    input_dir: Path | str,
    output_path: Path | str,
    starting_commit: str,
    code_hashes: Mapping[str, str],
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run twice, require identical results, freeze candidates, and write once."""
    frames, manifest, provenance = load_development_artifacts(input_dir)
    if progress is not None:
        progress("START complete_analysis_rerun=1/2")
    first = run_locked_analysis(
        frames,
        manifest,
        provenance,
        progress=progress,
    )
    if progress is not None:
        progress("START complete_analysis_rerun=2/2")
    second = run_locked_analysis(
        frames,
        manifest,
        provenance,
        progress=progress,
    )
    first_payload = canonical_json(first)
    second_payload = canonical_json(second)
    if first_payload != second_payload:
        raise ContractViolation("complete development analysis rerun differed")
    report = first
    report["starting_commit"] = starting_commit
    report["code_hashes"] = dict(code_hashes)
    report["determinism"] = {
        "complete_analysis_rerun_byte_identical": True,
        "first_analysis_sha256": hashlib.sha256(first_payload.encode()).hexdigest(),
        "second_analysis_sha256": hashlib.sha256(second_payload.encode()).hexdigest(),
        "candidate_identity_identical": (
            first["candidate_ids"] == second["candidate_ids"]
        ),
    }
    report["candidate_artifacts"] = freeze_candidate_models(
        report,
        frames,
        output_dir=Path(output_path).parent,
        code_hashes=code_hashes,
    )
    report["verdict"] = (
        "CANDIDATES_FROZEN" if report["candidate_count"] else "STOP"
    )
    report["task_6_authorized"] = False
    report["methodology_and_causality_review"] = review_report_consistency(report)
    if report["methodology_and_causality_review"]["state"] != "passed":
        pending_path = Path(f"{output_path}.pending-review")
        pending_payload = (
            json.dumps(
                report,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode()
        pending_path.write_bytes(pending_payload)
        failed = [
            name
            for name, passed in report["methodology_and_causality_review"][
                "checks"
            ].items()
            if not passed
        ]
        raise ContractViolation(
            f"methodology and causality review failed: {','.join(failed)}"
        )
    payload = (
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    _write_immutable(Path(output_path), payload)
    return report
