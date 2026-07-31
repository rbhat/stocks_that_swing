"""Fail-closed initialization for unchanged forward paper cohorts."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from sts import calendar
from sts.swing_ranking.artifacts import (
    ArtifactPackage,
    ArtifactViolation,
    ArtifactWriteResult,
    write_artifact_package,
)
from sts.swing_ranking.candidates import (
    ScheduledEarnings,
    generate_forward_candidates,
)
from sts.swing_ranking.config import CohortSelection, ConfiguredStudy
from sts.swing_ranking.contracts import (
    REQUIRED_SOURCE_KINDS,
    Candidate,
    EntryGeometry,
    SignalFact,
)
from sts.swing_ranking.geometry import resolve_geometry
from sts.swing_ranking.identity import (
    canonical_bytes,
    canonical_json,
    identity_hash,
    sha256_hex,
)
from sts.swing_ranking.simulator import (
    ZERO_COST,
    DailyBar,
    ExecutionCheckpoint,
    OpenPosition,
    OrderRecord,
    advance_session,
    initial_checkpoint,
)


def _json(value: object) -> bytes:
    return canonical_bytes(value) + b"\n"


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ArtifactViolation(f"{path} must contain a JSON object")
    return value


@dataclass(frozen=True)
class ForwardAdvanceResult:
    session: dt.date
    session_identity: str
    created: bool
    candidate_count: int
    filled_order_count: int
    closed_trade_count: int


def _date(value: object, label: str) -> dt.date:
    if not isinstance(value, str):
        raise ArtifactViolation(f"{label} must be an ISO date")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ArtifactViolation(f"{label} must be an ISO date") from exc


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ArtifactViolation(f"{label} must be a canonical decimal string")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ArtifactViolation(f"{label} must be finite")
    return result


def _candidate(value: object) -> Candidate:
    if not isinstance(value, dict):
        raise ArtifactViolation("stored candidate must be an object")
    signal_facts = value.get("signal_facts")
    facts_as_of = value.get("facts_as_of")
    if not isinstance(signal_facts, dict) or not isinstance(facts_as_of, dict):
        raise ArtifactViolation("stored candidate facts are malformed")
    earnings = value.get("scheduled_earnings_session")
    return Candidate(
        strategy_revision_identity=str(value["strategy_revision_identity"]),
        input_manifest_identity=str(value["input_manifest_identity"]),
        permanent_id=str(value["permanent_id"]),
        symbol=str(value["symbol"]),
        signal_session=_date(value["signal_session"], "candidate signal_session"),
        entry_session=_date(value["entry_session"], "candidate entry_session"),
        signal_close=_decimal(value["signal_close"], "candidate signal_close"),
        average_dollar_volume=_decimal(
            value["average_dollar_volume"],
            "candidate average_dollar_volume",
        ),
        scheduled_earnings_session=(
            None if earnings is None else _date(earnings, "candidate earnings session")
        ),
        sessions_before_earnings=value.get("sessions_before_earnings"),
        facts_as_of=MappingProxyType(
            {kind: _date(day, f"candidate facts_as_of {kind}") for kind, day in facts_as_of.items()}
        ),
        signal_facts=MappingProxyType(
            {
                name: SignalFact(
                    value=_decimal(fact["value"], f"candidate fact {name}"),
                    available_session=_date(
                        fact["available_session"],
                        f"candidate fact {name} available_session",
                    ),
                )
                for name, fact in signal_facts.items()
            }
        ),
        priority_value=_decimal(value["priority_value"], "candidate priority_value"),
    )


def _geometry(value: object) -> EntryGeometry:
    if not isinstance(value, dict):
        raise ArtifactViolation("stored geometry must be an object")
    return EntryGeometry(
        candidate_identity=str(value["candidate_identity"]),
        entry_price=_decimal(value["entry_price"], "geometry entry_price"),
        initial_stop_price=_decimal(
            value["initial_stop_price"],
            "geometry initial_stop_price",
        ),
        target_price=_decimal(value["target_price"], "geometry target_price"),
        planned_hold_sessions=int(value["planned_hold_sessions"]),
    )


def _order(value: object) -> OrderRecord:
    if not isinstance(value, dict):
        raise ArtifactViolation("stored order must be an object")
    quantity = value.get("quantity")
    fill_price = value.get("fill_price")
    return OrderRecord(
        candidate_identity=str(value["candidate_identity"]),
        permanent_id=str(value["permanent_id"]),
        session=_date(value["session"], "order session"),
        status=str(value["status"]),
        reason=str(value["reason"]),
        quantity=None if quantity is None else _decimal(quantity, "order quantity"),
        fill_price=None if fill_price is None else _decimal(fill_price, "order fill_price"),
        cost=_decimal(value["cost"], "order cost"),
    )


def _checkpoint(book: dict[str, object], starting_capital: Decimal) -> ExecutionCheckpoint:
    raw = book.get("execution")
    if raw is None:
        return initial_checkpoint(starting_capital)
    if not isinstance(raw, dict) or not isinstance(raw.get("positions"), list):
        raise ArtifactViolation("forward execution checkpoint is malformed")
    positions: list[OpenPosition] = []
    for item in raw["positions"]:
        if not isinstance(item, dict):
            raise ArtifactViolation("stored open position must be an object")
        positions.append(
            OpenPosition(
                candidate=_candidate(item["candidate"]),
                order=_order(item["order"]),
                geometry=_geometry(item["geometry"]),
                quantity=_decimal(item["quantity"], "position quantity"),
                entry_price=_decimal(item["entry_price"], "position entry_price"),
                sessions_held=int(item["sessions_held"]),
            )
        )
    return ExecutionCheckpoint(
        cash=_decimal(raw["cash"], "checkpoint cash"),
        positions=tuple(positions),
        event_sequence=int(raw["event_sequence"]),
        previous_event_hash=raw.get("previous_event_hash"),
    )


def _pending(book: dict[str, object]) -> tuple[Candidate, ...]:
    values = book.get("pending_candidates", [])
    if not isinstance(values, list):
        raise ArtifactViolation("pending_candidates must be a list")
    return tuple(_candidate(value) for value in values)


def _jsonl(rows: list[object]) -> bytes:
    return b"".join(canonical_json(row).encode("utf-8") + b"\n" for row in rows)


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ArtifactViolation(f"required forward input is missing: {path}")
    return sha256_hex(path.read_bytes())


def initialize_forward_run(
    *,
    study: ConfiguredStudy,
    selection: CohortSelection,
    seal_path: Path,
    upcoming_earnings_snapshot: Path,
    authorization_date: dt.date,
    output: Path,
) -> ArtifactWriteResult:
    """Create an empty, no-backfill forward book only after a valid OOS seal."""
    seal = _read_json(Path(seal_path) / "seal.json")
    if (
        seal.get("status") != "sealed"
        or seal.get("selection_identity") != selection.identity
        or seal.get("forward_eligibility") != "unconditional_pre_oos"
        or set(seal.get("forward_eligible_cohorts", ())) != {"VF9", "MC5"}
    ):
        raise ArtifactViolation("forward initialization requires the approved OOS seal")
    if study.evidence_window != "oos":
        raise ArtifactViolation("forward selection must remain bound to the OOS-selected study")
    if not isinstance(authorization_date, dt.date) or isinstance(authorization_date, dt.datetime):
        raise ArtifactViolation("authorization_date must be a date")
    future_sessions = calendar.sessions_between(
        authorization_date + dt.timedelta(days=1),
        authorization_date + dt.timedelta(days=14),
    )
    if len(future_sessions) == 0:
        raise ArtifactViolation("cannot resolve the first post-authorization XNYS session")
    first_session = future_sessions[0].date()
    snapshot_path = Path(upcoming_earnings_snapshot)
    if not snapshot_path.is_file():
        raise ArtifactViolation("upcoming earnings snapshot is missing")
    snapshot_sha256 = sha256_hex(snapshot_path.read_bytes())
    member_by_id = {
        member.strategy_revision_identity: member for member in selection.members
    }
    strategy_by_id = {
        configured.strategy.identity: configured for configured in study.strategies
    }
    if set(member_by_id) != set(strategy_by_id):
        raise ArtifactViolation("forward strategies do not match the sealed selection")
    books = [
        {
            "strategy_revision_identity": identity,
            "strategy_name": member_by_id[identity].strategy_name,
            "memberships": member_by_id[identity].memberships,
            "starting_equity": "100000",
            "current_equity": "100000",
            "closed_trades": 0,
            "open_positions": 0,
            "status": "active",
        }
        for identity in sorted(strategy_by_id)
    ]
    charter = {
        "schema_version": "swing-ranking-v1.forward-charter.v1",
        "run_id": selection.forward_run_id,
        "authorization_date": authorization_date,
        "first_eligible_signal_session": first_session,
        "no_backfill": True,
        "paper_only": True,
        "selection_identity": selection.identity,
        "oos_seal_identity": seal["seal_identity"],
        "study_bundle_sha256": selection.study_bundle_sha256,
        "protocol_identity": study.protocol.identity,
        "charter_identity": study.protocol.charter.identity,
        "input_manifest_identity": study.protocol.input_manifest_identity,
        "strategy_revision_identities": tuple(sorted(strategy_by_id)),
        "cohorts": selection.cohorts,
        "forward_eligible_cohorts": selection.forward_eligible_cohorts,
        "aggregation": {
            "strategy_book_starting_capital": "100000",
            "VF9_raw_starting_capital": "900000",
            "MC5_raw_starting_capital": "500000",
            "FO4_raw_starting_capital": "400000",
            "normalized_index_start": "100",
            "member_weighting": "equal_weight_after_normalizing_each_strategy_book",
        },
        "evidence_thresholds": {
            "interim_closed_trades_per_revision": selection.interim_trade_counts,
            "decision_ready_closed_trades_per_revision": selection.minimum_decision_trades_per_revision,
        },
        "metrics": (
            "ending_equity",
            "gross_profit",
            "gross_return",
            "maximum_drawdown_dollars",
            "maximum_drawdown",
            "profit_drawdown",
            "closed_trades",
            "exposure",
            "turnover",
            "break_even_proportional_cost",
            "breadth",
            "concentration",
            "leave_one_out",
            "overlap",
        ),
        "upcoming_earnings_snapshot": {
            "path": snapshot_path.as_posix(),
            "sha256": snapshot_sha256,
        },
    }
    state = {
        "schema_version": "swing-ranking-v1.forward-state.v1",
        "run_id": selection.forward_run_id,
        "status": "active_awaiting_first_session",
        "as_of": authorization_date,
        "next_eligible_signal_session": first_session,
        "last_processed_session": None,
        "no_backfill": True,
        "books": books,
        "cohort_status": {
            "VF9": "descriptive_no_closed_trades",
            "MC5": "descriptive_no_closed_trades",
            "FO4": "diagnostic_no_closed_trades",
        },
        "decision_readiness": "not_ready",
    }
    files: dict[str, bytes] = {
        "charter.json": _json(charter),
        "state.json": _json(state),
        "candidates.jsonl": b"",
        "orders.jsonl": b"",
        "trades.jsonl": b"",
        "equity.jsonl": b"",
        "events.jsonl": b"",
        "README.md": (
            "# Swing Ranking V1 Forward 01\n\n"
            f"Active without backfill. First eligible XNYS signal session: `{first_session}`. "
            "VF9 and MC5 retain the sealed membership and execution charter. "
            "Ten- and twenty-trade views are descriptive; every revision requires 30 closed "
            "trades for decision-ready evidence.\n"
        ).encode(),
    }
    forward_identity = identity_hash(
        "swing-ranking-v1/forward-initialization/v1",
        {"charter": charter, "state": state},
    )
    content_hashes = {name: sha256_hex(content) for name, content in files.items()}
    files["manifest.json"] = _json(
        {
            "schema_version": "swing-ranking-v1.forward-manifest.v1",
            "forward_identity": forward_identity,
            "run_id": selection.forward_run_id,
            "status": state["status"],
            "first_eligible_signal_session": first_session,
            "selection_identity": selection.identity,
            "oos_seal_identity": seal["seal_identity"],
            "strategy_count": len(books),
            "content_hashes": content_hashes,
        }
    )
    return write_artifact_package(
        Path(output), ArtifactPackage(forward_identity, files, synthetic=False)
    )


def _load_forward_inputs(
    *,
    session: dt.date,
    parquet_root: Path,
    security_master: Path,
    earnings_snapshot: Path,
) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, DailyBar],
    dict[str, str],
    dict[str, tuple[ScheduledEarnings, ...]],
    dict[str, object],
]:
    master = _read_json(security_master)
    securities = master.get("securities")
    if not isinstance(securities, list) or len(securities) != 250:
        raise ArtifactViolation("forward security master must contain the frozen 250 securities")
    symbol_by_id: dict[str, str] = {}
    for row in securities:
        if not isinstance(row, dict):
            raise ArtifactViolation("forward security master row is malformed")
        permanent_id = str(row.get("permanent_id", ""))
        symbol = str(row.get("symbol", "")).upper()
        if not permanent_id or not symbol or permanent_id in symbol_by_id:
            raise ArtifactViolation("forward security master identities are incomplete")
        symbol_by_id[permanent_id] = symbol
    if len(set(symbol_by_id.values())) != len(symbol_by_id):
        raise ArtifactViolation("forward security master contains duplicate symbols")

    frames: dict[str, pd.DataFrame] = {}
    bars: dict[str, DailyBar] = {}
    parquet_hashes: dict[str, str] = {}
    for permanent_id, symbol in sorted(symbol_by_id.items()):
        path = parquet_root / f"{symbol}.parquet"
        parquet_hashes[permanent_id] = _sha256_file(path)
        frame = pd.read_parquet(path)
        if (
            tuple(frame.columns) != ("open", "high", "low", "close", "volume")
            or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is not None
            or not frame.index.is_monotonic_increasing
            or not frame.index.is_unique
            or frame.empty
            or frame.isna().any().any()
            or frame.index[-1].date() != session
            or any(value.date() > session for value in frame.index)
        ):
            raise ArtifactViolation(
                f"forward parquet for {symbol} is not a complete through-{session} frame"
            )
        row = frame.loc[pd.Timestamp(session)]
        frames[permanent_id] = frame
        bars[permanent_id] = DailyBar(
            session=session,
            open=_decimal(str(row["open"]), f"{symbol} open"),
            high=_decimal(str(row["high"]), f"{symbol} high"),
            low=_decimal(str(row["low"]), f"{symbol} low"),
            close=_decimal(str(row["close"]), f"{symbol} close"),
        )

    snapshot = _read_json(earnings_snapshot)
    source = snapshot.get("source")
    coverage = snapshot.get("coverage")
    events = snapshot.get("events")
    if (
        snapshot.get("schema_version") != "swing-ranking-v1.earnings-calendar.v1"
        or not isinstance(source, dict)
        or source.get("snapshot_date") != session.isoformat()
        or not isinstance(coverage, list)
        or not isinstance(events, list)
    ):
        raise ArtifactViolation("forward earnings input must be the exact daily snapshot")
    covered: set[str] = set()
    for row in coverage:
        if not isinstance(row, dict):
            raise ArtifactViolation("forward earnings coverage row is malformed")
        permanent_id = str(row.get("permanent_id", ""))
        start = _date(row.get("coverage_start"), "earnings coverage_start")
        end = _date(row.get("coverage_end_exclusive"), "earnings coverage_end_exclusive")
        if permanent_id in symbol_by_id and start <= session < end:
            covered.add(permanent_id)
    if covered != set(symbol_by_id):
        raise ArtifactViolation("forward earnings snapshot does not cover all 250 securities")
    earnings: defaultdict[str, list[ScheduledEarnings]] = defaultdict(list)
    for row in events:
        if not isinstance(row, dict):
            raise ArtifactViolation("forward earnings event row is malformed")
        permanent_id = str(row.get("permanent_id", ""))
        if permanent_id not in symbol_by_id:
            raise ArtifactViolation("forward earnings event references an unknown security")
        known = _date(row.get("known_session"), "earnings known_session")
        if known > session:
            continue
        superseded_value = row.get("superseded_session")
        earnings[permanent_id].append(
            ScheduledEarnings(
                earnings_session=_date(
                    row.get("earnings_session"),
                    "earnings earnings_session",
                ),
                known_session=known,
                superseded_session=(
                    None
                    if superseded_value is None
                    else _date(superseded_value, "earnings superseded_session")
                ),
            )
        )
    source_record = {
        "schema_version": "swing-ranking-v1.forward-source.v1",
        "session": session,
        "security_master": {
            "path": security_master.as_posix(),
            "sha256": _sha256_file(security_master),
        },
        "earnings_snapshot": {
            "path": earnings_snapshot.as_posix(),
            "sha256": _sha256_file(earnings_snapshot),
        },
        "parquet_root": parquet_root.as_posix(),
        "parquet_sha256_by_permanent_id": parquet_hashes,
    }
    return (
        frames,
        bars,
        symbol_by_id,
        {identity: tuple(values) for identity, values in earnings.items()},
        source_record,
    )


def _projection_row(
    strategy_identity: str,
    record: object,
    identity: str,
    **extra: object,
) -> dict[str, object]:
    return {
        "strategy_revision_identity": strategy_identity,
        "identity": identity,
        "record": record,
        **extra,
    }


def advance_forward_run(
    *,
    study: ConfiguredStudy,
    selection: CohortSelection,
    output: Path,
    session: dt.date,
    parquet_root: Path,
    security_master: Path,
    earnings_snapshot: Path,
    enforce_wall_clock: bool = True,
) -> ForwardAdvanceResult:
    """Advance the sealed run by its one exact next completed XNYS session."""
    output = Path(output)
    if isinstance(session, dt.datetime) or not isinstance(session, dt.date):
        raise ArtifactViolation("forward session must be a date")
    if not calendar.is_session(session):
        raise ArtifactViolation("forward session must be an XNYS session")
    if enforce_wall_clock and session != calendar.last_completed_session():
        raise ArtifactViolation("forward session must equal the latest completed XNYS session")
    charter = _read_json(output / "charter.json")
    state = _read_json(output / "state.json")
    manifest = _read_json(output / "manifest.json")
    if (
        charter.get("selection_identity") != selection.identity
        or manifest.get("selection_identity") != selection.identity
        or charter.get("run_id") != selection.forward_run_id
        or state.get("run_id") != selection.forward_run_id
        or charter.get("no_backfill") is not True
        or state.get("no_backfill") is not True
    ):
        raise ArtifactViolation("forward run no longer matches the sealed selection")
    last_value = state.get("last_processed_session")
    if last_value == session.isoformat():
        session_manifest = _read_json(output / "sessions" / session.isoformat() / "manifest.json")
        counts = session_manifest.get("record_counts", {})
        if not isinstance(counts, dict):
            raise ArtifactViolation("forward session record counts are malformed")
        return ForwardAdvanceResult(
            session=session,
            session_identity=str(session_manifest["session_identity"]),
            created=False,
            candidate_count=int(counts.get("candidates", 0)),
            filled_order_count=int(counts.get("filled_orders", 0)),
            closed_trade_count=int(counts.get("trades", 0)),
        )
    first_session = _date(
        charter.get("first_eligible_signal_session"),
        "first eligible signal session",
    )
    if last_value is None:
        expected = first_session
    else:
        last = _date(last_value, "last_processed_session")
        expected = calendar.nyse().next_session(pd.Timestamp(last)).date()
    if session != expected:
        raise ArtifactViolation(
            f"no-backfill forward advance expected {expected}, received {session}"
        )
    if study.evidence_window != "oos":
        raise ArtifactViolation("forward study must retain the sealed OOS selection binding")
    selected_ids = {configured.strategy.identity for configured in study.strategies}
    if selected_ids != set(charter.get("strategy_revision_identities", [])):
        raise ArtifactViolation("forward strategy identities no longer match the charter")

    frames, bars, symbol_by_id, earnings_by_id, source_record = _load_forward_inputs(
        session=session,
        parquet_root=Path(parquet_root),
        security_master=Path(security_master),
        earnings_snapshot=Path(earnings_snapshot),
    )
    snapshot_date = _date(
        _read_json(Path(earnings_snapshot))["source"]["snapshot_date"],
        "earnings snapshot_date",
    )
    facts_as_of = {fact.kind: fact.as_of for fact in study.protocol.source_facts}
    facts_as_of["daily_market_data"] = session
    facts_as_of["earnings_calendar"] = snapshot_date
    facts_as_of["exchange_calendar"] = session
    if set(facts_as_of) != set(REQUIRED_SOURCE_KINDS):
        raise ArtifactViolation("forward facts do not cover every required source kind")

    raw_books = state.get("books")
    if not isinstance(raw_books, list) or len(raw_books) != 9:
        raise ArtifactViolation("forward state must contain nine strategy books")
    books_by_id = {
        str(book.get("strategy_revision_identity")): dict(book)
        for book in raw_books
        if isinstance(book, dict)
    }
    if set(books_by_id) != selected_ids:
        raise ArtifactViolation("forward state books do not match the sealed revisions")

    candidate_rows: list[object] = []
    order_rows: list[object] = []
    trade_rows: list[object] = []
    equity_rows: list[object] = []
    event_rows: list[object] = []
    next_books: list[dict[str, object]] = []
    for configured in sorted(study.strategies, key=lambda item: item.strategy.identity):
        strategy_id = configured.strategy.identity
        book = books_by_id[strategy_id]
        pending = _pending(book)
        if any(candidate.entry_session != session for candidate in pending):
            raise ArtifactViolation("stored forward candidate does not enter on the next session")
        geometries: dict[str, EntryGeometry] = {}
        for candidate in pending:
            bar = bars.get(candidate.permanent_id)
            if bar is None:
                continue
            try:
                geometries[candidate.identity] = resolve_geometry(
                    candidate=candidate,
                    entry_price=bar.open,
                    spec=configured.geometry_spec,
                    charter=study.protocol.charter,
                )
            except ValueError:
                continue
        advanced = advance_session(
            protocol=study.protocol,
            strategy=configured.strategy,
            geometry_program=configured.geometry_program,
            session=session,
            candidates=pending,
            geometries_by_candidate_identity=geometries,
            bars_by_permanent_id=bars,
            priority_direction=configured.program.priority_direction,
            checkpoint=_checkpoint(book, study.protocol.charter.starting_capital),
            prospective=True,
        )
        generated: list[Candidate] = []
        for permanent_id in sorted(frames):
            generated.extend(
                generate_forward_candidates(
                    frame=frames[permanent_id],
                    permanent_id=permanent_id,
                    symbol=symbol_by_id[permanent_id],
                    protocol=study.protocol,
                    strategy=configured.strategy,
                    program=configured.program,
                    geometry_fact_names=configured.geometry_spec.signal_fact_names,
                    facts_as_of=facts_as_of,
                    scheduled_earnings=earnings_by_id.get(permanent_id, ()),
                    signal_session=session,
                )
            )
        new_pending = tuple(sorted(generated, key=lambda item: item.identity))
        candidate_rows.extend(
            _projection_row(strategy_id, candidate, candidate.identity)
            for candidate in new_pending
        )
        order_rows.extend(
            _projection_row(
                strategy_id,
                order,
                order.identity,
                geometry=geometries.get(order.candidate_identity),
            )
            for order in advanced.orders
        )
        trade_rows.extend(
            _projection_row(strategy_id, trade, trade.identity)
            for trade in advanced.trades
        )
        equity_rows.append(
            _projection_row(strategy_id, advanced.equity, advanced.equity.identity)
        )
        event_rows.extend(
            _projection_row(strategy_id, event, event.event_hash)
            for event in advanced.events
        )
        prior_closed = int(book.get("closed_trades", 0))
        prior_turnover = _decimal(book.get("turnover", "0"), "book turnover")
        session_turnover = sum(
            (
                order.quantity * order.fill_price
                for order in advanced.orders
                if order.status == "filled"
                and order.quantity is not None
                and order.fill_price is not None
            ),
            ZERO_COST,
        ) + sum(
            (trade.quantity * trade.exit_price for trade in advanced.trades),
            ZERO_COST,
        )
        prior_peak = _decimal(
            book.get("peak_equity", book.get("starting_equity", "100000")),
            "book peak_equity",
        )
        peak = max(prior_peak, advanced.equity.equity)
        drawdown = Decimal(0) if peak == 0 else Decimal(1) - advanced.equity.equity / peak
        maximum_drawdown = max(
            _decimal(book.get("maximum_drawdown", "0"), "book maximum_drawdown"),
            drawdown,
        )
        maximum_drawdown_dollars = max(
            _decimal(
                book.get("maximum_drawdown_dollars", "0"),
                "book maximum_drawdown_dollars",
            ),
            peak - advanced.equity.equity,
        )
        next_book = {
            **book,
            "current_equity": advanced.equity.equity,
            "closed_trades": prior_closed + len(advanced.trades),
            "open_positions": len(advanced.checkpoint.positions),
            "candidate_count": int(book.get("candidate_count", 0)) + len(new_pending),
            "order_count": int(book.get("order_count", 0)) + len(advanced.orders),
            "turnover": prior_turnover + session_turnover,
            "session_count": int(book.get("session_count", 0)) + 1,
            "exposure_sessions": int(book.get("exposure_sessions", 0))
            + int(advanced.equity.position_value > 0),
            "peak_equity": peak,
            "maximum_drawdown": maximum_drawdown,
            "maximum_drawdown_dollars": maximum_drawdown_dollars,
            "pending_candidates": new_pending,
            "execution": advanced.checkpoint,
        }
        next_books.append(next_book)

    closed_by_id = {
        str(book["strategy_revision_identity"]): int(book["closed_trades"])
        for book in next_books
    }
    minimum_closed = min(closed_by_id.values())
    decision_ready = minimum_closed >= selection.minimum_decision_trades_per_revision
    cohort_status: dict[str, str] = {}
    for name, identities in selection.cohorts.items():
        cohort_minimum = min(closed_by_id[identity] for identity in identities)
        if cohort_minimum >= 30:
            label = "decision_ready" if name != "FO4" else "30"
        elif cohort_minimum >= 20:
            label = "descriptive_20"
        elif cohort_minimum >= 10:
            label = "descriptive_10"
        else:
            label = "pre_10"
        cohort_status[name] = label if name != "FO4" else f"diagnostic_{label}"
    next_session = calendar.nyse().next_session(pd.Timestamp(session)).date()
    next_state = {
        **state,
        "schema_version": "swing-ranking-v1.forward-state.v2",
        "status": "active",
        "as_of": session,
        "last_processed_session": session,
        "next_eligible_signal_session": next_session,
        "books": next_books,
        "cohort_status": cohort_status,
        "decision_readiness": "ready" if decision_ready else "not_ready",
    }

    ledger_rows = {
        "candidates.jsonl": candidate_rows,
        "orders.jsonl": order_rows,
        "trades.jsonl": trade_rows,
        "equity.jsonl": equity_rows,
        "events.jsonl": event_rows,
    }
    prior_state = (output / "state.json").read_bytes()
    prior_hashes = {
        name: _sha256_file(output / name) for name in ledger_rows
    }
    additions = {name: _jsonl(rows) for name, rows in ledger_rows.items()}
    final_contents = {
        name: (output / name).read_bytes() + additions[name]
        for name in ledger_rows
    }
    next_state_bytes = _json(next_state)
    logical = {
        "schema_version": "swing-ranking-v1.forward-session.v1",
        "forward_identity": manifest.get("forward_identity"),
        "session": session,
        "prior_state_sha256": sha256_hex(prior_state),
        "source": source_record,
        "records": ledger_rows,
        "next_state": next_state,
    }
    session_identity = identity_hash(
        "swing-ranking-v1/forward-session/v1",
        logical,
    )
    record_counts = {
        "candidates": len(candidate_rows),
        "orders": len(order_rows),
        "filled_orders": sum(
            row["record"].status == "filled" for row in order_rows
        ),
        "trades": len(trade_rows),
        "equity": len(equity_rows),
        "events": len(event_rows),
    }
    session_files = {
        "source.json": _json(source_record),
        **{f"records/{name}": content for name, content in additions.items()},
        "next_state.json": next_state_bytes,
    }
    session_files["manifest.json"] = _json(
        {
            "schema_version": "swing-ranking-v1.forward-session.v1",
            "session_identity": session_identity,
            "session": session,
            "prior_state_sha256": sha256_hex(prior_state),
            "next_state_sha256": sha256_hex(next_state_bytes),
            "prior_ledger_sha256": prior_hashes,
            "final_ledger_sha256": {
                name: sha256_hex(content) for name, content in final_contents.items()
            },
            "record_counts": record_counts,
            "content_hashes": {
                name: sha256_hex(content) for name, content in session_files.items()
            },
        }
    )
    session_path = output / "sessions" / session.isoformat()
    write_artifact_package(
        session_path,
        ArtifactPackage(session_identity, session_files, synthetic=False),
    )

    for name, content in final_contents.items():
        current = (output / name).read_bytes()
        if sha256_hex(current) == sha256_hex(content):
            continue
        if sha256_hex(current) != prior_hashes[name]:
            raise ArtifactViolation(f"forward projection {name} diverged before commit")
        _atomic_replace(output / name, content)
    current_state = (output / "state.json").read_bytes()
    if sha256_hex(current_state) != sha256_hex(next_state_bytes):
        if sha256_hex(current_state) != sha256_hex(prior_state):
            raise ArtifactViolation("forward state diverged before commit")
        _atomic_replace(output / "state.json", next_state_bytes)

    session_artifacts = dict(manifest.get("session_artifacts", {}))
    session_artifacts[session.isoformat()] = session_identity
    content_hashes = {
        name: _sha256_file(output / name)
        for name in (
            "README.md",
            "charter.json",
            "state.json",
            "candidates.jsonl",
            "orders.jsonl",
            "trades.jsonl",
            "equity.jsonl",
            "events.jsonl",
        )
    }
    next_manifest = {
        **manifest,
        "status": "active",
        "last_processed_session": session,
        "next_eligible_signal_session": next_session,
        "content_hashes": content_hashes,
        "session_artifacts": session_artifacts,
        "record_counts": {
            "candidates": sum(1 for _ in (output / "candidates.jsonl").open()),
            "orders": sum(1 for _ in (output / "orders.jsonl").open()),
            "trades": sum(1 for _ in (output / "trades.jsonl").open()),
            "equity": sum(1 for _ in (output / "equity.jsonl").open()),
            "events": sum(1 for _ in (output / "events.jsonl").open()),
        },
    }
    _atomic_replace(output / "manifest.json", _json(next_manifest))
    return ForwardAdvanceResult(
        session=session,
        session_identity=session_identity,
        created=True,
        candidate_count=record_counts["candidates"],
        filled_order_count=record_counts["filled_orders"],
        closed_trade_count=record_counts["trades"],
    )


__all__ = [
    "ForwardAdvanceResult",
    "advance_forward_run",
    "initialize_forward_run",
]
