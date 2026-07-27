import datetime as dt

import pytest

from sts.ml.contracts import ContractViolation
from sts.ml.units import (
    EligibilityFacts,
    TrackAUnit,
    TrackBEvent,
    deduplicate_track_b,
    evaluate_eligibility,
    group_track_a,
)

DAY = dt.date(2023, 12, 29)


def eligible_facts(**changes):
    values = {
        "symbol": "AAPL",
        "signal_session": DAY,
        "in_frozen_roster": True,
        "causal_bars": 300,
        "adjusted_close": 5.0,
        "average_dollar_volume_20": 20_000_000.0,
        "next_session_open": 5.1,
        "geometry_valid": True,
        "label_path_complete": True,
    }
    values.update(changes)
    return EligibilityFacts(**values)


def test_eligibility_boundaries_pass_and_missing_facts_fail_closed():
    decision = evaluate_eligibility(eligible_facts())
    assert decision.eligible
    assert decision.reason is None

    missing = evaluate_eligibility(eligible_facts(next_session_open=None))
    assert not missing.eligible
    assert missing.reason == "missing_fact:next_session_open"

    assert evaluate_eligibility(
        eligible_facts(in_frozen_roster=False)
    ).reason == "not_in_frozen_roster"
    assert evaluate_eligibility(eligible_facts(causal_bars=299)).reason == (
        "insufficient_causal_bars"
    )
    assert evaluate_eligibility(eligible_facts(adjusted_close=4.99)).reason == (
        "adjusted_close_below_5"
    )
    assert evaluate_eligibility(
        eligible_facts(average_dollar_volume_20=19_999_999)
    ).reason == "average_dollar_volume_20_below_20m"


def test_track_a_groups_by_session_and_rejects_duplicate_units():
    rows = [
        TrackAUnit(symbol=f"S{i:02}", signal_session=DAY)
        for i in reversed(range(20))
    ]
    grouped = group_track_a(rows)

    assert tuple(row.symbol for row in grouped[DAY]) == tuple(
        f"S{i:02}" for i in range(20)
    )
    assert grouped[DAY][0].selection_status == "eligible"

    duplicate = rows + [TrackAUnit(symbol="S00", signal_session=DAY)]
    with pytest.raises(ContractViolation, match="duplicate Track A unit"):
        group_track_a(duplicate)


def test_small_track_a_group_is_explicitly_not_run():
    grouped = group_track_a(
        [TrackAUnit(symbol=f"S{i}", signal_session=DAY) for i in range(19)]
    )
    assert {row.selection_status for row in grouped[DAY]} == {
        "not_run_inadequate_cross_section"
    }


def test_track_b_union_deduplicates_symbol_session_and_preserves_provenance():
    events = [
        TrackBEvent("aapl", DAY, "vc-core"),
        TrackBEvent("AAPL", DAY, "tp-rsi6-w5"),
        TrackBEvent("MSFT", DAY, "vc-core"),
    ]

    units = deduplicate_track_b(events)

    assert [(unit.symbol, unit.signal_session) for unit in units] == [
        ("AAPL", DAY),
        ("MSFT", DAY),
    ]
    assert units[0].detector_sources == ("tp-rsi6-w5", "vc-core")
    assert units[0].row_id != units[1].row_id


def test_track_b_rejects_nonlocked_detector_source():
    with pytest.raises(ContractViolation, match="unknown detector source"):
        deduplicate_track_b([TrackBEvent("AAPL", DAY, "future-detector")])
