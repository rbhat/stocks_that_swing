"""Pure gross-performance diagnostics for ``swing-ranking-v1``.

These calculations deliberately consume only immutable simulator output and
candidate facts.  They never alter execution accounting or apply a cost.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from sts import calendar
from sts.swing_ranking.contracts import (
    ContractViolation,
    _date,
    _decimal,
    _positive_decimal,
    _sha256,
    _text,
)
from sts.swing_ranking.simulator import SimulationResult, TradeRecord

D0 = Decimal(0)
D1 = Decimal(1)


class MetricsViolation(ContractViolation):
    """The immutable simulator facts cannot support deterministic metrics."""


def _frozen_mapping(value: Mapping[object, object]) -> Mapping[object, object]:
    return MappingProxyType(dict(value))


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def maximum_drawdown(equity: Sequence[Decimal]) -> Decimal:
    """Return peak-to-trough drawdown for a non-empty Decimal equity path."""
    if not equity:
        raise MetricsViolation("equity path cannot be empty")
    values = tuple(_decimal(value, "equity value") for value in equity)
    peak = values[0]
    worst = D0
    for value in values:
        peak = max(peak, value)
        if peak <= D0:
            raise MetricsViolation("equity peak must remain positive")
        worst = max(worst, D1 - value / peak)
    return worst


@dataclass(frozen=True, order=True)
class SignalOccurrence:
    """A strategy-comparison key; symbols intentionally do not participate."""

    permanent_id: str
    session: dt.date

    def __post_init__(self) -> None:
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        object.__setattr__(self, "session", _date(self.session, "signal session"))


@dataclass(frozen=True)
class Distribution:
    """Exact summary of one explicitly selected set of closed trades."""

    count: int
    total: Decimal
    mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0:
            raise MetricsViolation("distribution count must be a non-negative integer")
        object.__setattr__(self, "total", _decimal(self.total, "distribution total"))
        for name in ("mean", "median", "minimum", "maximum"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, f"distribution {name}"))
        if self.count == 0:
            if self.total != D0 or any(getattr(self, name) is not None for name in ("mean", "median", "minimum", "maximum")):
                raise MetricsViolation("empty distribution must contain only zero and None values")
        elif any(getattr(self, name) is None for name in ("mean", "median", "minimum", "maximum")):
            raise MetricsViolation("non-empty distribution requires all summary values")


def _distribution(values: Sequence[Decimal]) -> Distribution:
    if not values:
        return Distribution(0, D0, None, None, None, None)
    total = sum(values, D0)
    return Distribution(
        count=len(values),
        total=total,
        mean=total / Decimal(len(values)),
        median=_median(values),
        minimum=min(values),
        maximum=max(values),
    )


@dataclass(frozen=True)
class YearMetrics:
    """Close-marked portfolio results plus separately labeled realized P&L."""

    year: int
    starting_equity: Decimal
    ending_equity: Decimal
    gross_profit: Decimal
    gross_return: Decimal
    realized_closed_profit: Decimal
    maximum_drawdown: Decimal
    trade_count: int

    def __post_init__(self) -> None:
        if isinstance(self.year, bool) or not isinstance(self.year, int) or self.year < 1:
            raise MetricsViolation("year must be a positive integer")
        for name in (
            "starting_equity",
            "ending_equity",
            "gross_profit",
            "gross_return",
            "realized_closed_profit",
            "maximum_drawdown",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        if self.starting_equity <= D0 or self.ending_equity < D0:
            raise MetricsViolation("year equity values are invalid")
        if self.gross_profit != self.ending_equity - self.starting_equity:
            raise MetricsViolation("year gross_profit must reconcile to marked equity")
        if self.gross_return != self.gross_profit / self.starting_equity:
            raise MetricsViolation("year gross_return must reconcile to marked profit")
        if not D0 <= self.maximum_drawdown <= D1:
            raise MetricsViolation("maximum_drawdown must be in [0, 1]")
        if isinstance(self.trade_count, bool) or not isinstance(self.trade_count, int) or self.trade_count < 0:
            raise MetricsViolation("trade_count must be a non-negative integer")


@dataclass(frozen=True)
class StrategyMetrics:
    """All zero-cost performance and diagnostic outputs for one strategy SHA."""

    strategy_revision_identity: str
    starting_capital: Decimal
    ending_equity: Decimal
    gross_profit: Decimal
    gross_return: Decimal
    maximum_drawdown: Decimal
    profit_drawdown_status: Literal["positive_return_no_drawdown", "defined", "undefined"]
    profit_drawdown: Decimal | None
    trade_count: int
    candidate_count: int
    order_count: int
    filled_order_count: int
    rejected_order_count: int
    dollars_turned_over: Decimal
    turnover: Decimal | None
    profit_per_dollar_turned_over: Decimal | None
    break_even_status: Literal[
        "defined",
        "not_applicable_nonpositive_profit",
        "undefined_no_turnover",
    ]
    break_even_proportional_cost: Decimal | None
    holding_sessions: Distribution
    winners: Distribution
    losers: Distribution
    exposure: Mapping[str, Decimal | None]
    concentration: Mapping[str, Mapping[str, Decimal]]
    yearly: Mapping[str, YearMetrics]
    candidate_signals: tuple[SignalOccurrence, ...]
    filled_trade_signals: tuple[SignalOccurrence, ...]
    rejection_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        _sha256(self.strategy_revision_identity, "strategy_revision_identity")
        object.__setattr__(self, "starting_capital", _positive_decimal(self.starting_capital, "starting_capital"))
        for name in ("ending_equity", "gross_profit", "gross_return", "maximum_drawdown", "dollars_turned_over"):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        if self.ending_equity < D0 or not D0 <= self.maximum_drawdown <= D1 or self.dollars_turned_over < D0:
            raise MetricsViolation("invalid equity, drawdown, or turnover amount")
        if self.gross_profit != self.ending_equity - self.starting_capital:
            raise MetricsViolation("gross_profit must reconcile to ending equity")
        if self.gross_return != self.gross_profit / self.starting_capital:
            raise MetricsViolation("gross_return must reconcile to gross_profit")
        if self.profit_drawdown_status == "positive_return_no_drawdown":
            if not (self.gross_return > D0 and self.maximum_drawdown == D0 and self.profit_drawdown is None):
                raise MetricsViolation("invalid positive_return_no_drawdown state")
        elif self.profit_drawdown_status == "defined":
            if self.maximum_drawdown == D0 or self.profit_drawdown != self.gross_return / self.maximum_drawdown:
                raise MetricsViolation("defined profit_drawdown must reconcile")
        elif self.profit_drawdown_status == "undefined":
            if not (self.maximum_drawdown == D0 and self.profit_drawdown is None):
                raise MetricsViolation("undefined profit_drawdown requires zero drawdown")
        else:
            raise MetricsViolation("unknown profit_drawdown_status")
        for name in ("trade_count", "candidate_count", "order_count", "filled_order_count", "rejected_order_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MetricsViolation(f"{name} must be a non-negative integer")
        if self.order_count != self.filled_order_count + self.rejected_order_count or self.trade_count != self.filled_order_count:
            raise MetricsViolation("order and trade counts do not reconcile")
        if self.candidate_count != self.order_count:
            raise MetricsViolation("every candidate must reconcile to one terminal order")
        for name in ("turnover", "profit_per_dollar_turned_over", "break_even_proportional_cost"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, name))
        if self.break_even_status == "defined":
            if (
                self.break_even_proportional_cost is None
                or self.break_even_proportional_cost <= D0
            ):
                raise MetricsViolation("defined break-even cost must be positive")
        elif self.break_even_status == "not_applicable_nonpositive_profit":
            if self.gross_profit > D0 or self.break_even_proportional_cost is not None:
                raise MetricsViolation("nonpositive-profit break-even state is invalid")
        elif self.break_even_status == "undefined_no_turnover":
            if self.dollars_turned_over != D0 or self.break_even_proportional_cost is not None:
                raise MetricsViolation("no-turnover break-even state is invalid")
        else:
            raise MetricsViolation("unknown break_even_status")
        if not isinstance(self.holding_sessions, Distribution) or not isinstance(self.winners, Distribution) or not isinstance(self.losers, Distribution):
            raise MetricsViolation("trade diagnostics must be Distribution values")
        if self.winners.count + self.losers.count > self.trade_count:
            raise MetricsViolation("winner and loser counts exceed trade_count")
        exposure = dict(self.exposure)
        if set(exposure) != {"mean", "maximum"}:
            raise MetricsViolation("exposure requires mean and maximum")
        for name, value in exposure.items():
            if value is not None:
                value = _decimal(value, f"exposure {name}")
                if value < D0:
                    raise MetricsViolation("exposure cannot be negative")
                exposure[name] = value
        object.__setattr__(self, "exposure", _frozen_mapping(exposure))
        concentration = {
            _text(name, "concentration name"): _frozen_mapping(
                {_text(key, "concentration key"): _decimal(value, "concentration value") for key, value in values.items()}
            )
            for name, values in self.concentration.items()
        }
        object.__setattr__(self, "concentration", _frozen_mapping(concentration))
        yearly = dict(self.yearly)
        if any(
            not isinstance(year, str)
            or not isinstance(value, YearMetrics)
            or str(value.year) != year
            for year, value in yearly.items()
        ):
            raise MetricsViolation("yearly metrics must be keyed by their string year")
        object.__setattr__(self, "yearly", _frozen_mapping(dict(sorted(yearly.items()))))
        candidates = tuple(self.candidate_signals)
        filled = tuple(self.filled_trade_signals)
        if not all(isinstance(item, SignalOccurrence) for item in (*candidates, *filled)):
            raise MetricsViolation("signal overlap facts must be SignalOccurrence values")
        if candidates != tuple(sorted(set(candidates))) or filled != tuple(sorted(set(filled))):
            raise MetricsViolation("signal overlap facts must be unique and sorted")
        if not set(filled).issubset(candidates):
            raise MetricsViolation("filled trade signals must be candidate signals")
        object.__setattr__(self, "candidate_signals", candidates)
        object.__setattr__(self, "filled_trade_signals", filled)
        rejection_counts = dict(self.rejection_counts)
        for reason, count in rejection_counts.items():
            _text(reason, "rejection reason")
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise MetricsViolation("rejection count must be a positive integer")
        if sum(rejection_counts.values()) != self.rejected_order_count:
            raise MetricsViolation("rejection counts do not reconcile")
        object.__setattr__(self, "rejection_counts", _frozen_mapping(dict(sorted(rejection_counts.items()))))


def _hold_sessions(trade: TradeRecord) -> Decimal:
    return Decimal(len(calendar.sessions_between(trade.entry_session, trade.exit_session)))


def _year_metrics(
    trades: Sequence[TradeRecord],
    equity: Sequence[tuple[dt.date, Decimal]],
    starting_capital: Decimal,
) -> Mapping[str, YearMetrics]:
    years = sorted(
        {session.year for session, _ in equity}
        | {trade.exit_session.year for trade in trades}
    )
    values: dict[str, YearMetrics] = {}
    for year in years:
        year_trades = tuple(trade for trade in trades if trade.exit_session.year == year)
        prior_values = tuple(value for session, value in equity if session.year < year)
        start = prior_values[-1] if prior_values else starting_capital
        current_values = tuple(value for session, value in equity if session.year == year)
        end = current_values[-1] if current_values else start
        year_equity = (start, *current_values)
        marked_profit = end - start
        realized_profit = sum((trade.gross_pnl for trade in year_trades), D0)
        values[str(year)] = YearMetrics(
            year=year,
            starting_equity=start,
            ending_equity=end,
            gross_profit=marked_profit,
            gross_return=marked_profit / start,
            realized_closed_profit=realized_profit,
            maximum_drawdown=maximum_drawdown(year_equity),
            trade_count=len(year_trades),
        )
    return _frozen_mapping(values)


def calculate_metrics(
    *,
    strategy_revision_identity: str,
    result: SimulationResult,
    candidates: Sequence[object],
    starting_capital: Decimal,
) -> StrategyMetrics:
    """Calculate all reported metrics without changing gross simulator output."""
    _sha256(strategy_revision_identity, "strategy_revision_identity")
    if not isinstance(result, SimulationResult):
        raise MetricsViolation("result must be a SimulationResult")
    starting_capital = _positive_decimal(starting_capital, "starting_capital")
    result.assert_reconciled(starting_capital)
    candidate_values = tuple(candidates)
    from sts.swing_ranking.contracts import Candidate

    if not all(isinstance(candidate, Candidate) for candidate in candidate_values):
        raise MetricsViolation("candidates must contain Candidate values")
    if any(candidate.strategy_revision_identity != strategy_revision_identity for candidate in candidate_values):
        raise MetricsViolation("candidate strategy revision identity does not match")
    by_identity = {candidate.identity: candidate for candidate in candidate_values}
    if len(by_identity) != len(candidate_values):
        raise MetricsViolation("candidates must be unique by immutable identity")
    if any(trade.candidate_identity not in by_identity for trade in result.trades):
        raise MetricsViolation("every trade must reference a supplied candidate")
    sessions = tuple(record.session for record in result.equity)
    if sessions != tuple(sorted(sessions)) or len(set(sessions)) != len(sessions):
        raise MetricsViolation("equity records must be sorted and unique by session")
    equity = tuple((record.session, record.equity) for record in result.equity)
    ending = equity[-1][1] if equity else starting_capital
    profit = ending - starting_capital
    gross_return = profit / starting_capital
    drawdown = maximum_drawdown((starting_capital, *(value for _, value in equity)))
    if drawdown == D0 and gross_return > D0:
        status: Literal["positive_return_no_drawdown", "defined", "undefined"] = "positive_return_no_drawdown"
        ratio: Decimal | None = None
    elif drawdown == D0:
        status = "undefined"
        ratio = None
    else:
        status = "defined"
        ratio = gross_return / drawdown
    entry_notional = sum(
        (order.quantity * order.fill_price for order in result.orders if order.status == "filled" and order.quantity is not None and order.fill_price is not None),
        D0,
    )
    exit_notional = sum((trade.quantity * trade.exit_price for trade in result.trades), D0)
    turned_over = entry_notional + exit_notional
    average_equity = None if not equity else sum((value for _, value in equity), D0) / Decimal(len(equity))
    turnover = None if average_equity in (None, D0) else turned_over / (Decimal(2) * average_equity)
    profit_per_dollar = None if turned_over == D0 else profit / turned_over
    if turned_over == D0:
        break_even_status: Literal[
            "defined",
            "not_applicable_nonpositive_profit",
            "undefined_no_turnover",
        ] = "undefined_no_turnover"
        break_even = None
    elif profit > D0:
        break_even_status = "defined"
        break_even = profit_per_dollar
    else:
        break_even_status = "not_applicable_nonpositive_profit"
        break_even = None
    holds = tuple(_hold_sessions(trade) for trade in result.trades)
    pnl = tuple(trade.gross_pnl for trade in result.trades)
    exposures = tuple(record.deployed_fraction for record in result.equity)
    concentration_values: dict[str, defaultdict[str, Decimal]] = {
        "entry_session": defaultdict(Decimal),
        "entry_month": defaultdict(Decimal),
        "exit_session": defaultdict(Decimal),
        "permanent_id": defaultdict(Decimal),
        "symbol": defaultdict(Decimal),
    }
    for trade in result.trades:
        concentration_values["entry_session"][trade.entry_session.isoformat()] += trade.gross_pnl
        concentration_values["entry_month"][trade.entry_session.strftime("%Y-%m")] += trade.gross_pnl
        concentration_values["exit_session"][trade.exit_session.isoformat()] += trade.gross_pnl
        concentration_values["permanent_id"][trade.permanent_id] += trade.gross_pnl
        concentration_values["symbol"][trade.symbol] += trade.gross_pnl
    candidate_signals = tuple(sorted({SignalOccurrence(candidate.permanent_id, candidate.signal_session) for candidate in candidate_values}))
    filled_signals = tuple(sorted({SignalOccurrence(by_identity[trade.candidate_identity].permanent_id, by_identity[trade.candidate_identity].signal_session) for trade in result.trades}))
    rejection_counts: defaultdict[str, int] = defaultdict(int)
    for order in result.orders:
        if order.status == "rejected":
            rejection_counts[order.reason] += 1
    filled_count = sum(order.status == "filled" for order in result.orders)
    return StrategyMetrics(
        strategy_revision_identity=strategy_revision_identity,
        starting_capital=starting_capital,
        ending_equity=ending,
        gross_profit=profit,
        gross_return=gross_return,
        maximum_drawdown=drawdown,
        profit_drawdown_status=status,
        profit_drawdown=ratio,
        trade_count=len(result.trades),
        candidate_count=len(candidate_values),
        order_count=len(result.orders),
        filled_order_count=filled_count,
        rejected_order_count=len(result.orders) - filled_count,
        dollars_turned_over=turned_over,
        turnover=turnover,
        profit_per_dollar_turned_over=profit_per_dollar,
        break_even_status=break_even_status,
        break_even_proportional_cost=break_even,
        holding_sessions=_distribution(holds),
        winners=_distribution(tuple(value for value in pnl if value > D0)),
        losers=_distribution(tuple(value for value in pnl if value < D0)),
        exposure={
            "mean": None if not exposures else sum(exposures, D0) / Decimal(len(exposures)),
            "maximum": None if not exposures else max(exposures),
        },
        concentration={name: dict(sorted(values.items())) for name, values in concentration_values.items()},
        yearly=_year_metrics(result.trades, equity, starting_capital),
        candidate_signals=candidate_signals,
        filled_trade_signals=filled_signals,
        rejection_counts=dict(rejection_counts),
    )
