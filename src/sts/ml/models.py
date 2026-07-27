"""Locked ML arm definitions and fold-local estimators."""

from __future__ import annotations

import dataclasses
import math
import pickle
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from sts.ml.contracts import (
    ContractViolation,
    canonical_config_hash,
    deterministic_noise,
)
from sts.ml.features import feature_names

TARGET_COLUMNS = {
    "T1": "relative_net_r_2x",
    "T2": "spy_residual_h15",
    "T3": "useful_opportunity",
}


@dataclass(frozen=True)
class ArmConfig:
    track: str
    target: str
    model: str

    def __post_init__(self) -> None:
        if self.track not in {"A", "B"}:
            raise ContractViolation("arm track must be A or B")
        if self.target not in TARGET_COLUMNS:
            raise ContractViolation("arm target must be T1, T2, or T3")
        if self.model not in {"M1", "M2", "M3"}:
            raise ContractViolation("arm model must be M1, M2, or M3")
        if self.model == "M3" and (self.track, self.target) != ("A", "T1"):
            raise ContractViolation("M3 is permitted only for Track A + T1")

    @property
    def canonical_id(self) -> str:
        return f"{self.track}-{self.target}-{self.model}"

    @property
    def target_column(self) -> str:
        return TARGET_COLUMNS[self.target]

    @property
    def config(self) -> dict[str, Any]:
        base: dict[str, Any] = dataclasses.asdict(self)
        if self.model == "M1" and self.target in {"T1", "T2"}:
            base["estimator"] = {
                "class": "Ridge",
                "alpha": 10.0,
                "solver": "lsqr",
                "tol": 1e-6,
            }
        elif self.model == "M1":
            base["estimator"] = {
                "class": "LogisticRegression",
                "penalty": "l2",
                "C": 0.1,
                "solver": "lbfgs",
                "max_iter": 2000,
            }
        elif self.model == "M2":
            base["estimator"] = {
                "class": (
                    "HistGradientBoostingClassifier"
                    if self.target == "T3"
                    else "HistGradientBoostingRegressor"
                ),
                "max_leaf_nodes": 15,
                "learning_rate": 0.05,
                "max_iter": 200,
                "l2_regularization": 10.0,
                "min_samples_leaf": 100,
                "early_stopping": False,
            }
        else:
            base["estimator"] = {
                "class": "LGBMRanker",
                "objective": "lambdarank",
                "num_leaves": 15,
                "max_depth": 3,
                "learning_rate": 0.05,
                "n_estimators": 200,
                "min_child_samples": 100,
                "deterministic": True,
                "force_col_wise": True,
                "num_threads": 1,
                "verbosity": -1,
            }
        return base

    @property
    def config_hash(self) -> str:
        return canonical_config_hash(self.config)


def locked_arms(*, include_m3: bool = True) -> tuple[ArmConfig, ...]:
    arms = tuple(
        ArmConfig(track, target, model)
        for track in ("A", "B")
        for target in ("T1", "T2", "T3")
        for model in ("M1", "M2")
    )
    return (*arms, ArmConfig("A", "T1", "M3")) if include_m3 else arms


def build_estimator(arm: ArmConfig) -> Any:
    """Instantiate one exact preregistered estimator."""
    if arm.model == "M1":
        estimator: Any
        if arm.target == "T3":
            estimator = LogisticRegression(
                C=0.1,
                solver="lbfgs",
                max_iter=2000,
            )
        else:
            estimator = Ridge(alpha=10.0, solver="lsqr", tol=1e-6)
        return Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median",
                        add_indicator=True,
                        keep_empty_features=True,
                    ),
                ),
                ("scaler", StandardScaler()),
                ("estimator", estimator),
            ]
        )
    if arm.model == "M2":
        parameters = {
            "max_leaf_nodes": 15,
            "learning_rate": 0.05,
            "max_iter": 200,
            "l2_regularization": 10.0,
            "min_samples_leaf": 100,
            "early_stopping": False,
            # The locked configuration has no stochastic training behavior
            # with early stopping disabled; pin the otherwise materialized
            # internal seed so serialized reruns are byte-identical too.
            "random_state": 0,
        }
        return (
            HistGradientBoostingClassifier(**parameters)
            if arm.target == "T3"
            else HistGradientBoostingRegressor(**parameters)
        )
    return LGBMRanker(
        objective="lambdarank",
        num_leaves=15,
        max_depth=3,
        learning_rate=0.05,
        n_estimators=200,
        min_child_samples=100,
        deterministic=True,
        force_col_wise=True,
        num_threads=1,
        verbosity=-1,
        random_state=0,
    )


