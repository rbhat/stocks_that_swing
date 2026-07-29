"""Fail-closed, read-only input resolution for ``swing-ranking-v1``.

The cache layout intentionally has a small, explicit interchange schema.  A
source manifest contains one ``content_sha256`` for every required source
kind.  The security master uses ``securities`` records, symbol history uses
``history`` records, and corporate-action and earnings files use ``coverage``
records.  Every record names ``permanent_id``; history also names ``symbol``,
``start``, and ``end_exclusive``.  Coverage records name ``permanent_id``,
``coverage_start``, and ``coverage_end_exclusive``.

Preflight never returns data frames.  It reads cache files only long enough to
validate their identity, quality, and coverage, then returns immutable input
metadata that can be frozen into the discovery protocol before evaluation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from sts import calendar
from sts.data import quality
from sts.swing_ranking.contracts import (
    ADJUSTMENT_BASIS,
    REQUIRED_SOURCE_KINDS,
    DiscoveryProtocol,
    SourceFact,
)
from sts.swing_ranking.identity import IdentityViolation, identity_hash, require_sha256

_OHLCV = ("open", "high", "low", "close", "volume")
_DATA_HASH_DOMAIN = "swing-ranking-v1/parquet-inventory/v1"
_SECURITY_IDENTITY_DOMAIN = "swing-ranking-v1/security-identity-inputs/v1"
_RESOLVED_INPUT_DOMAIN = "swing-ranking-v1/resolved-inputs/v1"


class PreflightViolation(ValueError):
    """An input cache is incomplete, altered, or has ambiguous identity."""


def _fail(message: str) -> None:
    raise PreflightViolation(message)


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        _fail(f"required input is absent or not a file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        _fail(f"cannot read required input {path}: {exc}")
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is unreadable JSON: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _read_yaml(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _fail(f"{label} is unreadable YAML: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a YAML object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value.strip()


def _date(value: object, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(_text(value, label))
    except ValueError as exc:
        _fail(f"{label} must be an ISO date: {exc}")
    raise AssertionError("unreachable")


def _sha256(value: object, label: str) -> str:
    try:
        return require_sha256(_text(value, label), label)
    except IdentityViolation as exc:
        _fail(str(exc))
    raise AssertionError("unreachable")


def _items(value: object, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail(f"{label} must be a list")
    items = tuple(value)
    if not items:
        _fail(f"{label} cannot be empty")
    return items


def _records(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    records = _items(value, label)
    if not all(isinstance(record, Mapping) for record in records):
        _fail(f"{label} must contain objects")
    return records


def _symbol(value: object, label: str) -> str:
    symbol = _text(value, label).upper()
    if symbol != value.strip():
        _fail(f"{label} must be uppercase")
    return symbol


def _permanent_id(value: object, symbol: str, label: str) -> str:
    permanent_id = _text(value, label)
    if permanent_id.upper() == symbol:
        _fail(f"{label} cannot be the ticker symbol {symbol!r}")
    return permanent_id


@dataclass(frozen=True)
class PreflightPaths:
    """Every external input is explicit; preflight never discovers paths."""

    roster: Path
    roster_manifest: Path
    source_manifest: Path
    security_master: Path
    symbol_history: Path
    corporate_actions: Path
    earnings_calendar: Path
    exchange_calendar: Path
    parquet_root: Path

    def __post_init__(self) -> None:
        for field in (
            "roster",
            "roster_manifest",
            "source_manifest",
            "security_master",
            "symbol_history",
            "corporate_actions",
            "earnings_calendar",
            "exchange_calendar",
            "parquet_root",
        ):
            value = getattr(self, field)
            if not isinstance(value, Path):
                _fail(f"{field} must be a pathlib.Path")


@dataclass(frozen=True)
class ResolvedSecurity:
    """One current roster member resolved through permanent identity facts."""

    permanent_id: str
    symbol: str

    def __post_init__(self) -> None:
        symbol = _symbol(self.symbol, "resolved symbol")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "permanent_id",
            _permanent_id(self.permanent_id, symbol, "resolved permanent_id"),
        )


@dataclass(frozen=True)
class ResolvedParquet:
    """Validated parquet identity and non-performance coverage metadata."""

    permanent_id: str
    symbol: str
    file_sha256: str
    first_session: dt.date
    last_session: dt.date
    n_bars: int

    def __post_init__(self) -> None:
        symbol = _symbol(self.symbol, "resolved parquet symbol")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "permanent_id",
            _permanent_id(self.permanent_id, symbol, "resolved parquet permanent_id"),
        )
        _sha256(self.file_sha256, f"{symbol} file_sha256")
        if not isinstance(self.first_session, dt.date) or isinstance(
            self.first_session, dt.datetime
        ):
            _fail(f"{symbol} first_session must be a date")
        if not isinstance(self.last_session, dt.date) or isinstance(
            self.last_session, dt.datetime
        ):
            _fail(f"{symbol} last_session must be a date")
        if self.first_session > self.last_session:
            _fail(f"{symbol} parquet coverage is reversed")
        if isinstance(self.n_bars, bool) or not isinstance(self.n_bars, int) or self.n_bars < 1:
            _fail(f"{symbol} n_bars must be a positive integer")


@dataclass(frozen=True, order=True)
class ResolvedEarnings:
    """One point-in-time-safe scheduled earnings fact."""

    permanent_id: str
    earnings_session: dt.date
    known_session: dt.date
    superseded_session: dt.date | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permanent_id",
            _text(self.permanent_id, "earnings permanent_id"),
        )
        if (
            isinstance(self.earnings_session, dt.datetime)
            or not isinstance(self.earnings_session, dt.date)
            or isinstance(self.known_session, dt.datetime)
            or not isinstance(self.known_session, dt.date)
        ):
            _fail("earnings sessions must be dates")
        if self.known_session > self.earnings_session:
            _fail("earnings known_session cannot follow the event")
        superseded = self.superseded_session
        if superseded is not None:
            if isinstance(superseded, dt.datetime) or not isinstance(
                superseded,
                dt.date,
            ):
                _fail("earnings superseded_session must be a date")
            if superseded <= self.known_session:
                _fail("earnings superseded_session must follow known_session")


@dataclass(frozen=True)
class ResolvedInputs:
    """Immutable, hashable metadata only; no price frames escape preflight."""

    protocol_identity: str
    roster_sha256: str
    roster_manifest_sha256: str
    source_manifest_sha256: str
    source_facts: tuple[SourceFact, ...]
    securities: tuple[ResolvedSecurity, ...]
    parquets: tuple[ResolvedParquet, ...]
    earnings_events: tuple[ResolvedEarnings, ...]

    def __post_init__(self) -> None:
        _sha256(self.protocol_identity, "protocol_identity")
        for name in ("roster_sha256", "roster_manifest_sha256", "source_manifest_sha256"):
            _sha256(getattr(self, name), name)
        facts = tuple(self.source_facts)
        if not all(isinstance(fact, SourceFact) for fact in facts):
            _fail("source_facts must contain SourceFact values")
        if {fact.kind for fact in facts} != set(REQUIRED_SOURCE_KINDS):
            _fail("source_facts must include every required source kind")
        object.__setattr__(self, "source_facts", tuple(sorted(facts, key=lambda item: item.kind)))
        securities = tuple(self.securities)
        if not securities or not all(isinstance(item, ResolvedSecurity) for item in securities):
            _fail("securities must contain resolved securities")
        if len({item.symbol for item in securities}) != len(securities):
            _fail("resolved securities contain duplicate symbols")
        if len({item.permanent_id for item in securities}) != len(securities):
            _fail("resolved securities contain duplicate permanent IDs")
        object.__setattr__(self, "securities", tuple(sorted(securities, key=lambda item: item.permanent_id)))
        parquets = tuple(self.parquets)
        if len(parquets) != len(securities) or not all(
            isinstance(item, ResolvedParquet) for item in parquets
        ):
            _fail("parquets must contain exactly one resolved parquet per security")
        if {(item.permanent_id, item.symbol) for item in parquets} != {
            (item.permanent_id, item.symbol) for item in securities
        }:
            _fail("resolved parquets do not exactly match resolved securities")
        object.__setattr__(self, "parquets", tuple(sorted(parquets, key=lambda item: item.permanent_id)))
        events = tuple(self.earnings_events)
        if not all(isinstance(item, ResolvedEarnings) for item in events):
            _fail("earnings_events must contain ResolvedEarnings values")
        if len(events) != len(set(events)):
            _fail("earnings_events contain duplicate facts")
        known_ids = {item.permanent_id for item in securities}
        if any(item.permanent_id not in known_ids for item in events):
            _fail("earnings_events reference an unknown permanent ID")
        object.__setattr__(self, "earnings_events", tuple(sorted(events)))

    @property
    def identity(self) -> str:
        return identity_hash(_RESOLVED_INPUT_DOMAIN, self)


def _roster_symbols(path: Path) -> tuple[str, ...]:
    roster = _read_yaml(path, "roster")
    symbols = _items(roster.get("symbols"), "roster symbols")
    result = tuple(_symbol(item, "roster symbol") for item in symbols)
    if len(set(result)) != len(result):
        _fail("roster contains duplicate symbols")
    count = roster.get("count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count != len(result)):
        _fail("roster count does not equal its explicit symbols")
    return result


def _validate_inventory(
    path: Path,
    roster_symbols: tuple[str, ...],
    root: Path,
    protocol: DiscoveryProtocol,
    permanent_ids: Mapping[str, str],
) -> tuple[ResolvedParquet, ...]:
    manifest = _read_json(path, "roster manifest")
    if manifest.get("adjustment_basis") != "split+dividend adjusted total return (auto_adjust=True)":
        _fail("roster manifest adjustment basis is not adjusted total return")
    entries = manifest.get("symbols")
    if not isinstance(entries, Mapping):
        _fail("roster manifest symbols must be an object")
    normalized_entries: dict[str, Mapping[str, Any]] = {}
    for raw_symbol, entry in entries.items():
        symbol = _symbol(raw_symbol, "roster manifest symbol")
        if symbol in normalized_entries or not isinstance(entry, Mapping):
            _fail("roster manifest has duplicate or malformed symbol entries")
        normalized_entries[symbol] = entry
    if set(normalized_entries) != set(roster_symbols):
        _fail("roster manifest inventory has absent or extra symbols")
    if not root.is_dir():
        _fail(f"parquet root is absent or not a directory: {root}")
    files = {item.stem.upper(): item for item in root.iterdir() if item.is_file() and item.suffix == ".parquet"}
    if len(files) != len([item for item in root.iterdir() if item.is_file() and item.suffix == ".parquet"]):
        _fail("parquet root has case-colliding parquet names")
    if set(files) != set(roster_symbols):
        _fail("parquet inventory has absent or extra files")
    resolved: list[ResolvedParquet] = []
    for symbol in roster_symbols:
        entry = normalized_entries[symbol]
        file_path = files[symbol]
        expected_hash = _sha256(entry.get("file_sha256"), f"{symbol} manifest file_sha256")
        actual_hash = _sha256_file(file_path)
        if actual_hash != expected_hash:
            _fail(f"{symbol} parquet hash differs from roster manifest")
        try:
            frame = pd.read_parquet(file_path)
        except (OSError, ValueError) as exc:
            _fail(f"{symbol} parquet is unreadable: {exc}")
        if tuple(frame.columns) != _OHLCV:
            _fail(f"{symbol} parquet columns must equal {_OHLCV!r}")
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
            _fail(f"{symbol} parquet index must be a timezone-naive DatetimeIndex")
        report = quality.check(symbol, frame)
        if not report.ok:
            _fail(f"{symbol} parquet quality failure: {'; '.join(report.errors)}")
        if frame.empty:
            _fail(f"{symbol} parquet is empty")
        first = frame.index[0].date()
        last = frame.index[-1].date()
        if first > protocol.evaluation_start:
            _fail(f"{symbol} parquet does not cover protocol evaluation start")
        if last != protocol.data_cutoff:
            _fail(f"{symbol} parquet does not cover protocol cutoff {protocol.data_cutoff}")
        if first != _date(entry.get("first_session"), f"{symbol} manifest first_session"):
            _fail(f"{symbol} parquet first_session differs from roster manifest")
        if last != _date(entry.get("last_session"), f"{symbol} manifest last_session"):
            _fail(f"{symbol} parquet last_session differs from roster manifest")
        n_bars = entry.get("n_bars")
        if isinstance(n_bars, bool) or not isinstance(n_bars, int) or n_bars != len(frame):
            _fail(f"{symbol} parquet n_bars differs from roster manifest")
        resolved.append(
            ResolvedParquet(
                permanent_id=permanent_ids[symbol],
                symbol=symbol,
                file_sha256=actual_hash,
                first_session=first,
                last_session=last,
                n_bars=len(frame),
            )
        )
    return tuple(resolved)


def _resolve_securities(
    security_master: Mapping[str, Any],
    symbol_history: Mapping[str, Any],
    roster_symbols: tuple[str, ...],
    protocol: DiscoveryProtocol,
) -> tuple[ResolvedSecurity, ...]:
    master_records = _records(security_master.get("securities"), "security master securities")
    by_symbol: dict[str, str] = {}
    all_ids: set[str] = set()
    for record in master_records:
        symbol = _symbol(record.get("symbol"), "security master symbol")
        permanent_id = _permanent_id(record.get("permanent_id"), symbol, "security master permanent_id")
        if symbol in by_symbol or permanent_id in all_ids:
            _fail("security master contains duplicate symbol or permanent ID")
        by_symbol[symbol] = permanent_id
        all_ids.add(permanent_id)
    if not set(roster_symbols).issubset(by_symbol):
        _fail("security master has a roster symbol with no permanent ID")
    resolved = tuple(ResolvedSecurity(by_symbol[symbol], symbol) for symbol in roster_symbols)
    history_records = _records(symbol_history.get("history"), "symbol history records")
    intervals: dict[str, list[tuple[dt.date, dt.date]]] = {item.permanent_id: [] for item in resolved}
    for record in history_records:
        symbol = _symbol(record.get("symbol"), "symbol history symbol")
        permanent_id = _permanent_id(record.get("permanent_id"), symbol, "symbol history permanent_id")
        if permanent_id not in all_ids:
            _fail("symbol history references a permanent ID absent from security master")
        start = _date(record.get("start"), "symbol history start")
        end = _date(record.get("end_exclusive"), "symbol history end_exclusive")
        if start >= end:
            _fail("symbol history has an empty or reversed interval")
        if permanent_id in intervals:
            intervals[permanent_id].append((start, end))
    for item in resolved:
        covered = any(
            start <= protocol.evaluation_start and end > protocol.data_cutoff
            for start, end in intervals[item.permanent_id]
        )
        if not covered:
            _fail(f"symbol history lacks full protocol coverage for {item.permanent_id}")
    return resolved


def _validate_coverage(
    document: Mapping[str, Any],
    label: str,
    resolved: tuple[ResolvedSecurity, ...],
    protocol: DiscoveryProtocol,
    require_adjustment_vintage: bool,
) -> None:
    if require_adjustment_vintage:
        if document.get("adjustment_basis") != ADJUSTMENT_BASIS:
            _fail("corporate actions adjustment basis differs from the protocol")
        vintage = _date(document.get("adjustment_vintage"), "corporate actions adjustment_vintage")
        if vintage > protocol.data_cutoff:
            _fail("corporate actions adjustment_vintage is after protocol cutoff")
    records = _records(document.get("coverage"), f"{label} coverage")
    coverage: dict[str, tuple[dt.date, dt.date]] = {}
    for record in records:
        permanent_id = _text(record.get("permanent_id"), f"{label} coverage permanent_id")
        start = _date(record.get("coverage_start"), f"{label} coverage_start")
        end = _date(record.get("coverage_end_exclusive"), f"{label} coverage_end_exclusive")
        if start >= end or permanent_id in coverage:
            _fail(f"{label} coverage has duplicate, empty, or reversed facts")
        coverage[permanent_id] = (start, end)
    for item in resolved:
        interval = coverage.get(item.permanent_id)
        if interval is None or interval[0] > protocol.evaluation_start or interval[1] <= protocol.data_cutoff:
            _fail(f"{label} has missing or incomplete fact coverage for {item.permanent_id}")


def _resolve_earnings_events(
    document: Mapping[str, Any],
    resolved: tuple[ResolvedSecurity, ...],
    protocol: DiscoveryProtocol,
) -> tuple[ResolvedEarnings, ...]:
    raw_events = document.get("events")
    if not isinstance(raw_events, Sequence) or isinstance(
        raw_events,
        (str, bytes, bytearray),
    ):
        _fail("earnings calendar events must be a list")
    known_ids = {item.permanent_id for item in resolved}
    events: list[ResolvedEarnings] = []
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            _fail("earnings calendar events must contain objects")
        event = ResolvedEarnings(
            permanent_id=_text(
                raw.get("permanent_id"),
                "earnings event permanent_id",
            ),
            earnings_session=_date(
                raw.get("earnings_session"),
                "earnings event earnings_session",
            ),
            known_session=_date(
                raw.get("known_session"),
                "earnings event known_session",
            ),
            superseded_session=(
                None
                if raw.get("superseded_session") is None
                else _date(
                    raw.get("superseded_session"),
                    "earnings event superseded_session",
                )
            ),
        )
        if event.permanent_id not in known_ids:
            _fail("earnings event references an unknown permanent ID")
        if event.known_session > protocol.data_cutoff:
            _fail("earnings event was not known by the protocol cutoff")
        events.append(event)
    if len(events) != len(set(events)):
        _fail("earnings calendar contains duplicate events")
    return tuple(sorted(events))


def _validate_exchange_calendar(document: Mapping[str, Any], protocol: DiscoveryProtocol) -> None:
    if document.get("exchange") != "XNYS":
        _fail("exchange calendar must explicitly identify XNYS")
    start = _date(document.get("coverage_start"), "exchange calendar coverage_start")
    end = _date(document.get("coverage_end_exclusive"), "exchange calendar coverage_end_exclusive")
    if start > protocol.evaluation_start or end <= protocol.data_cutoff:
        _fail("exchange calendar does not cover the protocol through its cutoff")
    session_values = _items(document.get("sessions"), "exchange calendar sessions")
    sessions = tuple(_date(value, "exchange calendar session") for value in session_values)
    if len(set(sessions)) != len(sessions) or tuple(sorted(sessions)) != sessions:
        _fail("exchange calendar sessions must be unique and sorted")
    expected = tuple(
        item.date()
        for item in calendar.sessions_between(protocol.evaluation_start, protocol.data_cutoff)
    )
    actual = tuple(item for item in sessions if protocol.evaluation_start <= item <= protocol.data_cutoff)
    if actual != expected:
        _fail("exchange calendar sessions differ from the required XNYS sessions")


def _validate_source_manifest(
    document: Mapping[str, Any], protocol: DiscoveryProtocol, actual_hashes: Mapping[str, str]
) -> tuple[SourceFact, ...]:
    sources = document.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != set(REQUIRED_SOURCE_KINDS):
        _fail("source manifest must contain exactly every required source kind")
    by_kind = {fact.kind: fact for fact in protocol.source_facts}
    resolved: list[SourceFact] = []
    for kind in REQUIRED_SOURCE_KINDS:
        entry = sources[kind]
        if not isinstance(entry, Mapping):
            _fail(f"source manifest {kind} must be an object")
        content_hash = _sha256(entry.get("content_sha256"), f"source manifest {kind} content_sha256")
        if content_hash != actual_hashes[kind]:
            _fail(f"source manifest identity mismatch for {kind}")
        fact = by_kind[kind]
        if content_hash != fact.content_hash:
            _fail(f"protocol source identity mismatch for {kind}")
        for field, expected in (
            ("as_of", fact.as_of),
            ("coverage_start", fact.coverage_start),
            ("coverage_end_exclusive", fact.coverage_end_exclusive),
            ("adjustment_basis", fact.adjustment_basis),
        ):
            value = entry.get(field)
            actual = _date(value, f"source manifest {kind} {field}") if field != "adjustment_basis" else value
            if actual != expected:
                _fail(f"source manifest fact mismatch for {kind} {field}")
        resolved.append(fact)
    return tuple(resolved)


def resolve_inputs(protocol: DiscoveryProtocol, paths: PreflightPaths) -> ResolvedInputs:
    """Read and validate a complete cache, returning metadata or raising.

    The caller supplies an already pre-registered protocol.  This function has
    no network or write operations and deliberately has no partial-result mode.
    """
    if not isinstance(protocol, DiscoveryProtocol):
        _fail("protocol must be a DiscoveryProtocol")
    if not isinstance(paths, PreflightPaths):
        _fail("paths must be a PreflightPaths")
    if not calendar.is_session(protocol.data_cutoff):
        _fail("protocol data_cutoff must be an XNYS session")
    roster_sha = _sha256_file(paths.roster)
    roster_manifest_sha = _sha256_file(paths.roster_manifest)
    source_manifest_sha = _sha256_file(paths.source_manifest)
    security_master_sha = _sha256_file(paths.security_master)
    symbol_history_sha = _sha256_file(paths.symbol_history)
    corporate_actions_sha = _sha256_file(paths.corporate_actions)
    earnings_sha = _sha256_file(paths.earnings_calendar)
    exchange_sha = _sha256_file(paths.exchange_calendar)
    roster = _roster_symbols(paths.roster)
    security_master = _read_json(paths.security_master, "security master")
    symbol_history = _read_json(paths.symbol_history, "symbol history")
    resolved = _resolve_securities(security_master, symbol_history, roster, protocol)
    permanent_ids = {item.symbol: item.permanent_id for item in resolved}
    parquets = _validate_inventory(
        paths.roster_manifest, roster, paths.parquet_root, protocol, permanent_ids
    )
    corporate_actions = _read_json(paths.corporate_actions, "corporate actions")
    _validate_coverage(corporate_actions, "corporate actions", resolved, protocol, True)
    earnings = _read_json(paths.earnings_calendar, "earnings calendar")
    _validate_coverage(earnings, "earnings calendar", resolved, protocol, False)
    earnings_events = _resolve_earnings_events(earnings, resolved, protocol)
    exchange = _read_json(paths.exchange_calendar, "exchange calendar")
    _validate_exchange_calendar(exchange, protocol)
    inventory_hash = identity_hash(
        _DATA_HASH_DOMAIN,
        tuple(sorted(parquets, key=lambda item: item.permanent_id)),
    )
    security_identity_hash = identity_hash(
        _SECURITY_IDENTITY_DOMAIN,
        {
            "security_master_sha256": security_master_sha,
            "symbol_history_sha256": symbol_history_sha,
        },
    )
    actual_hashes = {
        "security_master": security_identity_hash,
        "current_roster": roster_sha,
        "daily_market_data": inventory_hash,
        "corporate_actions": corporate_actions_sha,
        "earnings_calendar": earnings_sha,
        "exchange_calendar": exchange_sha,
    }
    source_manifest = _read_json(paths.source_manifest, "source manifest")
    facts = _validate_source_manifest(source_manifest, protocol, actual_hashes)
    return ResolvedInputs(
        protocol_identity=protocol.identity,
        roster_sha256=roster_sha,
        roster_manifest_sha256=roster_manifest_sha,
        source_manifest_sha256=source_manifest_sha,
        source_facts=facts,
        securities=resolved,
        parquets=parquets,
        earnings_events=earnings_events,
    )


__all__ = [
    "PreflightPaths",
    "PreflightViolation",
    "ResolvedEarnings",
    "ResolvedInputs",
    "ResolvedParquet",
    "ResolvedSecurity",
    "resolve_inputs",
]
