"""Per-family append-only ledger, built on top of the Journal primitive.

Two family journals (`ledger/h1.jsonl`, `ledger/h2.jsonl`) hold position
lifecycle rows (open -> closed, one row per status transition, latest `seq`
wins). A book-level equity snapshot journal (`ledger/equity.jsonl`) and a
signal journal (`ledger/signals.jsonl`) round out the ledger.

Dates/timestamps are serialized as ISO strings by the underlying Journal's
`json.dumps(..., default=str)`; readers get strings back and callers parse
them if they need `date`/`datetime` objects.

Legacy ledgers remain readable with their original schema.  A success-v2
ledger is explicitly constructed with ``LedgerPaths.success_v2`` and is
fail-closed: every write must carry the configured immutable
``strategy_version``, and its deterministic identity includes that version.

`Ledger` owns stamping `schema_version`, `seq`, and `updated_at` on every
row passed to `append_row` — `Journal.append` itself stamps nothing.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from sts.forward.journal import Journal

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
BOOKS = ("shared", "h1solo")
SOURCES = {"shared": "local-shared", "h1solo": "local-h1solo"}
SUCCESS_V2_ROOT = Path("ledger") / "success-v2"
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")

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
_SUCCESS_V2_ROW_FIELDS = frozenset(
    {
        "strategy_version",
        "target_initial",
        "stop_atr_multiple",
        "target_atr_multiple",
        "geometry",
    }
)

_VALID_FAMILIES = frozenset({"h1", "h2"})
_VALID_STATUSES = frozenset({"open", "closed"})

_VALID_SIGNAL_KINDS = frozenset(
    {
        "candidate",
        "skip",
        "missed_session",
        "upkeep_done",
        "signals_done",
        "notifications_done",
        "monitor_alert",
        "geometry_reject",
    }
)
_VALID_SKIP_REASONS = frozenset(
    {
        "slot",
        "throttle",
        "embargo",
        "dup_symbol",
        "deploy_cap",
        "size_zero",
        "invalid_actual_fill_geometry",
    }
)


def validate_strategy_version(strategy_version: str) -> str:
    """Return a safe canonical strategy version or raise.

    The restricted alphabet is deliberate: the version is used in local
    directory names, remote namespaces, and deterministic identities.
    """
    if not isinstance(strategy_version, str) or not _VERSION_RE.fullmatch(
        strategy_version
    ):
        raise ValueError(
            "strategy_version must match [a-z0-9][a-z0-9._-]{2,79}"
        )
    return strategy_version


def entry_id(
    book: str,
    family: str,
    symbol: str,
    signal_date: dt.date,
    *,
    strategy_version: str | None = None,
) -> str:
    """Deterministic position identity.

    The four-argument form is the frozen legacy identity.  Success-v2 callers
    must provide ``strategy_version``; the ``sv2|`` prefix makes a collision
    with every legacy identity structurally impossible.
    """
    if strategy_version is not None:
        version = validate_strategy_version(strategy_version)
        return (
            f"sv2|{version}|{book}:{family}:{symbol}:"
            f"{signal_date.isoformat()}"
        )
    return f"{book}:{family}:{symbol}:{signal_date.isoformat()}"


@dataclass
class LedgerPaths:
    root: Path = field(default_factory=lambda: Path("ledger"))
    strategy_version: str | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        if self.strategy_version is not None:
            validate_strategy_version(self.strategy_version)

    @classmethod
    def success_v2(
        cls,
        strategy_version: str,
        *,
        base_root: Path | str = Path("ledger"),
    ) -> LedgerPaths:
        """A fresh, disjoint local namespace for one locked strategy."""
        version = validate_strategy_version(strategy_version)
        return cls(
            root=Path(base_root) / "success-v2" / version,
            strategy_version=version,
        )

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

    def __init__(self, paths: LedgerPaths | None = None):
        if paths is None:
            paths = LedgerPaths()
        self.paths = paths
        self.strategy_version = paths.strategy_version
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
        version = row.get("strategy_version")
        if self.strategy_version is None:
            if version is not None or eid.startswith("sv2|"):
                raise ValueError(
                    "success-v2 rows cannot be written to the legacy ledger root"
                )
            book = eid.split(":", 1)[0]
        else:
            if version != self.strategy_version:
                raise ValueError(
                    f"row strategy_version {version!r} does not match ledger "
                    f"strategy_version {self.strategy_version!r}"
                )
            prefix = f"sv2|{self.strategy_version}|"
            if not eid.startswith(prefix):
                raise ValueError(
                    "success-v2 entry_id does not include the ledger strategy_version"
                )
            book = eid[len(prefix) :].split(":", 1)[0]
            missing_v2 = _SUCCESS_V2_ROW_FIELDS - row.keys()
            if missing_v2:
                raise ValueError(
                    "success-v2 ledger row missing required fields: "
                    f"{sorted(missing_v2)}"
                )
        if book not in BOOKS:
            raise ValueError(f"entry_id has invalid book prefix: {book!r}")
        if "book" in row and row["book"] is not None and row["book"] != book:
            raise ValueError(
                f"row['book'] {row['book']!r} conflicts with entry_id book {book!r}"
            )
        if row["source"] != SOURCES[book]:
            raise ValueError(
                f"row['source'] {row['source']!r} does not match "
                f"SOURCES[{book!r}] = {SOURCES[book]!r}"
            )
        prev_seq = max(
            (r["seq"] for r in self._all_rows() if r["entry_id"] == eid),
            default=0,
        )
        prior = self.state().get(eid)
        if prior is not None and prior.get("strategy_version") != version:
            raise ValueError("strategy_version is immutable across position rows")
        stamped = dict(row)
        stamped["book"] = book  # derived from entry_id — single source of truth
        stamped["schema_version"] = (
            SCHEMA_VERSION if self.strategy_version is not None else LEGACY_SCHEMA_VERSION
        )
        stamped["seq"] = prev_seq + 1
        if self.strategy_version is None:
            stamped["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
        else:
            # Event time, not wall-clock write time: a crash/retry produces
            # byte-identical facts.  seq disambiguates lifecycle transitions.
            event_at = (
                row.get("exit_timestamp")
                if row.get("status") == "closed"
                else row.get("timestamp")
            )
            stamped["updated_at"] = str(event_at)
        self._journal_for(row["family"]).append(stamped)

    def _all_rows(self) -> list[dict]:
        rows = self._h1.read() + self._h2.read()
        if self.strategy_version is not None:
            wrong = [
                r.get("entry_id")
                for r in rows
                if r.get("strategy_version") != self.strategy_version
            ]
            if wrong:
                raise ValueError(
                    "success-v2 ledger contains absent/mismatched strategy_version"
                )
        return rows

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
            rows = [r for r in rows if r["book"] == book]
        return rows

    def held_symbols(self, book: str) -> set[str]:
        return {r["ticker"] for r in self.open_rows(book=book)}

    def append_equity_snapshot(self, snap: dict) -> None:
        snap = self._versioned_write(snap, contract="equity snapshot")
        key = (snap.get("strategy_version"), str(snap["date"]), snap["book"])
        for r in self._equity.read():
            existing_key = (
                r.get("strategy_version"),
                str(r["date"]),
                r["book"],
            )
            if existing_key == key:
                if self.strategy_version is not None and r != snap:
                    raise ValueError("immutable equity snapshot content mismatch")
                return
        self._equity.append(snap)

    def equity_series(self, book: str) -> list[dict]:
        return [r for r in self._equity.read() if r["book"] == book]

    def append_signal(self, rec: dict) -> None:
        rec = self._versioned_write(rec, contract="signal")
        kind = rec.get("kind")
        if kind not in _VALID_SIGNAL_KINDS:
            raise ValueError(f"invalid signal kind: {kind!r}")
        if kind == "skip" and rec.get("reason") not in _VALID_SKIP_REASONS:
            raise ValueError(f"invalid skip reason: {rec.get('reason')!r}")
        key = self._signal_key(rec)
        for r in self._signals.read():
            if self._signal_key(r) == key:
                if self.strategy_version is not None and r != rec:
                    raise ValueError("immutable signal content mismatch")
                return
        self._signals.append(rec)

    @staticmethod
    def _signal_key(rec: dict) -> tuple:
        version = rec.get("strategy_version")
        key = (
            version,
            str(rec["signal_date"]),
            rec["book"],
            rec.get("entry_id"),
        )
        if version is not None:
            # A versioned candidate and its later fill-time disposition are
            # distinct append-only facts even though they share entry_id.
            return (*key, rec.get("kind"))
        if rec.get("entry_id") is None:
            return (*key, rec.get("kind"))
        return key

    def _versioned_write(self, rec: dict, *, contract: str) -> dict:
        """Validate namespace isolation without mutating the caller's dict."""
        out = dict(rec)
        version = out.get("strategy_version")
        if self.strategy_version is None:
            if version is not None:
                raise ValueError(
                    f"success-v2 {contract} cannot be written to legacy ledger root"
                )
            return out
        if version != self.strategy_version:
            raise ValueError(
                f"{contract} strategy_version {version!r} does not match ledger "
                f"strategy_version {self.strategy_version!r}"
            )
        if out.get("summary") is not None:
            summary_version = out["summary"].get("strategy_version")
            if summary_version != self.strategy_version:
                raise ValueError(
                    "summary strategy_version must match its signal contract"
                )
        return out

    def signals(self, signal_date: dt.date | None = None) -> list[dict]:
        rows = self._signals.read()
        if signal_date is not None:
            rows = [r for r in rows if str(r["signal_date"]) == str(signal_date)]
        return rows

    def _processed_control_dates(self, kind: str) -> set[dt.date]:
        dates: set[dt.date] = set()
        for r in self._signals.read():
            if r.get("kind") == kind:
                d = r.get("date", r["signal_date"])
                if isinstance(d, str):
                    d = dt.date.fromisoformat(d)
                dates.add(d)
        return dates

    def processed_upkeep_dates(self) -> set[dt.date]:
        return self._processed_control_dates("upkeep_done")

    def processed_signal_dates(self) -> set[dt.date]:
        return self._processed_control_dates("signals_done")

    def processed_notification_dates(self) -> set[dt.date]:
        return self._processed_control_dates("notifications_done")
