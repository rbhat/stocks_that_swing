"""Per-family append-only ledger, built on top of the Journal primitive.

Two family journals (`ledger/h1.jsonl`, `ledger/h2.jsonl`) hold position
lifecycle rows (open -> closed, one row per status transition, latest `seq`
wins). A book-level equity snapshot journal (`ledger/equity.jsonl`) and a
signal journal (`ledger/signals.jsonl`) round out the ledger.

Dates/timestamps are serialized as ISO strings by the underlying Journal's
`json.dumps(..., default=str)`; readers get strings back and callers parse
them if they need `date`/`datetime` objects.

`Ledger` owns stamping `schema_version`, `seq`, and `updated_at` on every
row passed to `append_row` — `Journal.append` itself stamps nothing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from sts.forward.journal import Journal

SCHEMA_VERSION = 1
BOOKS = ("shared", "h1solo")
SOURCES = {"shared": "local-shared", "h1solo": "local-h1solo"}

# Fields the caller must supply on every row passed to append_row.
# `schema_version`, `seq`, `updated_at` are bookkeeping fields Ledger stamps
# itself and are therefore excluded here (see append_row).
REQUIRED_FIELDS = frozenset(
    {
        "entry_id",
        "family",
        "source",
        "ticker",
        "signal_date",
        "timestamp",
        "qty",
        "entry_ref",
        "entry_fill",
        "entry_price_range",
        "stop_initial",
        "sl",
        "tp1",
        "tp2",
        "status",
        "usd_deployed",
        "exit_price",
        "exit_timestamp",
        "exit_reason",
        "fees_total",
        "pnl_usd",
        "r_net",
    }
)

# Fields that must be non-None regardless of open/closed status.
_ALWAYS_NON_NULL = frozenset(
    {"entry_id", "family", "source", "ticker", "signal_date", "status", "stop_initial"}
)

# Additionally required non-None when status == "closed".
_CLOSED_NON_NULL = frozenset({"exit_price", "exit_reason", "exit_timestamp"})

_VALID_FAMILIES = frozenset({"h1", "h2"})
_VALID_STATUSES = frozenset({"open", "closed"})


def entry_id(book: str, family: str, symbol: str, signal_date: dt.date) -> str:
    """Deterministic id: `book:family:symbol:signal_date` — job re-runs
    cannot double-book the same position."""
    return f"{book}:{family}:{symbol}:{signal_date.isoformat()}"


@dataclass
class LedgerPaths:
    root: Path = field(default_factory=lambda: Path("ledger"))

    @property
    def h1(self) -> Path:
        return self.root / "h1.jsonl"

    @property
    def h2(self) -> Path:
        return self.root / "h2.jsonl"

    @property
    def equity(self) -> Path:
        return self.root / "equity.jsonl"

    @property
    def signals(self) -> Path:
        return self.root / "signals.jsonl"


def _validate_row(row: dict) -> None:
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise ValueError(f"ledger row missing required fields: {sorted(missing)}")

    non_null_missing = [f for f in _ALWAYS_NON_NULL if row.get(f) is None]
    if non_null_missing:
        raise ValueError(
            f"ledger row has None for required fields: {sorted(non_null_missing)}"
        )

    if row["family"] not in _VALID_FAMILIES:
        raise ValueError(f"invalid family: {row['family']!r}")
    if row["status"] not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {row['status']!r}")

    if row["status"] == "closed":
        closed_missing = [f for f in _CLOSED_NON_NULL if row.get(f) is None]
        if closed_missing:
            raise ValueError(
                f"closed row has None for required fields: {sorted(closed_missing)}"
            )


class Ledger:
    """Wraps the two family journals plus the equity and signal journals."""

    def __init__(self, paths: LedgerPaths = LedgerPaths()):
        self.paths = paths
        self._h1 = Journal(paths.h1)
        self._h2 = Journal(paths.h2)
        self._equity = Journal(paths.equity)
        self._signals = Journal(paths.signals)

    def _journal_for(self, family: str) -> Journal:
        if family == "h1":
            return self._h1
        if family == "h2":
            return self._h2
        raise ValueError(f"invalid family: {family!r}")

    def append_row(self, row: dict) -> None:
        _validate_row(row)
        eid = row["entry_id"]
        prev_seq = max(
            (r["seq"] for r in self._all_rows() if r["entry_id"] == eid),
            default=0,
        )
        stamped = dict(row)
        stamped["schema_version"] = SCHEMA_VERSION
        stamped["seq"] = prev_seq + 1
        stamped["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
        self._journal_for(row["family"]).append(stamped)

    def _all_rows(self) -> list[dict]:
        return self._h1.read() + self._h2.read()

    def state(self) -> dict[str, dict]:
        """entry_id -> latest row (max seq) across both family journals."""
        latest: dict[str, dict] = {}
        for r in self._all_rows():
            eid = r["entry_id"]
            if eid not in latest or r["seq"] > latest[eid]["seq"]:
                latest[eid] = r
        return latest

    def open_rows(self, book: str | None = None) -> list[dict]:
        rows = [r for r in self.state().values() if r["status"] == "open"]
        if book is not None:
            rows = [r for r in rows if r["entry_id"].split(":", 1)[0] == book]
        return rows

    def held_symbols(self, book: str) -> set[str]:
        return {r["ticker"] for r in self.open_rows(book=book)}

    def append_equity_snapshot(self, snap: dict) -> None:
        key = (str(snap["date"]), snap["book"])
        for r in self._equity.read():
            if (str(r["date"]), r["book"]) == key:
                return
        self._equity.append(snap)

    def equity_series(self, book: str) -> list[dict]:
        return [r for r in self._equity.read() if r["book"] == book]

    def append_signal(self, rec: dict) -> None:
        key = (str(rec["signal_date"]), rec["book"], rec.get("entry_id"))
        for r in self._signals.read():
            if (str(r["signal_date"]), r["book"], r.get("entry_id")) == key:
                return
        self._signals.append(rec)

    def signals(self, signal_date: dt.date | None = None) -> list[dict]:
        rows = self._signals.read()
        if signal_date is not None:
            rows = [r for r in rows if str(r["signal_date"]) == str(signal_date)]
        return rows

    def processed_upkeep_dates(self) -> set[dt.date]:
        dates: set[dt.date] = set()
        for r in self._signals.read():
            if r.get("kind") == "upkeep_done":
                d = r["date"]
                if isinstance(d, str):
                    d = dt.date.fromisoformat(d)
                dates.add(d)
        return dates
