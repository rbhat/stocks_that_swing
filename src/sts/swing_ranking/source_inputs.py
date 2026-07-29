"""Reproducible security-identity and earnings input construction."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from curl_cffi import requests

from sts import calendar

OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
INVESTING_CALENDAR_URL = "https://www.investing.com/earnings-calendar"
INVESTING_EARNINGS_URL = "https://endpoints.investing.com/earnings"
INVESTING_SEARCH_URL = "https://api.investing.com/api/search/v2/search"

_FIGI_PATTERN = re.compile(r"^BBG[0-9A-Z]{9}$")
_NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_US_EXCHANGES = {
    "NASDAQ",
    "NASDAQ OTC",
    "NYSE",
    "NYSE AMEX",
    "NYSE ARCA",
}


class SourceInputViolation(ValueError):
    """A source response or normalized input is incomplete or ambiguous."""


def _fail(message: str) -> None:
    raise SourceInputViolation(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(Path(path).read_bytes())
    except OSError as exc:
        _fail(f"cannot hash {path}: {exc}")
    raise AssertionError("unreachable")


def atomic_write(path: Path, content: bytes, *, replace: bool) -> None:
    """Write bytes through a sibling temp file, fsync, and atomic replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not replace:
        if target.read_bytes() == content:
            return
        _fail(f"refusing to replace unequal append-only input {target}")
    temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def json_bytes(value: object, *, pretty: bool = True) -> bytes:
    options: dict[str, Any] = {
        "ensure_ascii": False,
        "sort_keys": True,
        "allow_nan": False,
    }
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    return (json.dumps(value, **options) + "\n").encode("utf-8")


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


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def roster_symbols(path: Path) -> tuple[str, ...]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _fail(f"roster is unreadable: {exc}")
    if not isinstance(value, Mapping) or not isinstance(value.get("symbols"), list):
        _fail("roster must contain an explicit symbols list")
    symbols = tuple(_text(symbol, "roster symbol").upper() for symbol in value["symbols"])
    if len(symbols) != len(set(symbols)):
        _fail("roster symbols must be unique")
    if value.get("count") != len(symbols):
        _fail("roster count must equal the symbols list")
    return symbols


def _openfigi_ticker(symbol: str) -> str:
    return symbol.replace("-", "/")


def openfigi_jobs(symbols: Sequence[str]) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "idType": "TICKER",
            "idValue": _openfigi_ticker(_text(symbol, "symbol").upper()),
            "exchCode": "US",
        }
        for symbol in symbols
    )


