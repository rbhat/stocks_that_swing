import datetime as dt

import pandas as pd
import pytest

from sts.ml.contracts import canonical_config_hash, row_identity
from sts.ml.controls import permute_labels_within_date, random_top_k_controls
from sts.ml.development import (
    _control_mean_by_date,
    _evaluate_with_control,
    _permute_training_target,
    _sha256_control_frame,
    _stream_random_control,
    bucket_score_rank,
    review_report_consistency,
    summarize_selected_rows,
    validate_matrix_frame,
)
from sts.ml.evaluation import evaluate_scores
from sts.ml.features import feature_names
from sts.ml.walls import WallViolation


def _matrix_row(track: str = "A") -> dict:
    signal_session = dt.date(2023, 12, 1)
    row = {
        "schema": "ml-development-data-v1",
        "config_hash": canonical_config_hash({"fixture": "development"}),
        "row_id": row_identity(track, "AAA", signal_session),
        "track": track,
        "symbol": "AAA",
        "signal_session": pd.Timestamp(signal_session),
        "label_end_session": pd.Timestamp("2023-12-22"),
        "entry_session": pd.Timestamp("2023-12-04"),
        "exit_session": pd.Timestamp("2023-12-22"),
        "selection_status": "eligible",
        "entry_fill": 100.0,
        "stop_initial": 96.0,
        "target_initial": 108.0,
        "initial_risk_pct": 0.04,
        "planned_r": 2.0,
        "hold_sessions": 15,
        "gross_profit": 2.0,
        "friction_base": 0.2,
        "friction_2x": 0.4,
        "net_r_base": 0.45,
        "net_r_2x": 0.40,
        "raw_h15_return": 0.02,
        "relative_net_r_2x": 0.20,
        "spy_residual_h15": 0.01,
        "useful_opportunity": 1,
        "dollar_volume_to_median_20": 1.1,
        "spy_above_ma_200": 1.0,
        "exit_reason": "time",
    }
    for name in feature_names(track):
        row.setdefault(name, 0.0)
    return row


def test_matrix_validation_refuses_post_wall_canary():
    row = _matrix_row()
    frame = pd.DataFrame([row])
    validate_matrix_frame(
        frame,
        track="A",
        config_hash=row["config_hash"],
    )

    frame.loc[0, "signal_session"] = pd.Timestamp("2024-01-01")
    with pytest.raises(WallViolation, match="on or after development end"):
        validate_matrix_frame(
            frame,
            track="A",
            config_hash=row["config_hash"],
        )


def test_selected_summary_keeps_missing_mae_explicit():
    selected = pd.DataFrame([_matrix_row()])
    selected["score_rank_fraction"] = [0.01]
    summary = summarize_selected_rows(selected)

    assert summary["rows"] == 1
    assert summary["net_r_2x_mean"] == 0.40
    assert summary["mae"] == {
        "state": "not_run_input_failure",
        "reason": "mae_column_absent_from_locked_development_matrix",
    }
    assert summary["slices"]["score_bucket"]["top_quartile"]["rows"] == 1


@pytest.mark.parametrize(
    ("rank_fraction", "expected"),
    [
        (0.25, "top_quartile"),
        (0.50, "second_quartile"),
        (0.50001, "bottom_half"),
    ],
)
def test_score_rank_buckets_are_fixed(rank_fraction, expected):
    assert bucket_score_rank(rank_fraction) == expected


