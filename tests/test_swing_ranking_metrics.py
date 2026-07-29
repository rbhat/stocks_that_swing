from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import replace
from decimal import Decimal

from sts.swing_ranking.contracts import REQUIRED_SOURCE_KINDS, Candidate, SignalFact
from sts.swing_ranking.metrics import calculate_metrics
from sts.swing_ranking.ranking import rank_strategies
from sts.swing_ranking.simulator import (
    EquityRecord,
    OrderRecord,
    SimulationResult,
    TradeRecord,
)


def _strategy_id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _metrics(exit_price: Decimal):
    strategy_identity = _strategy_id(f"strategy-{exit_price}")
    input_manifest_identity = _strategy_id("input")
    candidate = Candidate(
        strategy_revision_identity=strategy_identity,
        input_manifest_identity=input_manifest_identity,
        permanent_id="perm-1",
        symbol="OLD",
        signal_session=dt.date(2024, 1, 1),
        entry_session=dt.date(2024, 1, 2),
        signal_close=Decimal(100),
        average_dollar_volume=Decimal(20000000),
        scheduled_earnings_session=None,
        sessions_before_earnings=None,
        facts_as_of={kind: dt.date(2024, 1, 1) for kind in REQUIRED_SOURCE_KINDS},
        signal_facts={
            "close": SignalFact(
                value=Decimal(100),
                available_session=dt.date(2024, 1, 1),
            )
        },
        priority_value=Decimal(1),
    )
    order = OrderRecord(
        candidate_identity=candidate.identity,
        permanent_id=candidate.permanent_id,
        session=candidate.entry_session,
        status="filled",
        reason="filled",
        quantity=Decimal(100),
        fill_price=Decimal(100),
        cost=Decimal(0),
    )
    pnl = (exit_price - Decimal(100)) * Decimal(100)
    trade = TradeRecord(
        order_identity=order.identity,
        candidate_identity=candidate.identity,
        permanent_id=candidate.permanent_id,
        symbol=candidate.symbol,
        entry_session=candidate.entry_session,
        entry_price=Decimal(100),
        quantity=Decimal(100),
        exit_session=dt.date(2024, 1, 3),
        exit_price=exit_price,
        exit_reason="target" if pnl > 0 else "stop" if pnl < 0 else "time",
        gross_pnl=pnl,
        cost=Decimal(0),
    )
    result = SimulationResult(
        orders=(order,),
        trades=(trade,),
        equity=(
            EquityRecord(
                session=trade.exit_session,
                cash=Decimal(100000) + pnl,
                position_value=Decimal(0),
                equity=Decimal(100000) + pnl,
                deployed_fraction=Decimal(0),
            ),
        ),
        events=(),
    )
    return calculate_metrics(
        strategy_revision_identity=strategy_identity,
        result=result,
        candidates=(candidate,),
        starting_capital=Decimal(100000),
    )


def test_metrics_are_gross_and_cost_diagnostics_do_not_change_equity() -> None:
    metrics = _metrics(Decimal(110))

    assert metrics.gross_profit == Decimal(1000)
    assert metrics.gross_return == Decimal("0.01")
    assert metrics.maximum_drawdown == Decimal(0)
    assert metrics.profit_drawdown_status == "positive_return_no_drawdown"
    assert metrics.profit_drawdown is None
    assert metrics.dollars_turned_over == Decimal(21000)
    assert metrics.profit_per_dollar_turned_over == Decimal(1000) / Decimal(21000)
    assert metrics.break_even_status == "defined"
    assert metrics.break_even_proportional_cost == metrics.profit_per_dollar_turned_over
    assert metrics.holding_sessions.median == Decimal(2)
    assert metrics.winners.count == 1
    assert metrics.losers.count == 0
    assert metrics.exposure["maximum"] == Decimal(0)
    assert metrics.yearly["2024"].maximum_drawdown == Decimal(0)


