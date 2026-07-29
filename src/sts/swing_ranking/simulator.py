"""The one zero-cost, event-sourced simulator for ``swing-ranking-v1``.

The module owns execution ordering and accounting and has no alternate
simulation path.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from sts.swing_ranking.contracts import (
    Candidate,
    ContractViolation,
    DiscoveryProtocol,
    EntryGeometry,
    GeometryProgram,
    StrategyRevision,
    _date,
    _decimal,
    _freeze_mapping,
    _positive_decimal,
    _sha256,
    _text,
)
from sts.swing_ranking.identity import identity_hash

D0 = Decimal(0)
D1 = Decimal(1)
ZERO_COST = Decimal(0)


class SimulationViolation(ContractViolation):
    """The supplied execution frame cannot support one deterministic run."""


def _quantity(value: Decimal, name: str) -> Decimal:
    value = _positive_decimal(value, name)
    if value != value.to_integral_value():
        raise ContractViolation(f"{name} must be a whole-share Decimal")
    return value


@dataclass(frozen=True)
class DailyBar:
    """One completed daily bar expressed entirely in Decimal price values."""

    session: dt.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", _date(self.session, "bar session"))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, _positive_decimal(getattr(self, name), f"bar {name}"))
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ContractViolation("bar low/high must contain open and close")


@dataclass(frozen=True)
class OrderRecord:
    """Exactly one terminal filled or rejected order for each candidate."""

    candidate_identity: str
    permanent_id: str
    session: dt.date
    status: Literal["filled", "rejected"]
    reason: str
    quantity: Decimal | None
    fill_price: Decimal | None
    cost: Decimal

    def __post_init__(self) -> None:
        _sha256(self.candidate_identity, "order candidate_identity")
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "order permanent_id"))
        object.__setattr__(self, "session", _date(self.session, "order session"))
        if self.status not in ("filled", "rejected"):
            raise ContractViolation("order status must be filled or rejected")
        object.__setattr__(self, "reason", _text(self.reason, "order reason"))
        object.__setattr__(self, "cost", _decimal(self.cost, "order cost"))
        if self.cost != ZERO_COST:
            raise ContractViolation("swing-ranking-v1 orders must have zero cost")
        if self.status == "filled":
            if self.quantity is None or self.fill_price is None:
                raise ContractViolation("filled order requires quantity and fill_price")
            object.__setattr__(self, "quantity", _quantity(self.quantity, "order quantity"))
            object.__setattr__(self, "fill_price", _positive_decimal(self.fill_price, "order fill_price"))
        elif self.quantity is not None or self.fill_price is not None:
            raise ContractViolation("rejected order cannot have fill facts")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/order/v1", self)


@dataclass(frozen=True)
class TradeRecord:
    """A closed, gross, zero-cost long trade."""

    order_identity: str
    candidate_identity: str
    permanent_id: str
    symbol: str
    entry_session: dt.date
    entry_price: Decimal
    quantity: Decimal
    exit_session: dt.date
    exit_price: Decimal
    exit_reason: Literal["gap_stop", "gap_target", "stop", "target", "time"]
    gross_pnl: Decimal
    cost: Decimal

    def __post_init__(self) -> None:
        _sha256(self.order_identity, "trade order_identity")
        _sha256(self.candidate_identity, "trade candidate_identity")
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "trade permanent_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "trade symbol").upper())
        entry = _date(self.entry_session, "trade entry_session")
        exit_session = _date(self.exit_session, "trade exit_session")
        if exit_session < entry:
            raise ContractViolation("trade exit_session cannot precede entry_session")
        entry_price = _positive_decimal(self.entry_price, "trade entry_price")
        exit_price = _positive_decimal(self.exit_price, "trade exit_price")
        quantity = _quantity(self.quantity, "trade quantity")
        if self.exit_reason not in {"gap_stop", "gap_target", "stop", "target", "time"}:
            raise ContractViolation("unknown trade exit_reason")
        gross_pnl = _decimal(self.gross_pnl, "trade gross_pnl")
        if gross_pnl != (exit_price - entry_price) * quantity:
            raise ContractViolation("trade gross_pnl must reconcile to prices and quantity")
        cost = _decimal(self.cost, "trade cost")
        if cost != ZERO_COST:
            raise ContractViolation("swing-ranking-v1 trades must have zero cost")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/trade/v1", self)


@dataclass(frozen=True)
class EquityRecord:
    """A close-marked daily portfolio accounting record."""

    session: dt.date
    cash: Decimal
    position_value: Decimal
    equity: Decimal
    deployed_fraction: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", _date(self.session, "equity session"))
        cash = _decimal(self.cash, "equity cash")
        value = _decimal(self.position_value, "equity position_value")
        equity = _decimal(self.equity, "equity equity")
        deployed = _decimal(self.deployed_fraction, "equity deployed_fraction")
        if cash < D0 or value < D0 or equity < D0 or deployed < D0:
            raise ContractViolation("equity values cannot be negative")
        if equity != cash + value:
            raise ContractViolation("equity must reconcile to cash plus position_value")
        expected = D0 if equity == D0 else value / equity
        if deployed != expected:
            raise ContractViolation("deployed_fraction must reconcile to equity")

    @property
    def identity(self) -> str:
        return identity_hash("swing-ranking-v1/equity/v1", self)


@dataclass(frozen=True)
class EventRecord:
    """A chained, canonical event.  Its hash is deterministic and tamper-evident."""

    sequence: int
    session: dt.date
    event_type: Literal["order_filled", "order_rejected", "trade_closed", "equity_mark"]
    candidate_identity: str | None
    order_identity: str | None
    trade_identity: str | None
    payload: Mapping[str, Any]
    previous_hash: str | None
    event_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ContractViolation("event sequence must be a positive integer")
        object.__setattr__(self, "session", _date(self.session, "event session"))
        if self.event_type not in {"order_filled", "order_rejected", "trade_closed", "equity_mark"}:
            raise ContractViolation("unknown event_type")
        for name in ("candidate_identity", "order_identity", "trade_identity"):
            value = getattr(self, name)
            if value is not None:
                _sha256(value, name)
        if self.previous_hash is not None:
            _sha256(self.previous_hash, "previous_hash")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload, "event payload"))
        _sha256(self.event_hash, "event_hash")
        if self.event_hash != self.computed_hash:
            raise ContractViolation("event_hash does not match the canonical event payload")

    @property
    def computed_hash(self) -> str:
        return identity_hash(
            "swing-ranking-v1/event/v1",
            {
                "sequence": self.sequence,
                "session": self.session,
                "event_type": self.event_type,
                "candidate_identity": self.candidate_identity,
                "order_identity": self.order_identity,
                "trade_identity": self.trade_identity,
                "payload": self.payload,
                "previous_hash": self.previous_hash,
            },
        )


@dataclass(frozen=True)
class SimulationResult:
    """Complete durable output of the single simulator path."""

    orders: tuple[OrderRecord, ...]
    trades: tuple[TradeRecord, ...]
    equity: tuple[EquityRecord, ...]
    events: tuple[EventRecord, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(item, OrderRecord) for item in self.orders):
            raise ContractViolation("orders must contain OrderRecord values")
        if not all(isinstance(item, TradeRecord) for item in self.trades):
            raise ContractViolation("trades must contain TradeRecord values")
        if not all(isinstance(item, EquityRecord) for item in self.equity):
            raise ContractViolation("equity must contain EquityRecord values")
        if not all(isinstance(item, EventRecord) for item in self.events):
            raise ContractViolation("events must contain EventRecord values")
        if len({order.candidate_identity for order in self.orders}) != len(self.orders):
            raise ContractViolation("result has more than one terminal order per candidate")
        if len({event.sequence for event in self.events}) != len(self.events):
            raise ContractViolation("event sequences must be unique")
        if tuple(event.sequence for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise ContractViolation("event sequences must be contiguous")
        for index, event in enumerate(self.events):
            previous = self.events[index - 1].event_hash if index else None
            if event.previous_hash != previous:
                raise ContractViolation("event hash chain does not reconcile")

    @property
    def ending_equity(self) -> Decimal:
        return self.equity[-1].equity if self.equity else D0

    def assert_reconciled(self, starting_capital: Decimal) -> None:
        starting_capital = _positive_decimal(starting_capital, "starting_capital")
        realized = sum((trade.gross_pnl for trade in self.trades), D0)
        if self.ending_equity != starting_capital + realized:
            raise SimulationViolation("ending equity does not reconcile to gross realized P&L")
        filled = {order.identity for order in self.orders if order.status == "filled"}
        if {trade.order_identity for trade in self.trades} != filled:
            raise SimulationViolation("every filled order must reconcile to one closed trade")


@dataclass(frozen=True)
class _Position:
    candidate: Candidate
    order: OrderRecord
    geometry: EntryGeometry
    quantity: Decimal
    entry_price: Decimal
    entry_index: int


def _event(
    events: list[EventRecord],
    *,
    session: dt.date,
    event_type: Literal["order_filled", "order_rejected", "trade_closed", "equity_mark"],
    candidate_identity: str | None,
    order_identity: str | None,
    trade_identity: str | None,
    payload: Mapping[str, Any],
) -> EventRecord:
    sequence = len(events) + 1
    previous = events[-1].event_hash if events else None
    digest = identity_hash(
        "swing-ranking-v1/event/v1",
        {
            "sequence": sequence,
            "session": session,
            "event_type": event_type,
            "candidate_identity": candidate_identity,
            "order_identity": order_identity,
            "trade_identity": trade_identity,
            "payload": payload,
            "previous_hash": previous,
        },
    )
    event = EventRecord(
        sequence=sequence,
        session=session,
        event_type=event_type,
        candidate_identity=candidate_identity,
        order_identity=order_identity,
        trade_identity=trade_identity,
        payload=payload,
        previous_hash=previous,
        event_hash=digest,
    )
    events.append(event)
    return event


def _indexed_bars(
    bars_by_permanent_id: Mapping[str, Sequence[DailyBar]],
) -> dict[str, tuple[DailyBar, ...]]:
    if not isinstance(bars_by_permanent_id, Mapping):
        raise SimulationViolation("bars_by_permanent_id must be a mapping")
    indexed: dict[str, tuple[DailyBar, ...]] = {}
    for permanent_id, raw_bars in bars_by_permanent_id.items():
        permanent_id = _text(permanent_id, "bar permanent_id")
        bars = tuple(raw_bars)
        if not bars or not all(isinstance(bar, DailyBar) for bar in bars):
            raise SimulationViolation("each permanent ID requires completed DailyBar values")
        sessions = tuple(bar.session for bar in bars)
        if sessions != tuple(sorted(sessions)) or len(set(sessions)) != len(sessions):
            raise SimulationViolation("bars must be sorted and unique by session")
        indexed[permanent_id] = bars
    return indexed


def _full_forward_window(
    candidate: Candidate,
    bars: tuple[DailyBar, ...],
    hold: int,
    evaluation_end_exclusive: dt.date,
) -> bool:
    entry_index = next((index for index, bar in enumerate(bars) if bar.session == candidate.entry_session), None)
    return (
        entry_index is not None
        and entry_index + hold <= len(bars)
        and bars[entry_index + hold - 1].session < evaluation_end_exclusive
    )


def _candidate_rejection_reason(
    candidate: Candidate,
    protocol: DiscoveryProtocol,
    strategy: StrategyRevision,
) -> str | None:
    try:
        strategy.validate_against(protocol)
    except ContractViolation:
        return "strategy_binding"
    if candidate.strategy_revision_identity != strategy.identity:
        return "strategy_binding"
    if candidate.input_manifest_identity != protocol.input_manifest_identity:
        return "input_manifest_binding"
    if not (
        protocol.evaluation_start
        <= candidate.signal_session
        < protocol.evaluation_end_exclusive
    ) or candidate.entry_session >= protocol.evaluation_end_exclusive:
        return "outside_evaluation_range"
    if any(as_of > protocol.data_cutoff for as_of in candidate.facts_as_of.values()):
        return "source_fact_after_cutoff"
    if candidate.signal_close < protocol.charter.minimum_price:
        return "minimum_signal_price"
    if (
        candidate.average_dollar_volume
        < protocol.charter.minimum_average_dollar_volume
    ):
        return "minimum_average_dollar_volume"
    if (
        candidate.sessions_before_earnings is not None
        and candidate.sessions_before_earnings
        <= protocol.charter.earnings_blackout_sessions
    ):
        return "earnings_blackout"
    return None


def _open_state(
    positions: Mapping[str, _Position],
    session_bars: Mapping[str, DailyBar],
    cash: Decimal,
) -> tuple[Decimal, Decimal]:
    position_value = sum(
        (position.quantity * session_bars[permanent_id].open for permanent_id, position in positions.items()),
        D0,
    )
    return cash + position_value, position_value


def _fill_quantity(
    *,
    entry_price: Decimal,
    stop_price: Decimal,
    opening_equity: Decimal,
    opening_deployed: Decimal,
    cash: Decimal,
    protocol: DiscoveryProtocol,
) -> Decimal:
    charter = protocol.charter
    risk_shares = (opening_equity * charter.risk_fraction / (entry_price - stop_price)).to_integral_value(rounding=ROUND_DOWN)
    notional_shares = (opening_equity * charter.maximum_notional_fraction / entry_price).to_integral_value(rounding=ROUND_DOWN)
    deploy_available = opening_equity * charter.maximum_deployed_fraction - opening_deployed
    deploy_shares = (max(D0, deploy_available) / entry_price).to_integral_value(rounding=ROUND_DOWN)
    cash_shares = (cash / entry_price).to_integral_value(rounding=ROUND_DOWN)
    return min(risk_shares, notional_shares, deploy_shares, cash_shares)


def _order_rejection(
    *,
    candidate: Candidate,
    session: dt.date,
    reason: str,
    orders: list[OrderRecord],
    events: list[EventRecord],
) -> None:
    order = OrderRecord(
        candidate_identity=candidate.identity,
        permanent_id=candidate.permanent_id,
        session=session,
        status="rejected",
        reason=reason,
        quantity=None,
        fill_price=None,
        cost=ZERO_COST,
    )
    orders.append(order)
    _event(
        events,
        session=session,
        event_type="order_rejected",
        candidate_identity=candidate.identity,
        order_identity=order.identity,
        trade_identity=None,
        payload={"reason": reason, "cost": ZERO_COST},
    )


def _close_position(
    *,
    position: _Position,
    session: dt.date,
    exit_price: Decimal,
    exit_reason: Literal["gap_stop", "gap_target", "stop", "target", "time"],
    trades: list[TradeRecord],
    events: list[EventRecord],
) -> TradeRecord:
    trade = TradeRecord(
        order_identity=position.order.identity,
        candidate_identity=position.candidate.identity,
        permanent_id=position.candidate.permanent_id,
        symbol=position.candidate.symbol,
        entry_session=position.order.session,
        entry_price=position.entry_price,
        quantity=position.quantity,
        exit_session=session,
        exit_price=exit_price,
        exit_reason=exit_reason,
        gross_pnl=(exit_price - position.entry_price) * position.quantity,
        cost=ZERO_COST,
    )
    trades.append(trade)
    _event(
        events,
        session=session,
        event_type="trade_closed",
        candidate_identity=position.candidate.identity,
        order_identity=position.order.identity,
        trade_identity=trade.identity,
        payload={"exit_reason": exit_reason, "exit_price": exit_price, "gross_pnl": trade.gross_pnl, "cost": ZERO_COST},
    )
    return trade


def simulate(
    *,
    protocol: DiscoveryProtocol,
    strategy: StrategyRevision,
    geometry_program: GeometryProgram,
    candidates: Sequence[Candidate],
    geometries_by_candidate_identity: Mapping[str, EntryGeometry],
    bars_by_permanent_id: Mapping[str, Sequence[DailyBar]],
    priority_direction: Literal["ascending", "descending"],
) -> SimulationResult:
    """Simulate all candidate outcomes in the charter's required execution order.

    Geometry is supplied explicitly by an already-declared generic program;
    neither a stop nor target formula is selected by this execution layer.
    """
    strategy.validate_against(protocol)
    geometry_program.validate_against(strategy)
    if priority_direction not in ("ascending", "descending"):
        raise SimulationViolation("priority_direction must be ascending or descending")
    bars = _indexed_bars(bars_by_permanent_id)
    triggered = tuple(candidates)
    if not all(isinstance(candidate, Candidate) for candidate in triggered):
        raise SimulationViolation("candidates must contain Candidate values")
    identities = [candidate.identity for candidate in triggered]
    if len(identities) != len(set(identities)):
        raise SimulationViolation("candidates must be unique by immutable identity")
    if not isinstance(geometries_by_candidate_identity, Mapping):
        raise SimulationViolation("geometries_by_candidate_identity must be a mapping")

    orders: list[OrderRecord] = []
    trades: list[TradeRecord] = []
    equity: list[EquityRecord] = []
    events: list[EventRecord] = []
    cash = protocol.charter.starting_capital
    positions: dict[str, _Position] = {}
    geometry_by_identity = dict(geometries_by_candidate_identity)

    pre_rejection_reasons: dict[str, str] = {}
    for candidate in triggered:
        reason = _candidate_rejection_reason(candidate, protocol, strategy)
        geometry = geometry_by_identity.get(candidate.identity)
        if reason is None and not isinstance(geometry, EntryGeometry):
            reason = "missing_geometry"
        if reason is None:
            assert isinstance(geometry, EntryGeometry)
            try:
                geometry.validate_against(candidate, protocol.charter)
            except ContractViolation:
                reason = "invalid_geometry"
        candidate_bars = bars.get(candidate.permanent_id)
        if reason is None and (
            candidate_bars is None
            or not _full_forward_window(
                candidate,
                candidate_bars,
                protocol.charter.maximum_hold_sessions,
                protocol.evaluation_end_exclusive,
            )
        ):
            reason = "insufficient_forward_bars"
        if reason is not None:
            pre_rejection_reasons[candidate.identity] = reason

    sessions = sorted(
        {
            bar.session
            for per_security in bars.values()
            for bar in per_security
            if protocol.evaluation_start
            <= bar.session
            < protocol.evaluation_end_exclusive
        }
        | {candidate.entry_session for candidate in triggered}
    )
    by_session: dict[dt.date, list[Candidate]] = {}
    for candidate in triggered:
        by_session.setdefault(candidate.entry_session, []).append(candidate)
    bar_by_session = {
        permanent_id: {bar.session: bar for bar in per_security}
        for permanent_id, per_security in bars.items()
    }

    for session in sessions:
        active_bars = {
            permanent_id: by_session_bars[session]
            for permanent_id, by_session_bars in bar_by_session.items()
            if session in by_session_bars
        }
        if any(permanent_id not in active_bars for permanent_id in positions):
            raise SimulationViolation("a carried position is missing a daily bar")

        # 1. Carried-position opening gap exits.  Their proceeds are opening cash.
        for permanent_id, position in tuple(positions.items()):
            bar = active_bars[permanent_id]
            exit_reason: Literal["gap_stop", "gap_target"] | None = None
            if bar.open <= position.geometry.initial_stop_price:
                exit_reason = "gap_stop"
            elif bar.open >= position.geometry.target_price:
                exit_reason = "gap_target"
            if exit_reason is not None:
                trade = _close_position(position=position, session=session, exit_price=bar.open, exit_reason=exit_reason, trades=trades, events=events)
                cash += trade.exit_price * trade.quantity
                del positions[permanent_id]

        # 2. Same-session opening fills use static post-gap opening equity and deployment.
        opening_equity, opening_deployed = _open_state(positions, active_bars, cash)
        opening_fill_notional = D0
        day_candidates = by_session.get(session, [])
        day_candidates = sorted(
            day_candidates,
            key=lambda candidate: (
                -candidate.priority_value if priority_direction == "descending" else candidate.priority_value,
                candidate.tie_break,
            ),
        )
        for candidate in day_candidates:
            pre_rejection = pre_rejection_reasons.get(candidate.identity)
            if pre_rejection is not None:
                _order_rejection(
                    candidate=candidate,
                    session=session,
                    reason=pre_rejection,
                    orders=orders,
                    events=events,
                )
                continue
            bar = active_bars.get(candidate.permanent_id)
            if bar is None:
                _order_rejection(candidate=candidate, session=session, reason="missing_entry_bar", orders=orders, events=events)
                continue
            if candidate.permanent_id in positions:
                _order_rejection(candidate=candidate, session=session, reason="duplicate_security", orders=orders, events=events)
                continue
            geometry = geometry_by_identity[candidate.identity]
            assert isinstance(geometry, EntryGeometry)
            if geometry.entry_price != bar.open:
                _order_rejection(candidate=candidate, session=session, reason="opening_geometry_invalid", orders=orders, events=events)
                continue
            if bar.open < protocol.charter.minimum_price:
                _order_rejection(candidate=candidate, session=session, reason="minimum_price", orders=orders, events=events)
                continue
            risk_per_share = bar.open - geometry.initial_stop_price
            reward_per_share = geometry.target_price - bar.open
            if risk_per_share <= D0 or reward_per_share <= D0 or risk_per_share / bar.open > protocol.charter.maximum_stop_fraction or reward_per_share / risk_per_share <= protocol.charter.minimum_planned_reward_risk:
                _order_rejection(candidate=candidate, session=session, reason="opening_geometry_invalid", orders=orders, events=events)
                continue
            if len(positions) >= protocol.charter.maximum_positions:
                _order_rejection(candidate=candidate, session=session, reason="maximum_positions", orders=orders, events=events)
                continue
            quantity = _fill_quantity(
                entry_price=bar.open,
                stop_price=geometry.initial_stop_price,
                opening_equity=opening_equity,
                opening_deployed=opening_deployed + opening_fill_notional,
                cash=cash,
                protocol=protocol,
            )
            if quantity < D1:
                _order_rejection(candidate=candidate, session=session, reason="portfolio_cap", orders=orders, events=events)
                continue
            order = OrderRecord(candidate_identity=candidate.identity, permanent_id=candidate.permanent_id, session=session, status="filled", reason="filled", quantity=quantity, fill_price=bar.open, cost=ZERO_COST)
            orders.append(order)
            _event(events, session=session, event_type="order_filled", candidate_identity=candidate.identity, order_identity=order.identity, trade_identity=None, payload={"quantity": quantity, "fill_price": bar.open, "cost": ZERO_COST})
            cash -= quantity * bar.open
            opening_fill_notional += quantity * bar.open
            index = next(index for index, value in enumerate(bars[candidate.permanent_id]) if value.session == session)
            positions[candidate.permanent_id] = _Position(candidate=candidate, order=order, geometry=geometry, quantity=quantity, entry_price=bar.open, entry_index=index)

        # 3. Intraday exits, with stop collision precedence, then 21st-session close.
        for permanent_id, position in tuple(positions.items()):
            bar = active_bars[permanent_id]
            exit_reason: Literal["stop", "target", "time"] | None = None
            exit_price: Decimal | None = None
            if bar.low <= position.geometry.initial_stop_price:
                exit_reason, exit_price = "stop", position.geometry.initial_stop_price
            elif bar.high >= position.geometry.target_price:
                exit_reason, exit_price = "target", position.geometry.target_price
            elif session == bars[permanent_id][position.entry_index + protocol.charter.maximum_hold_sessions - 1].session:
                exit_reason, exit_price = "time", bar.close
            if exit_reason is not None:
                assert exit_price is not None
                trade = _close_position(position=position, session=session, exit_price=exit_price, exit_reason=exit_reason, trades=trades, events=events)
                cash += trade.exit_price * trade.quantity
                del positions[permanent_id]

        # 4. Close mark.  Intraday proceeds were deliberately unavailable for entries above.
        close_value = sum(
            (position.quantity * active_bars[permanent_id].close for permanent_id, position in positions.items()),
            D0,
        )
        total_equity = cash + close_value
        record = EquityRecord(session=session, cash=cash, position_value=close_value, equity=total_equity, deployed_fraction=D0 if total_equity == D0 else close_value / total_equity)
        equity.append(record)
        _event(events, session=session, event_type="equity_mark", candidate_identity=None, order_identity=None, trade_identity=None, payload={"cash": cash, "position_value": close_value, "equity": total_equity, "deployed_fraction": record.deployed_fraction})

    result = SimulationResult(orders=tuple(orders), trades=tuple(trades), equity=tuple(equity), events=tuple(events))
    if len(result.orders) != len(triggered):
        raise SimulationViolation("every triggered candidate must have one terminal order")
    if positions:
        raise SimulationViolation("full-forward validation left an unclosed position")
    result.assert_reconciled(protocol.charter.starting_capital)
    return result
