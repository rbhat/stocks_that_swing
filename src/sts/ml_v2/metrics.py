"""Exact ML-v2 accounting and portfolio diagnostics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, localcontext
from types import MappingProxyType
from typing import Any

from sts.ml_v2.contracts import D0, D1, ContractViolation, D


def _value(row: Any, name: str) -> Any:
    return row[name] if isinstance(row, Mapping) else getattr(row, name)


def _sum(rows: Sequence[Any], name: str) -> Decimal:
    return sum((D(_value(row, name), name) for row in rows), D0)


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            key: (
                _freeze_mapping(item)
                if isinstance(item, Mapping)
                else tuple(item)
                if isinstance(item, list)
                else item
            )
            for key, item in value.items()
        }
    )


def nearest_rank(values: Sequence[Decimal | int], percentile: Decimal) -> Decimal:
    """Locked nearest-rank percentile, including for all reported p90s."""
    if not values:
        raise ContractViolation("percentile values cannot be empty")
    if not D0 <= percentile <= D1:
        raise ContractViolation("percentile must be in [0, 1]")
    ordered = sorted(D(value) for value in values)
    rank = max(
        1,
        int(
            (percentile * len(ordered)).to_integral_value(
                rounding=ROUND_CEILING
            )
        ),
    )
    return ordered[rank - 1]


def median(values: Sequence[Decimal | int]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(D(value) for value in values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def max_drawdown(equity: Sequence[Decimal]) -> Decimal:
    if not equity:
        return D0
    peak = equity[0]
    worst = D0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, D1 - value / peak)
    return worst


@dataclass(frozen=True)
class PortfolioMetrics:
    total_net_pnl_2x: Decimal
    total_net_pnl_base: Decimal
    entry_notional_2x: Decimal
    nrocc_2x: Decimal | None
    nrocc_base: Decimal | None
    net_portfolio_return_2x: Decimal
    max_drawdown_2x: Decimal
    cagr_2x: Decimal | None
    calmar_2x: Decimal | None
    profit_factor_2x: Decimal | None
    win_rate_2x: Decimal | None
    zero_count: int
    average_r_2x: Decimal | None
    median_r_2x: Decimal | None
    average_exposure: Decimal | None
    turnover: Decimal | None
    holding_sessions: Mapping[str, Decimal | int | None]
    concurrency: Mapping[str, Decimal | int]
    rejection_counts: Mapping[str, int]
    concentration: Mapping[str, Any]


def calculate_metrics(
    trades: Sequence[Any],
    daily_marks: Sequence[Any],
    rejections: Sequence[Any],
    *,
    starting_equity: Decimal,
    exchange_sessions: int,
) -> PortfolioMetrics:
    start = D(starting_equity, "starting_equity")
    if start <= 0:
        raise ContractViolation("starting_equity must be positive")
    if exchange_sessions < 0:
        raise ContractViolation("exchange_sessions cannot be negative")

    pnl_2x = [_value(trade, "net_pnl_2x") for trade in trades]
    pnl_base = [_value(trade, "net_pnl_base") for trade in trades]
    total_2x = sum((D(value) for value in pnl_2x), D0)
    total_base = sum((D(value) for value in pnl_base), D0)
    entry_notional = _sum(trades, "entry_notional_2x")
    base_entry_notional = _sum(trades, "entry_notional_base")
    ending = (
        D(_value(daily_marks[-1], "equity"), "ending equity")
        if daily_marks
        else start
    )
    portfolio_return = ending / start - D1
    equities = [D(_value(mark, "equity")) for mark in daily_marks]
    drawdown = max_drawdown(equities)

    cagr: Decimal | None = None
    if exchange_sessions > 0 and ending > 0:
        with localcontext() as context:
            context.prec = 50
            cagr = (ending / start) ** (
                Decimal(252) / Decimal(exchange_sessions)
            ) - D1
    calmar = None if cagr is None or drawdown == 0 else cagr / drawdown
    positive = sum((D(value) for value in pnl_2x if D(value) > 0), D0)
    negative = sum((D(value) for value in pnl_2x if D(value) < 0), D0)
    profit_factor = None if negative == 0 else positive / abs(negative)
    wins = sum(D(value) > 0 for value in pnl_2x)
    zeros = sum(D(value) == 0 for value in pnl_2x)
    win_rate = None if not trades else Decimal(wins) / Decimal(len(trades))
    r_values = [D(_value(trade, "net_r_2x")) for trade in trades]
    average_r = (
        None if not r_values else sum(r_values, D0) / Decimal(len(r_values))
    )

    exposures: list[Decimal] = []
    concurrencies: list[int] = []
    for mark in daily_marks:
        equity = D(_value(mark, "equity"))
        gross = D(_value(mark, "gross_open_market_value"))
        exposures.append(D0 if equity == 0 else gross / equity)
        concurrencies.append(int(_value(mark, "open_positions")))
    average_exposure = (
        None
        if not exposures
        else sum(exposures, D0) / Decimal(len(exposures))
    )
    mean_equity = (
        None if not equities else sum(equities, D0) / Decimal(len(equities))
    )
    exits = _sum(trades, "exit_notional_2x")
    turnover = (
        None
        if mean_equity in (None, D0)
        else (entry_notional + exits) / (Decimal(2) * mean_equity)
    )

    holds = [int(_value(trade, "holding_sessions")) for trade in trades]
    holding = {
        "mean": (
            None if not holds else sum(holds) / Decimal(len(holds))
        ),
        "median": median(holds),
        "p90": None if not holds else nearest_rank(holds, Decimal("0.90")),
        "max": None if not holds else max(holds),
    }
    rejection_counts: dict[str, int] = defaultdict(int)
    for rejection in rejections:
        rejection_counts[str(_value(rejection, "reason"))] += 1
    concurrency = {
        "mean": (
            D0
            if not concurrencies
            else Decimal(sum(concurrencies)) / Decimal(len(concurrencies))
        ),
        "p90": (
            D0
            if not concurrencies
            else nearest_rank(concurrencies, Decimal("0.90"))
        ),
        "max": max(concurrencies, default=0),
        "slot_skipped_orders": rejection_counts.get("slot_limit", 0),
        "cash_skipped_orders": rejection_counts.get("cash_limit", 0),
    }

    contribution_groups: dict[str, dict[str, Decimal]] = {
        "entry_date": defaultdict(Decimal),
        "month": defaultdict(Decimal),
        "year": defaultdict(Decimal),
        "permanent_id": defaultdict(Decimal),
    }
    for trade in trades:
        entry_date = _value(trade, "entry_session")
        date_text = entry_date.isoformat() if hasattr(entry_date, "isoformat") else str(entry_date)
        pnl = D(_value(trade, "net_pnl_2x"))
        contribution_groups["entry_date"][date_text] += pnl
        contribution_groups["month"][date_text[:7]] += pnl
        contribution_groups["year"][date_text[:4]] += pnl
        contribution_groups["permanent_id"][
            str(_value(trade, "permanent_id"))
        ] += pnl
    contributors = sorted((D(value) for value in pnl_2x), reverse=True)
    concentration: dict[str, Any] = {
        name: dict(sorted(values.items()))
        for name, values in contribution_groups.items()
    }
    concentration["top_contributors"] = {
        f"top_{count}": sum(contributors[:count], D0)
        for count in (1, 5, 10)
    }

    return PortfolioMetrics(
        total_net_pnl_2x=total_2x,
        total_net_pnl_base=total_base,
        entry_notional_2x=entry_notional,
        nrocc_2x=_ratio(total_2x, entry_notional),
        nrocc_base=_ratio(total_base, base_entry_notional),
        net_portfolio_return_2x=portfolio_return,
        max_drawdown_2x=drawdown,
        cagr_2x=cagr,
        calmar_2x=calmar,
        profit_factor_2x=profit_factor,
        win_rate_2x=win_rate,
        zero_count=zeros,
        average_r_2x=average_r,
        median_r_2x=median(r_values),
        average_exposure=average_exposure,
        turnover=turnover,
        holding_sessions=_freeze_mapping(holding),
        concurrency=_freeze_mapping(concurrency),
        rejection_counts=_freeze_mapping(
            dict(sorted(rejection_counts.items()))
        ),
        concentration=_freeze_mapping(concentration),
    )
