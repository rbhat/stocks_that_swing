"""Deterministic cash-, slot-, and capacity-constrained ML-v2 simulator.

The state machine is deliberately pure.  Its durable ledger can be persisted
by a later authorized adapter, but this Gate-1 module neither reads nor writes
files.  Start-of-session equity is the preceding session's closing marked
equity, before current-session opening exits.  Pending orders are transient
opening commands and never reserve resources overnight.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, localcontext
from types import MappingProxyType
from typing import Any

from sts.ml_v2.contracts import (
    D0,
    D1,
    LOCKED_FOLD_IDS,
    Bar,
    Candidate,
    ContractViolation,
    PointInTimeManifest,
    SessionFrame,
    SetupContract,
    validate_synthetic_inputs,
)
from sts.ml_v2.controls import rank_candidates
from sts.ml_v2.identity import (
    candidate_identity,
    canonical_bytes,
    event_hash,
    identity_hash,
)
from sts.ml_v2.metrics import PortfolioMetrics, calculate_metrics

_BPS_DENOMINATOR = Decimal(10000)
_RECONCILIATION_TOLERANCE = Decimal("0.000000000000000001")


@dataclass(frozen=True)
class LedgerEvent:
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    previous_hash: str | None
    event_hash: str


@dataclass(frozen=True)
class Rejection:
    setup_id: str
    fold_id: str
    permanent_id: str
    signal_session: dt.date
    entry_session: dt.date
    candidate_id: str
    reason: str


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    setup_id: str
    fold_id: str
    permanent_id: str
    entry_symbol: str
    exit_symbol: str
    signal_session: dt.date
    entry_session: dt.date
    exit_session: dt.date
    slot: int
    shares: int
    next_open: Decimal
    entry_fill_2x: Decimal
    entry_fill_base: Decimal
    entry_commission_2x: Decimal
    entry_commission_base: Decimal
    stop_initial: Decimal
    target_initial: Decimal
    exit_reference: Decimal
    exit_fill_2x: Decimal
    exit_fill_base: Decimal
    exit_commission_2x: Decimal
    exit_commission_base: Decimal
    cash_distributions: Decimal
    entry_notional_2x: Decimal
    entry_notional_base: Decimal
    exit_notional_2x: Decimal
    exit_notional_base: Decimal
    gross_pnl: Decimal
    net_pnl_2x: Decimal
    net_pnl_base: Decimal
    initial_risk_dollars: Decimal
    net_r_2x: Decimal
    holding_sessions: int
    exit_reason: str


@dataclass(frozen=True)
class DailyMark:
    session: dt.date
    cash: Decimal
    receivables: Decimal
    gross_open_market_value: Decimal
    equity: Decimal
    open_positions: int


@dataclass(frozen=True)
class SimulationResult:
    book_id: str
    fold_id: str
    setup_identity: str
    source_identity: str
    ledger: tuple[LedgerEvent, ...]
    trades: tuple[ClosedTrade, ...]
    rejections: tuple[Rejection, ...]
    daily_marks: tuple[DailyMark, ...]
    metrics: PortfolioMetrics
    final_identity: str

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            {
                "book_id": self.book_id,
                "fold_id": self.fold_id,
                "setup_identity": self.setup_identity,
                "source_identity": self.source_identity,
                "ledger": self.ledger,
                "trades": self.trades,
                "rejections": self.rejections,
                "daily_marks": self.daily_marks,
                "metrics": self.metrics,
                "final_identity": self.final_identity,
            }
        )


class SimulatedCrash(RuntimeError):
    """A synthetic crash immediately after the last returned durable event."""

    def __init__(self, events: tuple[LedgerEvent, ...]):
        super().__init__(f"synthetic crash after {len(events)} durable events")
        self.events = events


@dataclass
class _Position:
    setup_id: str
    fold_id: str
    permanent_id: str
    entry_symbol: str
    signal_session: dt.date
    entry_session: dt.date
    entry_index: int
    slot: int
    shares: int
    next_open: Decimal
    entry_fill_2x: Decimal
    entry_fill_base: Decimal
    entry_commission_2x: Decimal
    entry_commission_base: Decimal
    stop: Decimal
    target: Decimal
    slippage_rate_2x: Decimal
    initial_risk_dollars: Decimal
    cash_distributions: Decimal = D0
    last_mark: Decimal = D0

    @property
    def reserved_notional(self) -> Decimal:
        return self.shares * self.entry_fill_2x


@dataclass
class _Receivable:
    permanent_id: str
    amount: Decimal
    payable_session: dt.date


@dataclass
class _State:
    cash: Decimal
    positions: dict[str, _Position] = field(default_factory=dict)
    receivables: list[_Receivable] = field(default_factory=list)
    trades: list[ClosedTrade] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    daily_marks: list[DailyMark] = field(default_factory=list)
    ledger: list[LedgerEvent] = field(default_factory=list)
    exited_today: set[str] = field(default_factory=set)


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _commission(notional: Decimal, bps: Decimal, fixed: Decimal) -> Decimal:
    return notional * bps / _BPS_DENOMINATOR + fixed


def _slippage_rate(
    *,
    shares: int,
    opening_print: Decimal,
    atr14: Decimal,
    signal_close: Decimal,
    mdv20: Decimal,
) -> Decimal:
    order_notional = Decimal(shares) * opening_print
    with localcontext() as context:
        context.prec = 50
        impact = (order_notional / mdv20).sqrt()
        raw = (
            Decimal("0.10") * (atr14 / signal_close)
            + Decimal("0.0020") * impact
        )
    return min(Decimal("0.0100"), max(Decimal("0.0010"), raw))


def _bar_map(frame: SessionFrame) -> dict[str, Bar]:
    return {bar.permanent_id: bar for bar in frame.bars}


def _receivables_value(state: _State) -> Decimal:
    return sum((item.amount for item in state.receivables), D0)


def _gross_reserved(state: _State) -> Decimal:
    return sum(
        (position.reserved_notional for position in state.positions.values()),
        D0,
    )


def _risk_reserved(state: _State) -> Decimal:
    return sum(
        (
            position.initial_risk_dollars
            for position in state.positions.values()
        ),
        D0,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _entry_cost(
    shares: int,
    opening_print: Decimal,
    rate: Decimal,
    *,
    base: bool,
) -> tuple[Decimal, Decimal, Decimal]:
    applied_rate = rate / Decimal(2) if base else rate
    fill = opening_print * (D1 + applied_rate)
    notional = Decimal(shares) * fill
    commission = _commission(
        notional,
        Decimal(5) if base else Decimal(10),
        D1 if base else Decimal(2),
    )
    return fill, notional, commission


def _sized_entry(
    *,
    setup: SetupContract,
    state: _State,
    candidate: Candidate,
    opening_print: Decimal,
    start_equity: Decimal,
) -> tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal] | str:
    ratio = candidate.signal_to_entry_split_ratio
    atr14 = candidate.atr14 / ratio
    signal_close = candidate.signal_close / ratio
    mdv20 = candidate.mdv20
    stop_risk = setup.stop_atr_multiple * atr14
    caps = {
        "risk_capacity": _floor(
            setup.risk_fraction * start_equity / stop_risk
        ),
        "position_capacity": _floor(
            setup.position_fraction * start_equity / opening_print
        ),
        "liquidity_capacity": _floor(
            setup.participation_fraction * mdv20 / opening_print
        ),
        "cash_limit": _floor(state.cash / opening_print),
        "gross_limit": _floor(
            max(D0, setup.gross_fraction * start_equity - _gross_reserved(state))
            / opening_print
        ),
    }
    initial_shares = min(caps.values())
    if initial_shares < 1:
        for reason in (
            "cash_limit",
            "gross_limit",
            "liquidity_capacity",
            "position_capacity",
            "risk_capacity",
        ):
            if caps[reason] < 1:
                return reason
        return "zero_shares"
    rate = _slippage_rate(
        shares=initial_shares,
        opening_print=opening_print,
        atr14=atr14,
        signal_close=signal_close,
        mdv20=mdv20,
    )

    def fits(shares: int) -> bool:
        _fill, notional, commission = _entry_cost(
            shares,
            opening_print,
            rate,
            base=False,
        )
        total = notional + commission
        return (
            total <= state.cash
            and total <= setup.position_fraction * start_equity
            and total <= setup.participation_fraction * mdv20
            and _gross_reserved(state) + total
            <= setup.gross_fraction * start_equity
        )

    low, high = 0, initial_shares
    while low < high:
        midpoint = (low + high + 1) // 2
        if fits(midpoint):
            low = midpoint
        else:
            high = midpoint - 1
    shares = low
    if shares < 1:
        if state.cash < opening_print:
            return "cash_limit"
        return "capacity_after_friction"
    entry_fill, _entry_notional, entry_commission = _entry_cost(
        shares,
        opening_print,
        rate,
        base=False,
    )
    base_fill, _base_notional, base_commission = _entry_cost(
        shares,
        opening_print,
        rate,
        base=True,
    )
    return (
        shares,
        rate,
        entry_fill,
        entry_commission,
        base_fill,
        base_commission,
    )


def simulate(
    *,
    setup: SetupContract,
    manifest: PointInTimeManifest,
    sessions: tuple[SessionFrame, ...],
    candidates: tuple[Candidate, ...],
    book_id: str = "real",
    fold_id: str | None = None,
    resume_events: tuple[LedgerEvent, ...] = (),
    crash_after_events: int | None = None,
) -> SimulationResult:
    """Run one synthetic setup/control/fold book through the locked state machine."""
    validate_synthetic_inputs(
        setup=setup,
        manifest=manifest,
        sessions=sessions,
        candidates=candidates,
    )
    if not isinstance(book_id, str) or not book_id.strip():
        raise ContractViolation("book_id must be a non-empty string")
    book_id = book_id.strip()
    candidate_fold_ids = {candidate.fold_id for candidate in candidates}
    if len(candidate_fold_ids) > 1:
        raise ContractViolation("one simulator book cannot mix validation folds")
    inferred_fold = (
        next(iter(candidate_fold_ids)) if candidate_fold_ids else None
    )
    resolved_fold = fold_id or inferred_fold
    if resolved_fold not in LOCKED_FOLD_IDS:
        raise ContractViolation(
            f"fold_id must be one of {LOCKED_FOLD_IDS}; "
            "empty candidate books must supply it"
        )
    if inferred_fold is not None and inferred_fold != resolved_fold:
        raise ContractViolation("requested fold_id differs from candidate fold")
    if crash_after_events is not None and crash_after_events < 0:
        raise ContractViolation("crash_after_events cannot be negative")
    if crash_after_events == 0:
        raise SimulatedCrash(())

    state = _State(cash=setup.starting_cash)

    def assert_reconciled() -> None:
        if state.cash < -_RECONCILIATION_TOLERANCE:
            raise ContractViolation("cash became negative")
        slots = [position.slot for position in state.positions.values()]
        if len(slots) != len(set(slots)) or any(
            slot < 0 or slot >= setup.max_positions for slot in slots
        ):
            raise ContractViolation("position slots do not reconcile")
        if any(
            permanent_id != position.permanent_id or position.shares < 1
            for permanent_id, position in state.positions.items()
        ):
            raise ContractViolation("open-position identity or shares do not reconcile")
        if any(item.amount < 0 for item in state.receivables):
            raise ContractViolation("receivables cannot be negative")
        marked_positions = sum(
            (
                Decimal(position.shares) * position.last_mark
                for position in state.positions.values()
            ),
            D0,
        )
        equity = state.cash + _receivables_value(state) + marked_positions
        reconstructed = (
            state.cash + _receivables_value(state) + marked_positions
        )
        if abs(equity - reconstructed) > _RECONCILIATION_TOLERANCE:
            raise ContractViolation("cash and marked positions do not reconcile")

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        assert_reconciled()
        receivables_after = _receivables_value(state)
        marked_positions_after = sum(
            (
                Decimal(position.shares) * position.last_mark
                for position in state.positions.values()
            ),
            D0,
        )
        payload = {
            "study_id": "ml-v2",
            "book_id": book_id,
            "setup_id": setup.setup_id,
            "fold_id": resolved_fold,
            "source_identity": manifest.identity,
            "cash_after": state.cash,
            "receivables_after": receivables_after,
            "marked_positions_after": marked_positions_after,
            "state_equity_after": (
                state.cash + receivables_after + marked_positions_after
            ),
            "gross_reserved_after": _gross_reserved(state),
            "risk_reserved_after": _risk_reserved(state),
            "occupied_slots_after": sorted(
                position.slot for position in state.positions.values()
            ),
            **payload,
        }
        sequence = len(state.ledger)
        previous = state.ledger[-1].event_hash if state.ledger else None
        frozen_payload = _freeze(payload)
        digest = event_hash(
            sequence=sequence,
            event_type=event_type,
            payload=frozen_payload,
            previous_hash=previous,
        )
        event = LedgerEvent(
            sequence,
            event_type,
            frozen_payload,
            previous,
            digest,
        )
        if sequence < len(resume_events) and event != resume_events[sequence]:
            raise ContractViolation(
                f"resume ledger diverges at durable event {sequence}"
            )
        state.ledger.append(event)
        if crash_after_events == len(state.ledger):
            raise SimulatedCrash(tuple(state.ledger))

    def reject(candidate: Candidate, reason: str) -> None:
        candidate_id = candidate_identity(candidate)
        rejection = Rejection(
            setup_id=candidate.setup_id,
            fold_id=candidate.fold_id,
            permanent_id=candidate.permanent_id,
            signal_session=candidate.signal_session,
            entry_session=candidate.entry_session,
            candidate_id=candidate_id,
            reason=reason,
        )
        state.rejections.append(rejection)
        emit(
            "order_rejected",
            {
                "setup_id": candidate.setup_id,
                "fold_id": candidate.fold_id,
                "permanent_id": candidate.permanent_id,
                "signal_session": candidate.signal_session,
                "entry_session": candidate.entry_session,
                "candidate_id": candidate_id,
                "source_identity": candidate.source_identity,
                "reason": reason,
            },
        )

    def close_position(
        permanent_id: str,
        *,
        session: dt.date,
        session_index: int,
        exit_symbol: str,
        reference: Decimal,
        reason: str,
        apply_friction: bool = True,
    ) -> None:
        position = state.positions.pop(permanent_id)
        if apply_friction:
            exit_fill = reference * (D1 - position.slippage_rate_2x)
            base_fill = reference * (
                D1 - position.slippage_rate_2x / Decimal(2)
            )
            exit_notional = Decimal(position.shares) * exit_fill
            base_exit_notional = Decimal(position.shares) * base_fill
            exit_commission = _commission(
                exit_notional, Decimal(10), Decimal(2)
            )
            base_exit_commission = _commission(
                base_exit_notional, Decimal(5), D1
            )
        else:
            exit_fill = reference
            base_fill = reference
            exit_notional = Decimal(position.shares) * reference
            base_exit_notional = exit_notional
            exit_commission = D0
            base_exit_commission = D0
        state.cash += exit_notional - exit_commission
        entry_notional = Decimal(position.shares) * position.entry_fill_2x
        base_entry_notional = Decimal(position.shares) * position.entry_fill_base
        net_pnl = (
            exit_notional
            - exit_commission
            - entry_notional
            - position.entry_commission_2x
            + position.cash_distributions
        )
        net_pnl_base = (
            base_exit_notional
            - base_exit_commission
            - base_entry_notional
            - position.entry_commission_base
            + position.cash_distributions
        )
        initial_risk = position.initial_risk_dollars
        trade_id = identity_hash(
            "ml-v2/trade/v1",
            {
                "setup_id": position.setup_id,
                "fold_id": position.fold_id,
                "permanent_id": permanent_id,
                "entry_session": position.entry_session,
                "exit_session": session,
                "shares": position.shares,
            },
        )
        trade = ClosedTrade(
            trade_id=trade_id,
            setup_id=position.setup_id,
            fold_id=position.fold_id,
            permanent_id=permanent_id,
            entry_symbol=position.entry_symbol,
            exit_symbol=exit_symbol,
            signal_session=position.signal_session,
            entry_session=position.entry_session,
            exit_session=session,
            slot=position.slot,
            shares=position.shares,
            next_open=position.next_open,
            entry_fill_2x=position.entry_fill_2x,
            entry_fill_base=position.entry_fill_base,
            entry_commission_2x=position.entry_commission_2x,
            entry_commission_base=position.entry_commission_base,
            stop_initial=position.stop,
            target_initial=position.target,
            exit_reference=reference,
            exit_fill_2x=exit_fill,
            exit_fill_base=base_fill,
            exit_commission_2x=exit_commission,
            exit_commission_base=base_exit_commission,
            cash_distributions=position.cash_distributions,
            entry_notional_2x=entry_notional,
            entry_notional_base=base_entry_notional,
            exit_notional_2x=exit_notional,
            exit_notional_base=base_exit_notional,
            gross_pnl=Decimal(position.shares) * (reference - position.next_open),
            net_pnl_2x=net_pnl,
            net_pnl_base=net_pnl_base,
            initial_risk_dollars=initial_risk,
            net_r_2x=net_pnl / initial_risk,
            holding_sessions=session_index - position.entry_index + 1,
            exit_reason=reason,
        )
        state.trades.append(trade)
        state.exited_today.add(permanent_id)
        emit(
            "position_closed",
            {
                "setup_id": position.setup_id,
                "fold_id": position.fold_id,
                "permanent_id": permanent_id,
                "session": session,
                "trade_id": trade_id,
                "reason": reason,
                "slot": position.slot,
                "reference": reference,
                "exit_fill_2x": exit_fill,
                "cash_after": state.cash,
            },
        )

    candidates_by_entry: dict[dt.date, list[Candidate]] = {}
    for candidate in candidates:
        candidates_by_entry.setdefault(candidate.entry_session, []).append(candidate)

    for session_index, frame in enumerate(sessions):
        session = frame.session
        bars = _bar_map(frame)
        state.exited_today.clear()
        start_equity = (
            state.daily_marks[-1].equity
            if state.daily_marks
            else setup.starting_cash
        )

        payable = [
            item for item in state.receivables if item.payable_session == session
        ]
        for item in payable:
            state.cash += item.amount
            state.receivables.remove(item)
            emit(
                "distribution_paid",
                {
                    "permanent_id": item.permanent_id,
                    "session": session,
                    "amount": item.amount,
                    "cash_after": state.cash,
                },
            )

        for split in frame.splits:
            position = state.positions.get(split.permanent_id)
            if position is None:
                continue
            adjusted_shares = Decimal(position.shares) * split.ratio
            if adjusted_shares != adjusted_shares.to_integral_value():
                raise ContractViolation(
                    "synthetic split creates unsupported fractional shares"
                )
            position.shares = int(adjusted_shares)
            position.stop /= split.ratio
            position.target /= split.ratio
            position.entry_fill_2x /= split.ratio
            position.entry_fill_base /= split.ratio
            position.next_open /= split.ratio
            position.last_mark /= split.ratio
            emit(
                "split_applied",
                {
                    "permanent_id": split.permanent_id,
                    "session": session,
                    "ratio": split.ratio,
                    "shares_after": position.shares,
                },
            )

        for distribution in frame.distributions:
            if distribution.payable_session < session:
                raise ContractViolation(
                    "distribution payable session precedes its ex-date"
                )
            position = state.positions.get(distribution.permanent_id)
            if position is None:
                continue
            amount = Decimal(position.shares) * distribution.amount_per_share
            position.cash_distributions += amount
            state.receivables.append(
                _Receivable(
                    permanent_id=distribution.permanent_id,
                    amount=amount,
                    payable_session=distribution.payable_session,
                )
            )
            emit(
                "distribution_accrued",
                {
                    "permanent_id": distribution.permanent_id,
                    "session": session,
                    "payable_session": distribution.payable_session,
                    "amount": amount,
                },
            )
            if distribution.payable_session == session:
                state.cash += amount
                state.receivables.pop()
                emit(
                    "distribution_paid",
                    {
                        "permanent_id": distribution.permanent_id,
                        "session": session,
                        "amount": amount,
                        "cash_after": state.cash,
                    },
                )

        delisted_ids = {item.permanent_id for item in frame.delistings}
        for delisting in frame.delistings:
            if delisting.permanent_id not in state.positions:
                continue
            position = state.positions[delisting.permanent_id]
            close_position(
                delisting.permanent_id,
                session=session,
                session_index=session_index,
                exit_symbol=position.entry_symbol,
                reference=delisting.recovery_per_share or D0,
                reason=(
                    "delisting_recovery"
                    if delisting.recovery_per_share is not None
                    else "delisting_zero_recovery"
                ),
                apply_friction=False,
            )

        for permanent_id in tuple(state.positions):
            bar = bars.get(permanent_id)
            if bar is None:
                raise ContractViolation(
                    f"missing open-position bar for {permanent_id} on {session}"
                )
            if bar.documented_halt:
                continue
            assert bar.open is not None
            position = state.positions[permanent_id]
            if bar.open <= position.stop:
                close_position(
                    permanent_id,
                    session=session,
                    session_index=session_index,
                    exit_symbol=bar.symbol,
                    reference=bar.open,
                    reason="stop_gap",
                )
            elif bar.open >= position.target:
                close_position(
                    permanent_id,
                    session=session,
                    session_index=session_index,
                    exit_symbol=bar.symbol,
                    reference=position.target,
                    reason="target_gap",
                )

        accepted = 0
        opening_candidates = rank_candidates(
            tuple(candidates_by_entry.get(session, ()))
        )
        for candidate in opening_candidates:
            if accepted >= setup.max_daily_entries:
                reject(candidate, "daily_entry_quota")
                continue
            if candidate.permanent_id in delisted_ids:
                reject(candidate, "delisted")
                continue
            if candidate.stale:
                reject(candidate, "stale_input")
                continue
            if candidate.permanent_id in state.positions:
                reject(candidate, "existing_position")
                continue
            if candidate.permanent_id in state.exited_today:
                reject(candidate, "same_session_reentry")
                continue
            if len(state.positions) >= setup.max_positions:
                reject(candidate, "slot_limit")
                continue
            bar = bars.get(candidate.permanent_id)
            if bar is None:
                reject(candidate, "missing_open")
                continue
            if (
                bar.documented_halt
                or not bar.executable_open
                or bar.open is None
                or bar.open <= 0
            ):
                reject(candidate, "halt_no_open")
                continue
            ratio = candidate.signal_to_entry_split_ratio
            adjusted_signal_close = candidate.signal_close / ratio
            adjusted_atr = candidate.atr14 / ratio
            gap = abs(bar.open / adjusted_signal_close - D1)
            gap_limit = min(
                Decimal("0.03"),
                Decimal("0.75") * adjusted_atr / adjusted_signal_close,
            )
            if gap > gap_limit:
                reject(candidate, "excessive_gap")
                continue
            sized = _sized_entry(
                setup=setup,
                state=state,
                candidate=candidate,
                opening_print=bar.open,
                start_equity=start_equity,
            )
            if isinstance(sized, str):
                reject(candidate, sized)
                continue
            (
                shares,
                rate,
                entry_fill,
                entry_commission,
                base_fill,
                base_commission,
            ) = sized
            stop = entry_fill - setup.stop_atr_multiple * adjusted_atr
            target = entry_fill + setup.target_atr_multiple * adjusted_atr
            if (
                stop <= 0
                or stop >= entry_fill
                or target <= entry_fill
                or (entry_fill - stop) / entry_fill
                > setup.max_stop_fraction
            ):
                reject(candidate, "invalid_geometry")
                continue
            entry_notional = Decimal(shares) * entry_fill
            total_cost = entry_notional + entry_commission
            if total_cost > state.cash:
                reject(candidate, "cash_limit")
                continue
            state.cash -= total_cost
            used_slots = {item.slot for item in state.positions.values()}
            slot = next(
                index
                for index in range(setup.max_positions)
                if index not in used_slots
            )
            position = _Position(
                setup_id=candidate.setup_id,
                fold_id=candidate.fold_id,
                permanent_id=candidate.permanent_id,
                entry_symbol=bar.symbol,
                signal_session=candidate.signal_session,
                entry_session=session,
                entry_index=session_index,
                slot=slot,
                shares=shares,
                next_open=bar.open,
                entry_fill_2x=entry_fill,
                entry_fill_base=base_fill,
                entry_commission_2x=entry_commission,
                entry_commission_base=base_commission,
                stop=stop,
                target=target,
                slippage_rate_2x=rate,
                initial_risk_dollars=(
                    Decimal(shares) * (entry_fill - stop)
                ),
                last_mark=bar.open,
            )
            state.positions[candidate.permanent_id] = position
            accepted += 1
            emit(
                "entry_filled",
                {
                    "setup_id": candidate.setup_id,
                    "fold_id": candidate.fold_id,
                    "permanent_id": candidate.permanent_id,
                    "signal_session": candidate.signal_session,
                    "entry_session": session,
                    "candidate_id": candidate_identity(candidate),
                    "source_identity": candidate.source_identity,
                    "symbol": bar.symbol,
                    "slot": slot,
                    "shares": shares,
                    "opening_print": bar.open,
                    "entry_fill_2x": entry_fill,
                    "entry_commission_2x": entry_commission,
                    "initial_risk_dollars": position.initial_risk_dollars,
                    "stop": stop,
                    "target": target,
                    "cash_after": state.cash,
                },
            )

        for permanent_id in tuple(state.positions):
            bar = bars.get(permanent_id)
            if bar is None:
                raise ContractViolation(
                    f"missing open-position bar for {permanent_id} on {session}"
                )
            if bar.documented_halt:
                continue
            assert bar.high is not None and bar.low is not None
            position = state.positions[permanent_id]
            if bar.low <= position.stop:
                close_position(
                    permanent_id,
                    session=session,
                    session_index=session_index,
                    exit_symbol=bar.symbol,
                    reference=position.stop,
                    reason="stop",
                )
            elif bar.high >= position.target:
                close_position(
                    permanent_id,
                    session=session,
                    session_index=session_index,
                    exit_symbol=bar.symbol,
                    reference=position.target,
                    reason="target",
                )

        for permanent_id in tuple(state.positions):
            position = state.positions[permanent_id]
            holding_sessions = session_index - position.entry_index + 1
            if holding_sessions < setup.max_hold_sessions:
                continue
            bar = bars.get(permanent_id)
            if bar is None or bar.close is None:
                raise ContractViolation("time exit requires a valid close")
            close_position(
                permanent_id,
                session=session,
                session_index=session_index,
                exit_symbol=bar.symbol,
                reference=bar.close,
                reason="time",
            )

        if session_index == len(sessions) - 1:
            for permanent_id in tuple(state.positions):
                bar = bars.get(permanent_id)
                if bar is None or bar.close is None:
                    raise ContractViolation(
                        "terminal liquidation requires a valid final close"
                    )
                close_position(
                    permanent_id,
                    session=session,
                    session_index=session_index,
                    exit_symbol=bar.symbol,
                    reference=bar.close,
                    reason="terminal_liquidation",
                )

        gross_market_value = D0
        for permanent_id, position in state.positions.items():
            bar = bars.get(permanent_id)
            if bar is None:
                raise ContractViolation(
                    f"missing mark for {permanent_id} on {session}"
                )
            if bar.close is None:
                position.last_mark = D0
            else:
                position.last_mark = bar.close
            gross_market_value += Decimal(position.shares) * position.last_mark
        receivables = _receivables_value(state)
        equity = state.cash + receivables + gross_market_value
        reconciled = state.cash + _receivables_value(state) + sum(
            (
                Decimal(position.shares) * position.last_mark
                for position in state.positions.values()
            ),
            D0,
        )
        if abs(equity - reconciled) > _RECONCILIATION_TOLERANCE:
            raise ContractViolation("cash and marked positions do not reconcile")
        mark = DailyMark(
            session=session,
            cash=state.cash,
            receivables=receivables,
            gross_open_market_value=gross_market_value,
            equity=equity,
            open_positions=len(state.positions),
        )
        state.daily_marks.append(mark)
        emit(
            "daily_mark",
            {
                "session": session,
                "cash": state.cash,
                "receivables": receivables,
                "gross_open_market_value": gross_market_value,
                "equity": equity,
                "open_positions": len(state.positions),
            },
        )

    if len(resume_events) > len(state.ledger):
        raise ContractViolation("resume ledger contains events beyond this simulation")
    metrics = calculate_metrics(
        state.trades,
        state.daily_marks,
        state.rejections,
        starting_equity=setup.starting_cash,
        exchange_sessions=len(sessions),
    )
    root_payload = {
        "book_id": book_id,
        "fold_id": resolved_fold,
        "setup_identity": setup.identity,
        "source_identity": manifest.identity,
        "ledger_tail": state.ledger[-1].event_hash if state.ledger else None,
        "trades": state.trades,
        "rejections": state.rejections,
        "daily_marks": state.daily_marks,
        "metrics": metrics,
    }
    final_identity = identity_hash("ml-v2/simulation-result/v1", root_payload)
    return SimulationResult(
        book_id=book_id,
        fold_id=resolved_fold,
        setup_identity=setup.identity,
        source_identity=manifest.identity,
        ledger=tuple(state.ledger),
        trades=tuple(state.trades),
        rejections=tuple(state.rejections),
        daily_marks=tuple(state.daily_marks),
        metrics=metrics,
        final_identity=final_identity,
    )
