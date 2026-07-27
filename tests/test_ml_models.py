import pickle

import numpy as np
import pandas as pd
import pytest

from sts.ml.contracts import ContractViolation, row_identity
from sts.ml.features import feature_names
from sts.ml.models import (
    ArmConfig,
    build_estimator,
    fit_arm,
    locked_arms,
    relevance_grades,
)


def _training_frame(target="T1", track="A", rows=240):
    dates = pd.bdate_range("2020-01-02", periods=rows // 20)
    records = []
    for index in range(rows):
        day = dates[index // 20]
        symbol = f"S{index % 20:02d}"
        record = {
            "track": track,
            "symbol": symbol,
            "signal_session": day,
            "row_id": row_identity(track, symbol, day.date()),
            "relative_net_r_2x": (index % 7) / 7,
            "spy_residual_h15": (index % 11) / 11,
            "useful_opportunity": index % 2,
        }
        record.update(
            {
                name: float(index % 13) if index % 17 else np.nan
                for name in feature_names(track)
            }
        )
        for name in feature_names(track):
            if name.startswith("detector_flag_") or name == "spy_above_ma_200":
                record[name] = index % 2
        records.append(record)
    return pd.DataFrame(records)


def test_locked_arm_matrix_and_exact_estimators():
    arms = locked_arms()
    assert len(arms) == 13
    assert len({arm.canonical_id for arm in arms}) == 13
    ridge = build_estimator(ArmConfig("A", "T1", "M1"))
    assert ridge["estimator"].alpha == 10
    assert ridge["imputer"].add_indicator
    hist = build_estimator(ArmConfig("B", "T3", "M2"))
    assert hist.max_leaf_nodes == 15
    assert hist.min_samples_leaf == 100
    with pytest.raises(ContractViolation, match="only for Track A"):
        ArmConfig("B", "T1", "M3")


def test_relevance_grades_use_target_then_symbol_tie_break():
    frame = pd.DataFrame(
        {
            "signal_session": [pd.Timestamp("2023-01-03")] * 5,
            "symbol": ["E", "D", "C", "B", "A"],
            "relative_net_r_2x": [5.0, 4.0, 3.0, 1.0, 1.0],
        }
    )
    assert relevance_grades(frame, "relative_net_r_2x").tolist() == [4, 3, 2, 1, 0]


@pytest.mark.parametrize(
    "arm",
    [
        ArmConfig("A", "T1", "M1"),
        ArmConfig("A", "T3", "M1"),
        ArmConfig("A", "T1", "M2"),
        ArmConfig("A", "T3", "M2"),
        ArmConfig("A", "T1", "M3"),
    ],
)
def test_synthetic_fit_scores_and_serialization_are_deterministic(arm):
    frame = _training_frame(target=arm.target)
    one = fit_arm(frame, arm)
    two = fit_arm(frame, arm)
    first_scores = one.score(frame)
    second_scores = two.score(frame)
    assert np.array_equal(first_scores, second_scores)
    assert one.serialize() == two.serialize()
    restored = pickle.loads(one.serialize())
    assert np.array_equal(first_scores, restored.score(frame))


def test_classification_single_class_fails_closed():
    frame = _training_frame()
    frame["useful_opportunity"] = 0
    with pytest.raises(ContractViolation, match="both classes"):
        fit_arm(frame, ArmConfig("A", "T3", "M1"))
