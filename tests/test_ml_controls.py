import datetime as dt

import pandas as pd

from sts.ml.contracts import canonical_config_hash
from sts.ml.controls import (
    control_seed,
    fixed_control_scores,
    permute_labels_within_date,
    random_top_k_controls,
    select_top_k,
    symbol_matched_random_sessions,
    track_b_random_comparators,
)


def _frame():
    rows = []
    for day in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for index in range(20):
            rows.append(
                {
                    "row_id": f"{day.date()}-{index}",
                    "signal_session": day,
                    "symbol": f"S{index:02d}",
                    "score": 1.0 if index < 2 else float(index),
                    "net_r_2x": float(index),
                    "adjusted_return_20": float(index),
                    "adjusted_return_5": float(-index),
                    "dollar_volume_to_median_20": float(index % 3),
                    "T1": float(index),
                }
            )
    return pd.DataFrame(rows)


def test_top_k_tie_break_and_exact_same_date_random_controls():
    frame = _frame()
    selected = select_top_k(frame, score_column="score", track="A")
    assert selected.groupby("signal_session").size().tolist() == [3, 3]
    assert selected[selected["signal_session"] == pd.Timestamp("2023-01-03")][
        "symbol"
    ].tolist() == ["S19", "S18", "S17"]
    config_hash = canonical_config_hash({"fixture": 1})
    one = random_top_k_controls(
        frame, config_hash=config_hash, fold="F1", track="A"
    )
    two = random_top_k_controls(
        frame, config_hash=config_hash, fold="F1", track="A"
    )
    assert len(one) == 200
    pd.testing.assert_frame_equal(one, two)
    assert control_seed(
        config_hash, "F1", dt.date(2023, 1, 3), 0, "same_date_random"
    ) != control_seed(
        config_hash, "F1", dt.date(2023, 1, 3), 1, "same_date_random"
    )


def test_fixed_scores_and_permutations_preserve_date_groups_and_identity():
    frame = _frame()
    scores = fixed_control_scores(frame)
    assert set(scores) == {
        "momentum_20_desc",
        "pullback_5_asc",
        "activity_desc",
        "constant_equal",
    }
    config_hash = canonical_config_hash({"fixture": 2})
    shuffled = permute_labels_within_date(
        frame,
        target_columns=["T1"],
        config_hash=config_hash,
        fold="F2",
        replicate=0,
    )
    assert shuffled["row_id"].equals(frame["row_id"])
    for day, group in frame.groupby("signal_session"):
        assert sorted(group["T1"]) == sorted(
            shuffled[shuffled["signal_session"] == day]["T1"]
        )


def test_fixed_rank_controls_keep_missing_facts_last_without_zero_fill():
    frame = _frame()
    frame.loc[0, "adjusted_return_20"] = float("nan")
    frame.loc[1, "adjusted_return_5"] = float("nan")
    frame.loc[2, "dollar_volume_to_median_20"] = float("nan")

    scores = fixed_control_scores(frame)

    assert scores["momentum_20_desc"].notna().all()
    assert scores["pullback_5_asc"].notna().all()
    assert scores["activity_desc"].notna().all()
    assert scores["momentum_20_desc"].idxmin() == 0
    assert scores["pullback_5_asc"].idxmin() == 1
    assert scores["activity_desc"].idxmin() == 2
    assert frame.loc[0, "adjusted_return_20"] != 0


def test_track_b_controls_include_same_date_track_a_comparator():
    track_a = _frame()
    track_b = track_a.groupby("signal_session", sort=True).head(4)
    config_hash = canonical_config_hash({"fixture": 4})
    controls = track_b_random_comparators(
        track_b,
        track_a,
        config_hash=config_hash,
        fold="F3",
    )
    assert set(controls) == {"track_b_same_date", "track_a_same_date"}
    assert len(controls["track_b_same_date"]) == 200
    assert len(controls["track_a_same_date"]) == 200


def test_symbol_matched_random_session_preserves_symbol_and_count():
    frame = _frame()
    events = frame.groupby("signal_session", sort=True).head(3)
    sampled = symbol_matched_random_sessions(
        frame,
        events,
        config_hash=canonical_config_hash({"fixture": 5}),
        fold="F4",
    )
    assert len(sampled) == len(events)
    assert sorted(sampled["symbol"]) == sorted(events["symbol"])
