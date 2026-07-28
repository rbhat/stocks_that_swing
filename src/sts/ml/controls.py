"""Deterministic matched controls for grouped ML selection."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable

import numpy as np
import pandas as pd

from sts.ml.contracts import ContractViolation
from sts.ml.units import (
    MIN_TRACK_A_CROSS_SECTION,
    MIN_TRACK_B_TOP3_CROSS_SECTION,
)


def control_seed(
    config_hash: str,
    fold: str,
    signal_session: dt.date,
    replicate: int,
    control_id: str,
) -> int:
    payload = (
        f"{config_hash}|{fold}|{signal_session.isoformat()}|"
        f"{replicate}|{control_id}"
    )
    return int(hashlib.sha256(payload.encode()).hexdigest()[:16], 16)


def _minimum_pool(track: str, top_k: int) -> int:
    if track == "A":
        return MIN_TRACK_A_CROSS_SECTION
    if top_k == 1:
        return 2
    if top_k == 3:
        return MIN_TRACK_B_TOP3_CROSS_SECTION
    if top_k == 5:
        return 6
    return top_k + 1


def select_top_k(
    frame: pd.DataFrame,
    *,
    score_column: str,
    top_k: int = 3,
    track: str,
) -> pd.DataFrame:
    """Select deterministic same-date top-k rows with locked adequacy."""
    if top_k not in {1, 3, 5}:
        raise ContractViolation("top_k must be locked sensitivity 1, 3, or 5")
    required = {"signal_session", "symbol", score_column}
    if not required.issubset(frame):
        raise ContractViolation(f"selection frame lacks {sorted(required - set(frame))}")
    selected = []
    for _day, group in frame.groupby("signal_session", sort=True):
        if len(group) < _minimum_pool(track, top_k):
            continue
        selected.append(
            group.sort_values(
                [score_column, "symbol"],
                ascending=[False, True],
                kind="mergesort",
            ).head(top_k)
        )
    return pd.concat(selected, ignore_index=False) if selected else frame.iloc[0:0].copy()


def random_top_k_controls(
    frame: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
    track: str,
    value_column: str = "net_r_2x",
    top_k: int = 3,
    replicates: int = 100,
    control_id: str = "same_date_random",
) -> pd.DataFrame:
    """Return one mean value for every date/replicate random top-k draw."""
    if replicates != 100:
        raise ContractViolation("same-date random control must use 100 replicates")
    rows = []
    for day_value, group in frame.groupby("signal_session", sort=True):
        day = pd.Timestamp(day_value).date()
        if len(group) < _minimum_pool(track, top_k):
            continue
        ordered = group.sort_values("symbol", kind="mergesort").reset_index(drop=True)
        for replicate in range(replicates):
            rng = np.random.default_rng(
                control_seed(config_hash, fold, day, replicate, control_id)
            )
            positions = rng.choice(len(ordered), size=top_k, replace=False)
            rows.append(
                {
                    "signal_session": pd.Timestamp(day),
                    "replicate": replicate,
                    "control_id": control_id,
                    "mean_value": float(ordered.iloc[positions][value_column].mean()),
                    "selected_symbols": "|".join(
                        sorted(ordered.iloc[positions]["symbol"].astype(str))
                    ),
                }
            )
    return pd.DataFrame(rows)


def track_b_random_comparators(
    track_b_pool: pd.DataFrame,
    track_a_pool: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
    top_k: int = 3,
) -> dict[str, pd.DataFrame]:
    """Build Track B reranking and combined detector-plus-ranker controls."""
    adequate_dates = {
        day
        for day, group in track_b_pool.groupby("signal_session", sort=True)
        if len(group) >= _minimum_pool("B", top_k)
    }
    matched_track_b = track_b_pool[
        track_b_pool["signal_session"].isin(adequate_dates)
    ]
    matched_track_a = track_a_pool[
        track_a_pool["signal_session"].isin(adequate_dates)
    ]
    return {
        "track_b_same_date": random_top_k_controls(
            matched_track_b,
            config_hash=config_hash,
            fold=fold,
            track="B",
            top_k=top_k,
            control_id="track_b_same_date_random",
        ),
        "track_a_same_date": random_top_k_controls(
            matched_track_a,
            config_hash=config_hash,
            fold=fold,
            track="A",
            top_k=top_k,
            control_id="track_a_same_date_random",
        ),
    }


def fixed_control_scores(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return the three simple ranks and constant/equal score."""
    required = {
        "adjusted_return_20",
        "adjusted_return_5",
        "dollar_volume_to_median_20",
    }
    if not required.issubset(frame):
        raise ContractViolation(f"fixed controls lack {sorted(required - set(frame))}")
    # These are explicitly ranks, not raw-value fills. A missing ranking fact
    # remains missing in the matrix but receives the lowest finite score so the
    # economic evaluator can keep the exact eligible pool without treating the
    # fact as zero or accepting a non-finite score.
    momentum = frame["adjusted_return_20"].astype(float).rank(
        method="average", ascending=True, na_option="top"
    )
    pullback = (-frame["adjusted_return_5"].astype(float)).rank(
        method="average", ascending=True, na_option="top"
    )
    activity = frame["dollar_volume_to_median_20"].astype(float).rank(
        method="average", ascending=True, na_option="top"
    )
    return {
        "momentum_20_desc": momentum,
        "pullback_5_asc": pullback,
        "activity_desc": activity,
        "constant_equal": pd.Series(0.0, index=frame.index),
    }


def symbol_matched_random_sessions(
    frame: pd.DataFrame,
    events: pd.DataFrame,
    *,
    config_hash: str,
    fold: str,
) -> pd.DataFrame:
    """Sample one eligible session for each event's exact symbol."""
    by_symbol = {
        symbol: group.sort_values(["signal_session", "symbol"], kind="mergesort")
        for symbol, group in frame.groupby("symbol", sort=True)
    }
    sampled = []
    for replicate, event in enumerate(
        events.sort_values(["signal_session", "symbol"], kind="mergesort").itertuples()
    ):
        choices = by_symbol.get(event.symbol)
        if choices is None or choices.empty:
            continue
        day = pd.Timestamp(event.signal_session).date()
        seed = control_seed(
            config_hash, fold, day, replicate, "symbol_matched_random_session"
        )
        sampled.append(choices.iloc[seed % len(choices)])
    return pd.DataFrame(sampled).reset_index(drop=True) if sampled else frame.iloc[0:0]


def permute_labels_within_date(
    frame: pd.DataFrame,
    *,
    target_columns: Iterable[str],
    config_hash: str,
    fold: str,
    replicate: int,
) -> pd.DataFrame:
    """Permute labels only inside each date group, preserving row identities."""
    if replicate < 0 or replicate >= 20:
        raise ContractViolation("permutation replicate must be in [0, 20)")
    result = frame.copy()
    columns = tuple(target_columns)
    for day_value, group in frame.groupby("signal_session", sort=True):
        day = pd.Timestamp(day_value).date()
        seed = control_seed(config_hash, fold, day, replicate, "label_permutation")
        rng = np.random.default_rng(seed)
        positions = rng.permutation(len(group))
        result.loc[group.index, list(columns)] = (
            group.iloc[positions][list(columns)].to_numpy()
        )
    return result
