from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sts.ml_v2.metrics import calculate_metrics, max_drawdown, nearest_rank


@dataclass(frozen=True)
class _Trade:
    permanent_id: str
    entry_session: dt.date
    net_pnl_2x: Decimal
    net_pnl_base: Decimal
    entry_notional_2x: Decimal
    entry_notional_base: Decimal
    exit_notional_2x: Decimal
    net_r_2x: Decimal
    holding_sessions: int


@dataclass(frozen=True)
class _Mark:
    equity: Decimal
    gross_open_market_value: Decimal
    open_positions: int


@dataclass(frozen=True)
class _Rejection:
    reason: str


def test_hand_calculated_metrics_and_undefined_diagnostics():
    trades = (
        _Trade(
            "a",
            dt.date(2024, 1, 2),
            Decimal(100),
            Decimal(120),
            Decimal(10000),
            Decimal(9990),
            Decimal(10100),
            Decimal("0.5"),
            3,
        ),
        _Trade(
            "b",
            dt.date(2024, 2, 2),
            Decimal(-50),
            Decimal(-40),
            Decimal(5000),
            Decimal(4990),
            Decimal(4950),
            Decimal("-0.25"),
            5,
        ),
        _Trade(
            "b",
            dt.date(2024, 2, 9),
            Decimal(0),
            Decimal(0),
            Decimal(5000),
            Decimal(4990),
            Decimal(5000),
            Decimal(0),
            4,
        ),
    )
    marks = (
        _Mark(Decimal(1000), Decimal(500), 1),
        _Mark(Decimal(900), Decimal(450), 2),
        _Mark(Decimal(1100), Decimal(0), 0),
    )
    metrics = calculate_metrics(
        trades,
        marks,
        (_Rejection("slot_limit"), _Rejection("cash_limit")),
        starting_equity=Decimal(1000),
        exchange_sessions=3,
    )
    assert metrics.total_net_pnl_2x == Decimal(50)
    assert metrics.nrocc_2x == Decimal("0.0025")
    assert metrics.net_portfolio_return_2x == Decimal("0.1")
    assert metrics.max_drawdown_2x == Decimal("0.1")
    assert metrics.profit_factor_2x == Decimal(2)
    assert metrics.win_rate_2x == Decimal(1) / Decimal(3)
    assert metrics.zero_count == 1
    assert metrics.average_r_2x == Decimal("0.08333333333333333333333333333")
    assert metrics.median_r_2x == Decimal(0)
    assert metrics.holding_sessions["median"] == Decimal(4)
    assert metrics.holding_sessions["p90"] == Decimal(5)
    assert metrics.concurrency["slot_skipped_orders"] == 1
    assert metrics.concurrency["cash_skipped_orders"] == 1
    assert metrics.concentration["permanent_id"]["b"] == Decimal(-50)


def test_drawdown_percentile_and_no_trade_states():
    assert max_drawdown(
        [Decimal(100), Decimal(120), Decimal(90), Decimal(95)]
    ) == Decimal("0.25")
    assert nearest_rank([1, 2, 3, 4, 5], Decimal("0.9")) == Decimal(5)
    metrics = calculate_metrics(
        (),
        (_Mark(Decimal(1000), Decimal(0), 0),),
        (),
        starting_equity=Decimal(1000),
        exchange_sessions=1,
    )
    assert metrics.nrocc_2x is None
    assert metrics.profit_factor_2x is None
    assert metrics.win_rate_2x is None
    assert metrics.calmar_2x is None
