"""Shared domain types. Nothing is a black box: every signal carries the
config that fired it and the values that triggered it; every trade record
carries the full lifecycle per CLAUDE.md."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class SignalEvent:
    """A pick. `trigger_values` must include what fired (e.g. range_width_pct,
    volume_ratio) and the swing points (`swing_low`, `swing_high`) the risk
    layer needs for Fibonacci targets."""

    symbol: str
    date: dt.date            # session the signal fired on (fill is next bar)
    config_name: str
    params: dict             # exact config parameters at fire time
    trigger_values: dict     # observed values that satisfied the rules
    direction: str = "long"  # long only for now


# Required keys for every trades.jsonl row (CLAUDE.md hard rule).
TRADE_FIELDS = [
    "id", "timestamp", "mode", "source", "config", "symbol", "direction",
    "entry_date", "exit_date",
    "entry", "size", "stop", "targets", "exit", "exit_reason",
    "pnl_usd", "pnl_pct", "r_multiple", "holding_days",
]


def new_trade_record(**kwargs) -> dict:
    """Build a trades.jsonl row; fills id/timestamp, validates required keys.
    `exit`/`exit_reason`/pnl fields may be None while a position is open —
    closed trades append a fresh, complete record (append-only, never edit).

    `timestamp` is when the record was WRITTEN (wall clock) — unchanged
    semantics, not a trading date. `entry_date`/`exit_date` (ISO YYYY-MM-DD
    strings) are the actual SESSIONS of fill and final exit; `exit_date` is
    None while a position is open, same convention as `exit`. Any consumer
    doing time-based analysis (charts, --date filtering) must use
    entry_date/exit_date, never timestamp.

    Optional identity fields `book` ("primary"|"catalyst"; "swing" reserved)
    and `program` (e.g. "rework") are stamped by ForwardEngine on every
    forward record since Phase 10a; both are absent on backtest records and
    on legacy forward rows (append-only log, never backfilled). Readers must
    tolerate absence: an absent `program` means legacy, and for legacy
    forward rows `book` derives from the id's "{book}:" prefix via
    stm.forward.book_label."""
    rec = {
        "id": str(uuid.uuid4()),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        **kwargs,
    }
    missing = [k for k in TRADE_FIELDS if k not in rec]
    if missing:
        raise ValueError(f"trade record missing fields: {missing}")
    return rec
