
import numpy as np
import pandas as pd

from sts.ml.contracts import canonical_config_hash
from sts.ml.evaluation import (
    LOCKED_FOLDS,
    PromotionControls,
    assess_development_credibility,
    circular_blocked_bootstrap,
    evaluate_scores,
    rank_credible_arms,
    split_fold,
)


def test_fold_purge_and_embargo_use_sessions_not_calendar_days():
    sessions = pd.bdate_range("2015-12-01", "2016-02-01")
    frame = pd.DataFrame(
        {
            "signal_session": sessions,
            "label_end_session": sessions + pd.offsets.BDay(15),
            "symbol": ["AAA"] * len(sessions),
        }
    )
    train, validation, evidence = split_fold(
        frame,
        LOCKED_FOLDS[0],
        exchange_sessions=[day.date() for day in sessions],
    )
    assert (
        pd.to_datetime(train["label_end_session"]) < pd.Timestamp("2016-01-01")
    ).all()
    original_validation_dates = sessions[sessions >= pd.Timestamp("2016-01-01")]
    assert validation["signal_session"].min() == original_validation_dates[15]
    assert evidence["embargoed_validation_sessions"] == 15
    assert evidence["purged_training_rows"] > 0


def test_blocked_bootstrap_constant_hand_case():
    result = circular_blocked_bootstrap(
        np.full(25, 0.25), seed=123, block_size=20, replicates=2000
    )
    assert result == {"mean": 0.25, "lower90": 0.25, "upper90": 0.25}


def test_economic_evaluator_uses_date_level_random_difference():
    rows = []
    for day in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for index in range(20):
            rows.append(
                {
                    "row_id": f"{day.date()}-{index}",
                    "signal_session": day,
                    "symbol": f"S{index:02d}",
                    "net_r_2x": float(index),
                    "gross_profit": float(index + 1),
                    "friction_base": 0.1,
                    "friction_2x": 0.2,
                    "raw_h15_return": 0.01 * index,
                }
            )
    frame = pd.DataFrame(rows)
    scores = frame["net_r_2x"].to_numpy()
    result = evaluate_scores(
        frame,
        scores=scores,
        config_hash=canonical_config_hash({"fixture": 3}),
        fold="F1",
        track="A",
    )
    assert result["selected_rows"] == 6
    assert result["unique_dates"] == 2
    assert result["incremental"]["mean"] > 0
    assert len(result["date_differences"]) == 2


def test_leakage_or_permutation_canary_blocks_promotion():
    good = {
        "future_feature_canary_rejected": True,
        "post_wall_canary_rejected": True,
        "fold_local_transforms": True,
        "permutation_arm_cleared": False,
        "deterministic_candidate_identity": True,
        "data_integrity_passed": True,
    }
    common = {
        "fold_incremental_means": [0.1, 0.2, 0.3, -0.1],
        "pooled_lower90": 0.01,
        "selected_net_profit_base": 1.0,
        "selected_net_profit_2x": 1.0,
        "selected_raw_h15_mean": 0.01,
        "geometry_and_hold_valid": True,
        "selected_n": 100,
        "unique_dates": 60,
        "primary_incremental_mean": 0.2,
        "baseline_incremental_means": {
            "momentum_20_desc": 0.1,
            "pullback_5_asc": 0.0,
            "activity_desc": 0.05,
            "constant_equal": -0.01,
        },
    }
    assert assess_development_credibility(
        **common, controls=PromotionControls(**good)
    )["credible"]
    permutation = {**good, "permutation_arm_cleared": True}
    assert not assess_development_credibility(
        **common, controls=PromotionControls(**permutation)
    )["credible"]
    leakage = {**good, "future_feature_canary_rejected": False}
    assert not assess_development_credibility(
        **common, controls=PromotionControls(**leakage)
    )["credible"]


def test_candidate_ranking_applies_exact_ties_and_one_per_family_cap():
    def result(identifier, model, track, target, incremental, credible=True):
        return {
            "credible": credible,
            "median_fold_incremental_mean": incremental,
            "pooled_lower90": 0.1,
            "median_fold_absolute_net_r_2x": 0.2,
            "model": model,
            "track": track,
            "target": target,
            "canonical_config_id": identifier,
        }

    selected = rank_credible_arms(
        [
            result("B-T1-M1", "M1", "B", "T1", 0.4),
            result("A-T1-M1", "M1", "A", "T1", 0.5),
            result("A-T2-M2", "M2", "A", "T2", 0.3),
            result("A-T1-M3", "M3", "A", "T1", 0.2),
            result("B-T3-M2", "M2", "B", "T3", 0.9, credible=False),
        ]
    )
    assert [row["canonical_config_id"] for row in selected] == [
        "A-T1-M1",
        "A-T2-M2",
        "A-T1-M3",
    ]
