"""Catalyst calendar: known binary events (earnings, lawsuits, FDA decisions)
that a daily-bar stop cannot manage — a 30% stop fills *through* a gap, it
never prevents one. This module is the read side only: a `CatalystCalendar`
loaded from two sources, and a session-horizon predicate the trading engines
(backtest + forward) call to decide entry embargoes and pre-event exits.

Two data sources, merged:
- `cache/catalysts/earnings.json` — auto-fetched via `refresh_earnings`
  (yfinance), atomic writes (temp file + fsync + os.replace + dir fsync,
  same discipline as `stm.forward._atomic_write_json` — copied locally here
  rather than imported, per spec).
- `catalysts.yaml` — human-curated (lawsuits, FDA, ...), analogous to
  universe.yaml's seeds: code never writes it, only a human edits it.

Fail-open throughout: missing/corrupt files, unknown symbols, or dates
outside the calendar's bounds all resolve to "no catalyst" rather than
raising or blocking. The guard is protection, not a gate — a broken or
stale calendar must never itself halt trading.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from sts.calendar import nyse, sessions_between

logger = logging.getLogger(__name__)

EARNINGS_PATH = Path("cache/catalysts/earnings.json")
CURATED_PATH = Path("catalysts.yaml")

_VALID_TYPES = {"earnings", "lawsuit", "fda", "other"}
_ACTION_MAP = {
    "block_entry": frozenset({"block_entry"}),
    "exit_before": frozenset({"exit_before"}),
    "both": frozenset({"block_entry", "exit_before"}),
}


@dataclass(frozen=True)
class CatalystEvent:
    symbol: str
    date: dt.date  # best-known event date (may be an estimate)
    type: str  # "earnings" | "lawsuit" | "fda" | "other"
    source: str  # "earnings" (auto) | "curated"
    note: str = ""
    actions: frozenset = field(default_factory=lambda: frozenset({"block_entry", "exit_before"}))


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Same discipline as stm.forward._atomic_write_json: temp file in the
    same directory, fsync, os.replace, fsync the directory. A crash never
    corrupts prior good data. Kept as a local copy per spec (no cross-import)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload, indent=2, default=str))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@lru_cache(maxsize=1)
def _calendar_bounds() -> tuple[dt.date, dt.date]:
    cal = nyse()
    return cal.first_session.date(), cal.last_session.date()


@lru_cache(maxsize=4096)
def _effective_session(event_date: dt.date) -> dt.date | None:
    """First XNYS session on or after event_date. None if out of calendar bounds."""
    lo, hi = _calendar_bounds()
    if event_date < lo or event_date > hi:
        return None
    cal = nyse()
    session = cal.date_to_session(pd.Timestamp(event_date), direction="next")
    return session.date()


@lru_cache(maxsize=8192)
def _session_distance(query_date: dt.date, effective_date: dt.date) -> int:
    """Number of XNYS sessions s with query_date < s <= effective_date. 0 when
    effective_date == query_date. query_date need not itself be a session."""
    if effective_date < query_date:
        return -1  # past event relative to query; caller filters this out
    sessions = sessions_between(query_date, effective_date)
    # sessions_between includes query_date's session if query_date is itself a
    # session; we want strictly-after, so drop it when present.
    count = len(sessions)
    if len(sessions) and sessions[0].date() == query_date:
        count -= 1
    return count


class CatalystCalendar:
    def __init__(self, events: list[CatalystEvent], fetched_at: str | None = None):
        self.events = list(events)
        self.fetched_at = fetched_at
        # Precompute per-symbol sorted (by effective session) event lists so
        # catalyst_within doesn't rescan the full event list per call — this
        # runs per candidate-fill and per open position per session across
        # years of backtest history.
        by_symbol: dict[str, list[tuple[dt.date, CatalystEvent]]] = {}
        for ev in self.events:
            eff = _effective_session(ev.date)
            if eff is None:
                logger.warning(
                    "catalyst: %s event on %s is outside calendar bounds, skipping", ev.symbol, ev.date
                )
                continue
            by_symbol.setdefault(ev.symbol, []).append((eff, ev))
        for sym in by_symbol:
            by_symbol[sym].sort(key=lambda t: t[0])
        self._by_symbol = by_symbol

    @classmethod
    def load(
        cls, earnings_path: Path = EARNINGS_PATH, curated_path: Path = CURATED_PATH
    ) -> "CatalystCalendar":
        events: list[CatalystEvent] = []
        fetched_at: str | None = None

        earnings_path = Path(earnings_path)
        if earnings_path.exists():
            try:
                raw = json.loads(earnings_path.read_text())
                fetched_at = raw.get("fetched_at")
                for symbol, entry in raw.get("symbols", {}).items():
                    for d in entry.get("dates", []):
                        try:
                            events.append(
                                CatalystEvent(
                                    symbol=symbol.upper(),
                                    date=dt.date.fromisoformat(d),
                                    type="earnings",
                                    source="earnings",
                                )
                            )
                        except ValueError:
                            logger.warning("catalyst: bad earnings date %r for %s, skipping", d, symbol)
            except (json.JSONDecodeError, OSError, AttributeError) as e:
                logger.warning("catalyst: failed to load %s: %s (continuing without it)", earnings_path, e)
        else:
            logger.info("catalyst: %s not found, no auto-fetched earnings loaded", earnings_path)

        curated_path = Path(curated_path)
        if curated_path.exists():
            try:
                raw = yaml.safe_load(curated_path.read_text()) or {}
                for entry in raw.get("events", []) or []:
                    try:
                        symbol = str(entry["symbol"]).upper()
                        date = dt.date.fromisoformat(str(entry["date"]))
                        etype = entry.get("type", "other")
                        if etype not in _VALID_TYPES:
                            logger.warning(
                                "catalyst: unknown type %r for %s curated event, using 'other'",
                                etype, symbol,
                            )
                            etype = "other"
                        action = entry.get("action", "both")
                        actions = _ACTION_MAP.get(action)
                        if actions is None:
                            logger.warning(
                                "catalyst: unknown action %r for %s curated event, using 'both'",
                                action, symbol,
                            )
                            actions = _ACTION_MAP["both"]
                        events.append(
                            CatalystEvent(
                                symbol=symbol,
                                date=date,
                                type=etype,
                                source="curated",
                                note=str(entry.get("note", "")),
                                actions=actions,
                            )
                        )
                    except (KeyError, ValueError, TypeError) as e:
                        logger.warning("catalyst: malformed curated event %r: %s, skipping", entry, e)
            except (yaml.YAMLError, OSError) as e:
                logger.warning("catalyst: failed to load %s: %s (continuing without it)", curated_path, e)
        else:
            logger.info("catalyst: %s not found, no curated events loaded", curated_path)

        return cls(events, fetched_at=fetched_at)

    def catalyst_within(
        self, symbol: str, date: dt.date, horizon_sessions: int, action: str
    ) -> CatalystEvent | None:
        candidates = self._by_symbol.get(symbol)
        if not candidates:
            return None
        best: tuple[dt.date, CatalystEvent] | None = None
        for eff, ev in candidates:
            if action not in ev.actions:
                continue
            if eff < date:
                continue  # past events never match
            distance = _session_distance(date, eff)
            if distance < 0 or distance > horizon_sessions:
                continue
            if best is None or eff < best[0]:
                best = (eff, ev)
        return best[1] if best is not None else None

    def coverage(self, symbols: list[str]) -> dict:
        today = dt.date.today()
        with_events = 0
        with_upcoming = 0
        for sym in symbols:
            candidates = self._by_symbol.get(sym)
            if not candidates:
                continue
            with_events += 1
            if any(eff >= today for eff, _ in candidates):
                with_upcoming += 1
        return {
            "total": len(symbols),
            "with_events": with_events,
            "with_upcoming": with_upcoming,
            "earnings_fetched_at": self.fetched_at,
        }


def refresh_earnings(
    symbols: list[str], path: Path = EARNINGS_PATH, per_symbol_limit: int = 12
) -> dict:
    """Fetch upcoming/recent earnings dates per symbol via yfinance and merge
    into `path`, atomically. Never raises: per-symbol failures are recorded
    and keep the symbol's previously known dates rather than wiping them."""
    import yfinance as yf  # lazy: avoid import cost/side effects when unused

    from sts.calendar import NY

    path = Path(path)
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("catalyst: existing %s unreadable (%s), starting fresh", path, e)
            existing = {}
    existing_symbols: dict = dict(existing.get("symbols", {}))

    t0 = time.monotonic()
    result_symbols: dict = dict(existing_symbols)
    ok = 0
    failed = 0
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    for i, sym in enumerate(symbols, 1):
        elapsed = time.monotonic() - t0
        eta = (elapsed / i) * (len(symbols) - i) if i else 0.0
        print(f"[{i}/{len(symbols)}] {sym} (elapsed {elapsed:.0f}s, eta {eta:.0f}s)")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = yf.Ticker(sym).get_earnings_dates(limit=per_symbol_limit)
            dates: list[str] = []
            if df is not None and not df.empty:
                for ts in df.index:
                    if ts.tzinfo is not None:
                        ts = ts.tz_convert(NY)
                    dates.append(ts.date().isoformat())
            dates = sorted(set(dates))
            result_symbols[sym] = {"dates": dates, "fetched_at": now_iso, "error": None}
            ok += 1
        except Exception as e:
            logger.warning("catalyst: earnings fetch failed for %s: %s", sym, e)
            prev = existing_symbols.get(sym, {})
            result_symbols[sym] = {
                "dates": list(prev.get("dates", [])),
                "fetched_at": prev.get("fetched_at"),
                "error": str(e),
            }
            failed += 1

    elapsed_total = time.monotonic() - t0
    payload = {"fetched_at": now_iso, "symbols": result_symbols}
    _atomic_write_json(path, payload)

    print(f"catalyst refresh_earnings: {ok} ok, {failed} failed, {elapsed_total:.1f}s -> {path}")
    return {"ok": ok, "failed": failed, "elapsed_s": elapsed_total, "path": str(path)}