def test_cached_control_evaluator_matches_task4_primary_economics():
    rows = []
    for day in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for index in range(20):
            row = _matrix_row()
            row.update(
                {
                    "row_id": f"row-{day.date()}-{index}",
                    "signal_session": day,
                    "symbol": f"S{index:02d}",
                    "net_r_2x": float(index),
                    "gross_profit": float(index + 1),
                    "friction_base": 0.1,
                    "friction_2x": 0.2,
                    "raw_h15_return": index / 100,
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    scores = frame["net_r_2x"].to_numpy()
    config_hash = canonical_config_hash({"fixture": "cached-control"})
    expected = evaluate_scores(
        frame,
        scores=scores,
        config_hash=config_hash,
        fold="F1",
        track="A",
    )
    controls = random_top_k_controls(
        frame,
        config_hash=config_hash,
        fold="F1",
        track="A",
    )
    actual, selected, differences = _evaluate_with_control(
        frame,
        scores=scores,
        control_by_date=_control_mean_by_date(controls),
        config_hash=config_hash,
        scope="F1",
        track="A",
        top_k=3,
    )

    assert actual["selected_rows"] == expected["selected_rows"]
    assert actual["selected_net_r_2x_mean"] == expected["selected_net_r_2x_mean"]
    assert actual["incremental"] == expected["incremental"]
    assert selected["row_id"].tolist() == expected["selected_identities"]
    assert differences == expected["date_differences"]


@pytest.mark.parametrize("top_k", [1, 3, 5])
def test_streamed_random_controls_match_task4_details(top_k):
    rows = []
    for day in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for index in range(20):
            row = _matrix_row()
            row.update(
                {
                    "row_id": f"row-{day.date()}-{index}",
                    "signal_session": day,
                    "symbol": f"S{index:02d}",
                    "net_r_2x": float(index),
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    config_hash = canonical_config_hash({"fixture": "stream-control"})
    expected = random_top_k_controls(
        frame,
        config_hash=config_hash,
        fold="F2",
        track="A",
        top_k=top_k,
    )
    actual_means, evidence = _stream_random_control(
        frame,
        config_hash=config_hash,
        fold="F2",
        track="A",
        top_k=top_k,
    )

    pd.testing.assert_series_equal(
        actual_means,
        _control_mean_by_date(expected),
        check_names=False,
    )
    assert evidence["rows"] == len(expected)
    assert evidence["sha256"] == _sha256_control_frame(expected)


def test_efficient_target_permutation_matches_task4_control():
    rows = []
    for day in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for index in range(20):
            row = _matrix_row()
            row.update(
                {
                    "row_id": f"row-{day.date()}-{index}",
                    "signal_session": day,
                    "symbol": f"S{index:02d}",
                    "relative_net_r_2x": float(index),
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    config_hash = canonical_config_hash({"fixture": "permutation"})
    expected = permute_labels_within_date(
        frame,
        target_columns=["relative_net_r_2x"],
        config_hash=config_hash,
        fold="F3",
        replicate=7,
    )
    actual = _permute_training_target(
        frame,
        target_column="relative_net_r_2x",
        config_hash=config_hash,
        fold="F3",
        replicate=7,
    )

    pd.testing.assert_frame_equal(actual, expected)


def test_report_review_allows_only_roundoff_scale_profit_reconciliation():
    fold = {
        "primary": {
            "selected_rows": 1,
            "selected_net_profit_base": 1.0,
            "selected_net_profit_2x": 0.5,
        },
        "split": {
            "training_max_label_end_session": "2015-12-31",
            "validation_first_session": "2016-01-25",
            "validation_last_session": "2017-12-29",
        },
    }
    arms = [
        {
            "canonical_config_id": f"arm-{index}",
            "model": f"model-{index}",
            "credible": False,
            "bars": {"bar": False},
            "folds": [fold] * 4,
            "permutation_controls": [{}] * 20,
            "selected": {
                "rows": 4,
                "net_profit_base": 4.0 + 5e-9,
                "net_profit_2x": 2.0 - 5e-9,
                "mae": {"state": "not_run_input_failure"},
            },
        }
        for index in range(13)
    ]
    report = {
        "arms": arms,
        "attempts": [{}] * (13 * 4 * 21),
        "candidate_ids": [],
        "development_wall": {
            "end_exclusive": "2024-01-01",
            "post_wall_rows_observed": 0,
        },
        "input": {
            "limitations": [
                "Historical roster is survivor-biased development evidence."
            ]
        },
    }

    review = review_report_consistency(report)

    assert review["state"] == "passed"