def select_openfigi_security(
    symbol: str,
    result: object,
) -> dict[str, str]:
    """Resolve one exact US-listed share class or fail on ambiguity."""
    symbol = _text(symbol, "symbol").upper()
    if not isinstance(result, Mapping):
        _fail(f"OpenFIGI result for {symbol} must be an object")
    if "error" in result or "warning" in result:
        _fail(f"OpenFIGI did not resolve {symbol}: {result}")
    rows = result.get("data")
    if not isinstance(rows, list):
        _fail(f"OpenFIGI result for {symbol} has no data list")
    query_ticker = _openfigi_ticker(symbol)
    candidates: dict[str, dict[str, str]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        share_class_figi = raw.get("shareClassFIGI")
        composite_figi = raw.get("compositeFIGI")
        if (
            raw.get("ticker") != query_ticker
            or raw.get("exchCode") != "US"
            or raw.get("securityType2")
            not in {"Common Stock", "Depositary Receipt", "Mutual Fund", "REIT"}
            or not isinstance(share_class_figi, str)
            or not _FIGI_PATTERN.fullmatch(share_class_figi)
            or not isinstance(composite_figi, str)
            or not _FIGI_PATTERN.fullmatch(composite_figi)
        ):
            continue
        candidates[share_class_figi] = {
            "permanent_id": share_class_figi,
            "permanent_id_type": "ID_BB_GLOBAL_SHARE_CLASS_LEVEL",
            "composite_figi": composite_figi,
            "symbol": symbol,
            "openfigi_ticker": query_ticker,
            "name": _text(raw.get("name"), f"{symbol} OpenFIGI name"),
            "security_type": _text(
                raw.get("securityType"),
                f"{symbol} OpenFIGI securityType",
            ),
            "security_type_2": _text(
                raw.get("securityType2"),
                f"{symbol} OpenFIGI securityType2",
            ),
        }
    if len(candidates) != 1:
        _fail(
            f"OpenFIGI mapping for {symbol} must resolve exactly one share class; "
            f"found {len(candidates)}"
        )
    return next(iter(candidates.values()))


def normalize_security_inputs(
    *,
    symbols: Sequence[str],
    mapping_results: Sequence[object],
    roster_manifest: Mapping[str, Any],
    raw_sha256: str,
    retrieved_at: str,
    coverage_end_exclusive: dt.date,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build permanent-ID master and cache-symbol history documents."""
    values = tuple(_text(symbol, "symbol").upper() for symbol in symbols)
    results = tuple(mapping_results)
    if len(values) != len(results):
        _fail("OpenFIGI mapping result count must equal the roster")
    if not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
        _fail("OpenFIGI raw_sha256 must be lowercase SHA-256")
    if (
        isinstance(coverage_end_exclusive, dt.datetime)
        or not isinstance(coverage_end_exclusive, dt.date)
    ):
        _fail("coverage_end_exclusive must be a date")
    entries = roster_manifest.get("symbols")
    if not isinstance(entries, Mapping) or set(entries) != set(values):
        _fail("roster manifest must exactly cover security-input symbols")
    securities = tuple(
        sorted(
            (
                select_openfigi_security(symbol, result)
                for symbol, result in zip(values, results, strict=True)
            ),
            key=lambda row: row["permanent_id"],
        )
    )
    if len({row["permanent_id"] for row in securities}) != len(securities):
        _fail("OpenFIGI permanent IDs must be unique across the roster")
    by_symbol = {row["symbol"]: row["permanent_id"] for row in securities}
    history: list[dict[str, object]] = []
    for symbol in sorted(values):
        raw_entry = entries[symbol]
        if not isinstance(raw_entry, Mapping):
            _fail(f"roster manifest entry for {symbol} must be an object")
        start = _date(raw_entry.get("first_session"), f"{symbol} first_session")
        if start >= coverage_end_exclusive:
            _fail(f"{symbol} cache-symbol interval is empty")
        history.append(
            {
                "permanent_id": by_symbol[symbol],
                "symbol": symbol,
                "start": start.isoformat(),
                "end_exclusive": coverage_end_exclusive.isoformat(),
            }
        )
    source = {
        "provider": "OpenFIGI",
        "endpoint": OPENFIGI_MAPPING_URL,
        "retrieved_at": _text(retrieved_at, "retrieved_at"),
        "raw_sha256": raw_sha256,
    }
    security_master = {
        "schema_version": "swing-ranking-v1.security-master.v1",
        "source": source,
        "securities": list(securities),
    }
    symbol_history = {
        "schema_version": "swing-ranking-v1.symbol-history.v1",
        "namespace": "yahoo_current_roster_adjusted_history",
        "source": {
            "provider": "local validated parquet cache",
            "manifest": "configs/study_roster_manifest.json",
            "openfigi_raw_sha256": raw_sha256,
        },
        "history": history,
    }
    return security_master, symbol_history


def fetch_openfigi_mappings(
    symbols: Sequence[str],
    *,
    api_key: str | None,
) -> tuple[list[dict[str, object]], tuple[object, ...]]:
    """Fetch ordered mapping batches and return archive rows plus flat results."""
    values = tuple(symbols)
    batch_size = 100 if api_key else 10
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    archives: list[dict[str, object]] = []
    flat: list[object] = []
    for offset in range(0, len(values), batch_size):
        batch_symbols = values[offset : offset + batch_size]
        jobs = openfigi_jobs(batch_symbols)
        while True:
            response = requests.post(
                OPENFIGI_MAPPING_URL,
                headers=headers,
                data=json.dumps(jobs, separators=(",", ":")),
                impersonate="chrome",
                timeout=30,
            )
            if response.status_code != 429:
                break
            retry_after = response.headers.get("retry-after")
            try:
                delay = max(1, min(60, int(retry_after or "1")))
            except ValueError:
                delay = 1
            time.sleep(delay)
        if response.status_code != 200:
            _fail(
                f"OpenFIGI mapping failed with HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            results = response.json()
        except ValueError as exc:
            _fail(f"OpenFIGI returned invalid JSON: {exc}")
        if not isinstance(results, list) or len(results) != len(jobs):
            _fail("OpenFIGI response count does not match its request")
        archives.append(
            {
                "symbols": list(batch_symbols),
                "request": list(jobs),
                "response": results,
            }
        )
        flat.extend(results)
    return archives, tuple(flat)


def investing_access_token(session: requests.Session) -> tuple[str, bytes]:
    response = session.get(INVESTING_CALENDAR_URL, timeout=30)
    if response.status_code != 200:
        _fail(f"Investing.com calendar failed with HTTP {response.status_code}")
    raw = response.content
    match = _NEXT_DATA_PATTERN.search(response.text)
    if match is None:
        _fail("Investing.com calendar lacks __NEXT_DATA__")
    try:
        document = json.loads(match.group(1))
        token = document["props"]["pageProps"]["accessToken"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        _fail(f"Investing.com calendar access token is absent: {exc}")
    return _text(token, "Investing.com access token"), raw


def _symbol_key(value: str) -> str:
    return re.sub(r"[-./]", "", value.upper())


def investing_search_query(symbol: str) -> str:
    """Translate Yahoo class notation to Investing.com's class suffix."""
    value = _text(symbol, "symbol")
    if "-" not in value:
        return value
    base, share_class = value.rsplit("-", 1)
    if not base or len(share_class) != 1 or not share_class.isalpha():
        _fail(f"unsupported class-share symbol {value!r}")
    return base + share_class.lower()


def select_investing_instrument(symbol: str, response: object) -> dict[str, object]:
    symbol = _text(symbol, "symbol").upper()
    if not isinstance(response, Mapping) or not isinstance(response.get("quotes"), list):
        _fail(f"Investing.com search response for {symbol} lacks quotes")
    matches: dict[int, dict[str, object]] = {}
    for raw in response["quotes"]:
        if not isinstance(raw, Mapping):
            continue
        instrument_id = raw.get("id")
        exchange = str(raw.get("exchange", "")).upper()
        quote_type = str(raw.get("type", ""))
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or _symbol_key(str(raw.get("symbol", ""))) != _symbol_key(symbol)
            or str(raw.get("flag", "")).upper() != "USA"
            or exchange not in _US_EXCHANGES
            or not quote_type.startswith(("Stock", "ETF"))
        ):
            continue
        matches[instrument_id] = {
            "investing_instrument_id": instrument_id,
            "symbol": symbol,
            "description": _text(
                raw.get("description"),
                f"{symbol} Investing.com description",
            ),
            "exchange": exchange,
            "instrument_type": quote_type,
            "url": _text(raw.get("url"), f"{symbol} Investing.com url"),
        }
    if len(matches) != 1:
        _fail(
            f"Investing.com search for {symbol} must resolve exactly one US "
            f"instrument; found {len(matches)}"
        )
    return next(iter(matches.values()))


def _completed_or_next_session(value: dt.date) -> dt.date:
    if calendar.is_session(value):
        return value
    return calendar.nyse().date_to_session(value, direction="next").date()


def _known_snapshot_session(value: dt.date) -> dt.date:
    if calendar.is_session(value):
        return value
    return calendar.nyse().date_to_session(value, direction="previous").date()


def _decimal_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be numeric or null")
    return str(value)


def _earnings_row_priority(row: Mapping[str, object]) -> tuple[object, ...]:
    completeness = sum(
        row.get(name) is not None
        for name in (
            "eps_actual",
            "eps_forecast",
            "revenue_actual",
            "revenue_forecast",
        )
    )
    return (
        row.get("earning_date_type") == "OFFICIAL",
        row.get("fiscal_quarter") is not None,
        completeness,
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )


def normalize_earnings_inputs(
    *,
    securities: Sequence[Mapping[str, object]],
    instruments: Sequence[Mapping[str, object]],
    earnings_by_instrument: Mapping[int, Sequence[Mapping[str, object]]],
    raw_sha256: str,
    retrieved_at: str,
    snapshot_date: dt.date,
    coverage_start: dt.date,
    coverage_end_exclusive: dt.date,
) -> dict[str, object]:
    """Normalize historical results and current schedules without hindsight."""
    if not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
        _fail("Investing.com raw_sha256 must be lowercase SHA-256")
    if coverage_start >= coverage_end_exclusive:
        _fail("earnings coverage must be non-empty")
    permanent_by_symbol: dict[str, str] = {}
    for row in securities:
        symbol = _text(row.get("symbol"), "security symbol").upper()
        permanent_by_symbol[symbol] = _text(
            row.get("permanent_id"),
            f"{symbol} permanent_id",
        )
    instrument_by_id: dict[int, Mapping[str, object]] = {}
    if len(instruments) != len(permanent_by_symbol):
        _fail("Investing.com instruments must exactly cover the security master")
    for row in instruments:
        instrument_id = row.get("investing_instrument_id")
        symbol = _text(row.get("symbol"), "instrument symbol").upper()
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or symbol not in permanent_by_symbol
            or instrument_id in instrument_by_id
        ):
            _fail("Investing.com instrument mapping is incomplete or duplicated")
        instrument_by_id[instrument_id] = row
    known_snapshot = _known_snapshot_session(snapshot_date)
    events: list[dict[str, object]] = []
    seen: set[tuple[str, dt.date]] = set()
    for instrument_id, rows in earnings_by_instrument.items():
        instrument = instrument_by_id.get(instrument_id)
        if instrument is None:
            _fail("earnings response references an unmapped Investing.com instrument")
        symbol = _text(instrument.get("symbol"), "instrument symbol").upper()
        permanent_id = permanent_by_symbol[symbol]
        grouped: dict[dt.date, list[Mapping[str, object]]] = {}
        for raw in rows:
            if not isinstance(raw, Mapping) or raw.get("instrument_id") != instrument_id:
                _fail(f"earnings rows for {symbol} have an invalid instrument binding")
            calendar_date = _date(raw.get("date"), f"{symbol} earnings date")
            earnings_session = _completed_or_next_session(calendar_date)
            grouped.setdefault(earnings_session, []).append(raw)
        for earnings_session, provider_rows in grouped.items():
            raw = max(provider_rows, key=_earnings_row_priority)
            calendar_date = _date(raw.get("date"), f"{symbol} earnings date")
            if not (coverage_start <= earnings_session < coverage_end_exclusive):
                continue
            historical = calendar_date <= snapshot_date and (
                raw.get("eps_actual") is not None
                or raw.get("revenue_actual") is not None
            )
            known_session = earnings_session if historical else known_snapshot
            if known_session > earnings_session:
                _fail(f"{symbol} schedule was first observed after its event")
            key = (permanent_id, earnings_session)
            if key in seen:
                _fail(f"duplicate normalized earnings session for {symbol}")
            seen.add(key)
            events.append(
                {
                    "permanent_id": permanent_id,
                    "symbol": symbol,
                    "investing_instrument_id": instrument_id,
                    "calendar_date": calendar_date.isoformat(),
                    "earnings_session": earnings_session.isoformat(),
                    "known_session": known_session.isoformat(),
                    "superseded_session": None,
                    "knowledge_kind": (
                        "historical_result"
                        if historical
                        else "scheduled_snapshot"
                    ),
                    "provider_row_count": len(provider_rows),
                    "provider_selection": "official_then_fiscal_quarter_then_completeness",
                    "date_type": _optional_text(
                        raw.get("earning_date_type"),
                        f"{symbol} earning_date_type",
                    ),
                    "market_phase": _optional_text(
                        raw.get("market_phase"),
                        f"{symbol} market_phase",
                    ),
                    "eps_actual": _decimal_text(
                        raw.get("eps_actual"),
                        f"{symbol} eps_actual",
                    ),
                    "eps_forecast": _decimal_text(
                        raw.get("eps_forecast"),
                        f"{symbol} eps_forecast",
                    ),
                    "revenue_actual": _decimal_text(
                        raw.get("revenue_actual"),
                        f"{symbol} revenue_actual",
                    ),
                    "revenue_forecast": _decimal_text(
                        raw.get("revenue_forecast"),
                        f"{symbol} revenue_forecast",
                    ),
                }
            )
    coverage = [
        {
            "permanent_id": permanent_id,
            "coverage_start": coverage_start.isoformat(),
            "coverage_end_exclusive": coverage_end_exclusive.isoformat(),
        }
        for permanent_id in sorted(permanent_by_symbol.values())
    ]
    return {
        "schema_version": "swing-ranking-v1.earnings-calendar.v1",
        "source": {
            "provider": "Investing.com earnings calendar",
            "calendar_url": INVESTING_CALENDAR_URL,
            "earnings_api": f"{INVESTING_EARNINGS_URL}/v1/instruments/{{id}}/earnings",
            "retrieved_at": _text(retrieved_at, "retrieved_at"),
            "snapshot_date": snapshot_date.isoformat(),
            "raw_sha256": raw_sha256,
        },
        "coverage": coverage,
        "events": sorted(
            events,
            key=lambda row: (
                row["permanent_id"],
                row["earnings_session"],
            ),
        ),
    }