def relevance_grades(frame: pd.DataFrame, target_column: str) -> np.ndarray:
    """Assign the locked 0-4 within-date grades with symbol tie-breaking."""
    required = {"signal_session", "symbol", target_column}
    if not required.issubset(frame):
        raise ContractViolation(f"ranking frame lacks {sorted(required - set(frame))}")
    grades = pd.Series(index=frame.index, dtype=np.int64)
    for _day, group in frame.groupby("signal_session", sort=True):
        ordered = group.sort_values(
            [target_column, "symbol"], ascending=[True, True], kind="mergesort"
        )
        size = len(ordered)
        values = [min(4, math.floor(5 * rank / size)) for rank in range(size)]
        grades.loc[ordered.index] = values
    return grades.loc[frame.index].to_numpy(dtype=np.int64)


def model_frame(frame: pd.DataFrame, arm: ArmConfig) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Return locked features plus the per-arm deterministic noise canary."""
    columns = feature_names(arm.track)
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ContractViolation(f"model frame lacks features: {','.join(missing)}")
    if "row_id" not in frame:
        raise ContractViolation("model frame lacks row_id")
    result = frame.loc[:, list(columns)].astype(float).copy()
    result["noise"] = [
        deterministic_noise(arm.config_hash, row_id) for row_id in frame["row_id"]
    ]
    return result, (*columns, "noise")


@dataclass
class FittedArm:
    arm: ArmConfig
    estimator: Any
    feature_columns: tuple[str, ...]

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        features, columns = model_frame(frame, self.arm)
        if columns != self.feature_columns:
            raise ContractViolation("scoring feature identity differs from fit")
        if self.arm.target == "T3":
            probabilities = self.estimator.predict_proba(features)
            return np.asarray(probabilities[:, 1], dtype=float)
        return np.asarray(self.estimator.predict(features), dtype=float)

    def serialize(self) -> bytes:
        """Serialize the exact fitted object for byte-level rerun checks."""
        return pickle.dumps(self, protocol=5)


def fit_arm(frame: pd.DataFrame, arm: ArmConfig) -> FittedArm:
    """Fit one arm on an already purged training fold."""
    if frame.empty:
        raise ContractViolation("training fold is empty")
    if set(frame["track"]) != {arm.track}:
        raise ContractViolation("training rows do not match arm track")
    target = frame[arm.target_column]
    if target.isna().any():
        raise ContractViolation("training target contains missing values")
    if arm.target == "T3" and target.nunique() < 2:
        raise ContractViolation("classification training fold needs both classes")
    features, columns = model_frame(frame, arm)
    estimator = build_estimator(arm)
    if arm.model == "M3":
        ordered = frame.sort_values(
            ["signal_session", "symbol"], kind="mergesort"
        )
        ordered_features = features.loc[ordered.index]
        grades = relevance_grades(ordered, arm.target_column)
        group = ordered.groupby("signal_session", sort=True).size().to_list()
        estimator.fit(ordered_features, grades, group=group)
    else:
        estimator.fit(features, target.to_numpy())
    return FittedArm(arm=arm, estimator=estimator, feature_columns=columns)
