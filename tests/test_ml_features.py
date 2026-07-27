import datetime as dt

import pytest

from sts.ml.contracts import ContractViolation
from sts.ml.features import (
    DETECTOR_FLAG_FEATURES,
    FeatureFact,
    FutureFeatureViolation,
    feature_names,
    make_feature_snapshot,
)

DAY = dt.date(2023, 12, 29)


def facts_for(track="A"):
    return {
        name: FeatureFact(
            value=1.0 if name not in DETECTOR_FLAG_FEATURES else 0,
            available_session=DAY,
        )
        for name in feature_names(track)
    }


def test_locked_feature_dictionary_has_exact_track_behavior():
    track_a = feature_names("A")
    track_b = feature_names("B")

    assert {
        "adjusted_return_252",
        "close_to_ma_200",
        "realized_volatility_60",
        "atr14_over_close",
        "atr14_percentile_60",
        "close_location_in_range",
        "volume_to_median_20",
        "dollar_volume_to_median_60",
        "spy_relative_return_252",
        "spy_above_ma_200",
    }.issubset(track_a)
    assert set(DETECTOR_FLAG_FEATURES).issubset(track_a)
    assert set(DETECTOR_FLAG_FEATURES).isdisjoint(track_b)
    assert tuple(name for name in track_a if name not in DETECTOR_FLAG_FEATURES) == track_b


def test_warmup_and_missing_feature_facts_fail_closed():
    with pytest.raises(ContractViolation, match="300 completed sessions"):
        make_feature_snapshot("A", DAY, causal_bars=299, facts=facts_for())

    omitted = facts_for()
    omitted.pop("adjusted_return_1")
    with pytest.raises(ContractViolation, match="missing feature facts"):
        make_feature_snapshot("A", DAY, causal_bars=300, facts=omitted)


def test_missing_and_infinite_values_remain_explicit_not_zero():
    facts = facts_for()
    facts["adjusted_return_1"] = FeatureFact(None, DAY)
    facts["adjusted_return_2"] = FeatureFact(float("inf"), DAY)

    snapshot = make_feature_snapshot("A", DAY, causal_bars=300, facts=facts)

    assert snapshot.values["adjusted_return_1"] is None
    assert snapshot.values["adjusted_return_2"] is None
    assert snapshot.missing == ("adjusted_return_1", "adjusted_return_2")


def test_future_feature_and_unknown_feature_canaries_fail_closed():
    future = facts_for()
    future["adjusted_return_1"] = FeatureFact(
        999.0,
        DAY + dt.timedelta(days=1),
    )
    with pytest.raises(FutureFeatureViolation, match="adjusted_return_1"):
        make_feature_snapshot("A", DAY, causal_bars=300, facts=future)

    unknown = facts_for()
    unknown["future_h15_return"] = FeatureFact(1.0, DAY)
    with pytest.raises(ContractViolation, match="unknown feature facts"):
        make_feature_snapshot("A", DAY, causal_bars=300, facts=unknown)


def test_detector_flags_must_be_binary_when_used_on_track_a():
    facts = facts_for()
    facts[DETECTOR_FLAG_FEATURES[0]] = FeatureFact(0.5, DAY)
    with pytest.raises(ContractViolation, match="binary"):
        make_feature_snapshot("A", DAY, causal_bars=300, facts=facts)
