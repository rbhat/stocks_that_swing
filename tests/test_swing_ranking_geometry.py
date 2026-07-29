from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from sts.swing_ranking.contracts import (
    REQUIRED_SOURCE_KINDS,
    Candidate,
    ContractViolation,
    SignalFact,
    swing_ranking_charter,
)
from sts.swing_ranking.geometry import GeometrySpec, PriceFormula, resolve_geometry


def _candidate_with_facts():
    signal_session = dt.date(2024, 1, 2)
    candidate = Candidate(
        strategy_revision_identity="a" * 64,
        input_manifest_identity="b" * 64,
        permanent_id="perm-1",
        symbol="AAA",
        signal_session=signal_session,
        entry_session=dt.date(2024, 1, 3),
        signal_close=Decimal(100),
        average_dollar_volume=Decimal(20_000_000),
        scheduled_earnings_session=None,
        sessions_before_earnings=None,
        facts_as_of={kind: signal_session for kind in REQUIRED_SOURCE_KINDS},
        signal_facts={
            "atr": SignalFact(
                value=Decimal(3),
                available_session=signal_session,
            ),
            "support": SignalFact(
                value=Decimal(94),
                available_session=signal_session,
            ),
        },
        priority_value=Decimal(1),
    )
    return candidate


def test_atr_stop_and_risk_multiple_target_resolve_at_actual_entry():
    candidate = _candidate_with_facts()
    spec = GeometrySpec(
        version="v1",
        stop=PriceFormula(
            kind="entry_minus_fact_multiple",
            primary_fact="atr",
            secondary_fact=None,
            multiple=Decimal("1.5"),
        ),
        target=PriceFormula(
            kind="entry_plus_risk_multiple",
            primary_fact=None,
            secondary_fact=None,
            multiple=Decimal("1.75"),
        ),
        hold_sessions=21,
    )
    geometry = resolve_geometry(
        candidate=candidate,
        entry_price=Decimal(101),
        spec=spec,
        charter=swing_ranking_charter(),
    )
    assert geometry.initial_stop_price == Decimal("96.5")
    assert geometry.target_price == Decimal("108.875")
    assert geometry.planned_reward_risk == Decimal("1.75")


def test_structure_stop_and_invalid_geometry_fail_closed():
    candidate = _candidate_with_facts()
    spec = GeometrySpec(
        version="v1",
        stop=PriceFormula(
            kind="fact_value",
            primary_fact="support",
            secondary_fact=None,
            multiple=Decimal(1),
        ),
        target=PriceFormula(
            kind="entry_plus_risk_multiple",
            primary_fact=None,
            secondary_fact=None,
            multiple=Decimal("1.5"),
        ),
        hold_sessions=21,
    )
    with pytest.raises(ContractViolation, match="strictly greater"):
        resolve_geometry(
            candidate=candidate,
            entry_price=Decimal(100),
            spec=spec,
            charter=swing_ranking_charter(),
        )