def test_rankings_are_independent_sha_tied_and_report_signal_overlap() -> None:
    positive = replace(_metrics(Decimal(110)), strategy_revision_identity=_strategy_id("positive"))
    zero = replace(_metrics(Decimal(100)), strategy_revision_identity=_strategy_id("zero"))
    negative = replace(_metrics(Decimal(95)), strategy_revision_identity=_strategy_id("negative"))

    report = rank_strategies((zero, negative, positive), top_n=2)

    assert report.profit[0].strategy_revision_identity == positive.strategy_revision_identity
    assert report.drawdown[0].strategy_revision_identity == min(
        positive.strategy_revision_identity,
        zero.strategy_revision_identity,
    )
    assert report.profit_drawdown[0].strategy_revision_identity == positive.strategy_revision_identity
    assert report.profit_drawdown[-1].strategy_revision_identity == negative.strategy_revision_identity
    assert rank_strategies((zero, negative, positive), top_n=3).profit_drawdown[
        -1
    ].strategy_revision_identity == zero.strategy_revision_identity
    assert {row.strategy_revision_identity for row in report.comparison} == {
        positive.strategy_revision_identity,
        zero.strategy_revision_identity,
        negative.strategy_revision_identity,
    }
    assert all(overlap.candidate_signal_intersection == 1 for overlap in report.overlaps)
    assert all(overlap.filled_trade_intersection == 1 for overlap in report.overlaps)


def test_year_metrics_use_preceding_equity_for_a_carry_trade() -> None:
    strategy_identity = _strategy_id("carry")
    candidate = Candidate(
        strategy_revision_identity=strategy_identity,
        input_manifest_identity=_strategy_id("input"),
        permanent_id="perm-1",
        symbol="AAA",
        signal_session=dt.date(2023, 12, 28),
        entry_session=dt.date(2023, 12, 29),
        signal_close=Decimal(100),
        average_dollar_volume=Decimal(20000000),
        scheduled_earnings_session=None,
        sessions_before_earnings=None,
        facts_as_of={
            kind: dt.date(2023, 12, 28) for kind in REQUIRED_SOURCE_KINDS
        },
        signal_facts={
            "close": SignalFact(
                value=Decimal(100),
                available_session=dt.date(2023, 12, 28),
            )
        },
        priority_value=Decimal(1),
    )
    order = OrderRecord(
        candidate_identity=candidate.identity,
        permanent_id="perm-1",
        session=dt.date(2023, 12, 29),
        status="filled",
        reason="filled",
        quantity=Decimal(100),
        fill_price=Decimal(100),
        cost=Decimal(0),
    )
    trade = TradeRecord(
        order_identity=order.identity,
        candidate_identity=candidate.identity,
        permanent_id="perm-1",
        symbol="AAA",
        entry_session=dt.date(2023, 12, 29),
        entry_price=Decimal(100),
        quantity=Decimal(100),
        exit_session=dt.date(2024, 1, 2),
        exit_price=Decimal(110),
        exit_reason="target",
        gross_pnl=Decimal(1000),
        cost=Decimal(0),
    )
    result = SimulationResult(
        orders=(order,),
        trades=(trade,),
        equity=(
            EquityRecord(
                session=dt.date(2023, 12, 29),
                cash=Decimal(90000),
                position_value=Decimal(10500),
                equity=Decimal(100500),
                deployed_fraction=Decimal(10500) / Decimal(100500),
            ),
            EquityRecord(
                session=dt.date(2024, 1, 2),
                cash=Decimal(101000),
                position_value=Decimal(0),
                equity=Decimal(101000),
                deployed_fraction=Decimal(0),
            ),
        ),
        events=(),
    )
    metrics = calculate_metrics(
        strategy_revision_identity=strategy_identity,
        result=result,
        candidates=(candidate,),
        starting_capital=Decimal(100000),
    )
    assert metrics.yearly["2023"].gross_profit == Decimal(500)
    assert metrics.yearly["2023"].realized_closed_profit == Decimal(0)
    assert metrics.yearly["2024"].starting_equity == Decimal(100500)
    assert metrics.yearly["2024"].gross_profit == Decimal(500)
    assert metrics.yearly["2024"].realized_closed_profit == Decimal(1000)