def merge_earnings_snapshots(
    documents: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Merge daily normalized snapshots into causal schedule-validity intervals."""
    snapshots = tuple(documents)
    if not snapshots:
        _fail("at least one earnings snapshot is required")
    ordered = sorted(
        snapshots,
        key=lambda value: _date(
            value.get("source", {}).get("snapshot_date")
            if isinstance(value.get("source"), Mapping)
            else None,
            "earnings snapshot_date",
        ),
    )
    historical: dict[tuple[str, str], dict[str, object]] = {}
    active: dict[str, dict[str, dict[str, object]]] = {}
    intervals: list[dict[str, object]] = []
    source_snapshots: list[dict[str, object]] = []
    coverage_by_id: dict[str, tuple[dt.date, dt.date]] = {}
    for document in ordered:
        source = document.get("source")
        events = document.get("events")
        coverage = document.get("coverage")
        if (
            not isinstance(source, Mapping)
            or not isinstance(events, list)
            or not isinstance(coverage, list)
        ):
            _fail("earnings snapshot has an invalid normalized schema")
        snapshot_date = _date(source.get("snapshot_date"), "snapshot_date")
        snapshot_session = _known_snapshot_session(snapshot_date)
        source_snapshots.append(
            {
                "snapshot_date": snapshot_date.isoformat(),
                "raw_sha256": _text(
                    source.get("raw_sha256"),
                    "snapshot raw_sha256",
                ),
            }
        )
        for raw in coverage:
            if not isinstance(raw, Mapping):
                _fail("earnings snapshot coverage must contain objects")
            permanent_id = _text(
                raw.get("permanent_id"),
                "coverage permanent_id",
            )
            start = _date(raw.get("coverage_start"), "coverage_start")
            end = _date(raw.get("coverage_end_exclusive"), "coverage_end_exclusive")
            prior = coverage_by_id.get(permanent_id)
            coverage_by_id[permanent_id] = (
                min(start, prior[0]) if prior else start,
                max(end, prior[1]) if prior else end,
            )
        scheduled_now: dict[str, dict[str, dict[str, object]]] = {}
        for raw in events:
            if not isinstance(raw, Mapping):
                _fail("earnings snapshot events must contain objects")
            event = dict(raw)
            permanent_id = _text(
                event.get("permanent_id"),
                "event permanent_id",
            )
            earnings_session = _text(
                event.get("earnings_session"),
                "event earnings_session",
            )
            kind = event.get("knowledge_kind")
            if kind == "historical_result":
                historical[(permanent_id, earnings_session)] = event
            elif kind == "scheduled_snapshot":
                scheduled_now.setdefault(permanent_id, {})[earnings_session] = event
            else:
                _fail("earnings event has an unknown knowledge_kind")
        all_ids = set(active) | set(scheduled_now)
        for permanent_id in all_ids:
            previous = active.setdefault(permanent_id, {})
            current = scheduled_now.get(permanent_id, {})
            for earnings_session in set(previous) - set(current):
                event_date = _date(earnings_session, "active earnings_session")
                if event_date >= snapshot_session:
                    ended = dict(previous.pop(earnings_session))
                    ended["superseded_session"] = snapshot_session.isoformat()
                    intervals.append(ended)
            for earnings_session, event in current.items():
                if earnings_session not in previous:
                    previous[earnings_session] = event
    intervals.extend(
        event
        for per_security in active.values()
        for event in per_security.values()
    )
    intervals.extend(historical.values())
    coverage = [
        {
            "permanent_id": permanent_id,
            "coverage_start": start.isoformat(),
            "coverage_end_exclusive": end.isoformat(),
        }
        for permanent_id, (start, end) in sorted(coverage_by_id.items())
    ]
    return {
        "schema_version": "swing-ranking-v1.earnings-calendar.v1",
        "source": {
            "provider": "Investing.com earnings calendar",
            "snapshot_count": len(source_snapshots),
            "snapshots": source_snapshots,
        },
        "coverage": coverage,
        "events": sorted(
            intervals,
            key=lambda row: (
                row["permanent_id"],
                row["earnings_session"],
                row["known_session"],
            ),
        ),
    }


__all__ = [
    "SourceInputViolation",
    "atomic_write",
    "fetch_openfigi_mappings",
    "investing_access_token",
    "investing_search_query",
    "json_bytes",
    "merge_earnings_snapshots",
    "normalize_earnings_inputs",
    "normalize_security_inputs",
    "openfigi_jobs",
    "roster_symbols",
    "select_investing_instrument",
    "select_openfigi_security",
    "sha256_bytes",
    "sha256_file",
]
