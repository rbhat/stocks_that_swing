"""Phase 2.5 stage: feature engineering + a simple classifier screen predicting
whether an event's forward move is positive, trained/evaluated only on IS
data. Screening, not judging — no PROCEED/PARK/STOP verdict here (docs/PLAN.md
Phase 2.5).

Reuses `sweep_signals.DETECTOR_FNS` for event generation (not a new detector
list). Per-event features are computed directly from the price frame around
the signal bar (ATR%, distance from the rolling 20-session high, volume
z-score) rather than duplicating each detector's internal windows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from phase25_common import atomic_write_json, load_is_frames, setup_stage_logger
from phase25_sweep_signals import DETECTOR_FNS
from sts import eventsim, risk

FEATURES = ["atr_pct", "dist_from_20d_high", "volume_z"]


def _make_pipeline() -> Pipeline:
    return Pipeline(
        [("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000))]
    )


def _per_symbol_features(df: pd.DataFrame) -> pd.DataFrame:
    """ATR%, distance-from-20d-high, volume z-score — computed once per
    symbol frame, looked up by signal-bar date for each event."""
    high20 = df["high"].rolling(20).max()
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = tr.rolling(14).mean()
    vol_mean20 = df["volume"].rolling(20).mean()
    vol_std20 = df["volume"].rolling(20).std()
    return pd.DataFrame(
        {
            "atr_pct": atr14 / df["close"],
            "dist_from_20d_high": (high20 - df["close"]) / df["close"],
            "volume_z": (df["volume"] - vol_mean20) / vol_std20,
        },
        index=df.index,
    )


def _build_table(frames: dict[str, pd.DataFrame], detector: str) -> pd.DataFrame:
    """Build the per-event feature table for one detector. Label is the sign
    of the exit-simmed R-multiple (via eventsim._sim_one, default params) —
    the real risk engine's outcome, not a raw forward-direction proxy."""
    fn = DETECTOR_FNS[detector]
    p = dict(eventsim._PARAM_DEFAULTS)
    rows = []
    for symbol, df in frames.items():
        events = fn(symbol, df, {}, detector)
        if not events:
            continue
        feats = _per_symbol_features(df)
        iloc_of = {d: i for i, d in enumerate(df.index.date)}
        atr_series = risk.atr(df, window=p["atr_window"])
        for ev in events:
            sig_iloc = iloc_of.get(ev.date)
            if sig_iloc is None:
                continue
            feat_row = feats.iloc[sig_iloc]
            if feat_row.isna().any():
                continue
            sim = eventsim._sim_one(df, sig_iloc, atr_series, ev, p)
            if sim is None:
                continue
            r_multiple = sim[0]
            rows.append(
                {
                    **{f: float(feat_row[f]) for f in FEATURES},
                    "label": int(r_multiple > 0),
                    "date": ev.date,
                }
            )
    if not rows:
        return pd.DataFrame(columns=FEATURES + ["label", "date"])
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _screen_one_detector(table: pd.DataFrame) -> dict:
    n = len(table)
    n_classes = table["label"].nunique() if n else 0
    positive_rate = float(table["label"].mean()) if n else None
    if n < 10 or n_classes < 2:
        return {
            "model": "LogisticRegression",
            "cv_score": None,
            "feature_importances": {f: None for f in FEATURES},
            "n_events": n,
            "positive_rate": positive_rate,
            "confusion_matrix": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "fold_accuracies": None,
        }

    X = table[FEATURES].to_numpy()
    y = table["label"].to_numpy()
    n_splits = min(5, n_classes and max(2, n // 20))
    n_splits = max(2, min(n_splits, n - 1))
    tscv = TimeSeriesSplit(n_splits=n_splits)
    pipeline = _make_pipeline()
    scores = cross_val_score(pipeline, X, y, cv=tscv, scoring="accuracy")
    cv_score = float(np.mean(scores))
    fold_accuracies = [float(s) for s in scores]

    # Last fold: train on everything before it, evaluate on its held-out slice.
    splits = list(tscv.split(X))
    last_train_idx, last_test_idx = splits[-1]
    last_pipeline = _make_pipeline()
    last_pipeline.fit(X[last_train_idx], y[last_train_idx])
    y_pred = last_pipeline.predict(X[last_test_idx])
    y_true = y[last_test_idx]
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()
    precision = float(precision_score(y_true, y_pred, zero_division=0))
    recall = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))

    pipeline.fit(X, y)
    coef = pipeline.named_steps["clf"].coef_[0]
    importances = {f: float(abs(c)) for f, c in zip(FEATURES, coef)}

    return {
        "model": "LogisticRegression",
        "cv_score": cv_score,
        "feature_importances": importances,
        "n_events": n,
        "positive_rate": positive_rate,
        "confusion_matrix": cm,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fold_accuracies": fold_accuracies,
    }


def run_screen(run_dir: Path, detectors: list[str]) -> None:
    logger = setup_stage_logger("screen_features", run_dir)
    frames = load_is_frames()
    logger.info("loaded %d IS-only frames", len(frames))

    frozen_config = {
        "model": "LogisticRegression",
        "features": FEATURES,
        "detectors": detectors,
    }

    by_detector = {}
    total = len(detectors)
    for i, detector in enumerate(detectors, 1):
        table = _build_table(frames, detector)
        sub_result = _screen_one_detector(table)
        by_detector[detector] = sub_result
        logger.info(
            "[%d/%d] %s -> n=%d, cv_score=%s",
            i, total, detector, sub_result["n_events"], sub_result["cv_score"],
        )

    result = {"frozen_config": frozen_config, "by_detector": by_detector}
    atomic_write_json(result, run_dir / "screen_features" / "results.json")
    logger.info("screen_features done: %d detectors", total)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--detectors", default=",".join(DETECTOR_FNS.keys()))
    args = ap.parse_args()
    run_screen(args.run_dir, args.detectors.split(","))


if __name__ == "__main__":
    main()
