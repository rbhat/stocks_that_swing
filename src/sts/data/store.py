"""Canonical local price store: cache/ohlcv/{SYMBOL}.parquet.

Invariants (tested):
- Atomic writes: a crash mid-write never corrupts an existing file
  (write to temp in same directory, fsync, os.replace, fsync directory).
- Idempotent updates: running the daily update twice changes nothing.
- The local cache is the source of truth for prices; Drive only mirrors it.
- Nothing is written unless it passes `validate`; existing good data is
  untouched by a rejected candidate.
- Upstream bar revisions (the overlap bar disagreeing with the cache on a
  re-fetch) are permanently logged to cache/ohlcv/revisions.jsonl, append
  -only, best-effort (a logging failure never breaks the price update).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from sts import calendar

logger = logging.getLogger(__name__)

DEFAULT_ROOT = Path("cache/ohlcv")

REVISIONS_FILENAME = "revisions.jsonl"

TMP_SWEEP_AGE = 3600  # seconds; stray temp files older than this are stale


class PriceStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sweep_stale_tmp()

    def _sweep_stale_tmp(self) -> None:
        """Delete leftover *.parquet.tmp files from a killed process."""
        cutoff = time.time() - TMP_SWEEP_AGE
        for p in self.root.glob("*.parquet.tmp"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass

    def path(self, symbol: str) -> Path:
        return self.root / f"{symbol.upper()}.parquet"

    def load(self, symbol: str) -> pd.DataFrame | None:
        p = self.path(symbol)
        return pd.read_parquet(p) if p.exists() else None

    def last_date(self, symbol: str) -> dt.date | None:
        df = self.load(symbol)
        return df.index[-1].date() if df is not None and not df.empty else None

    def is_current(self, symbol: str, now: dt.datetime | None = None) -> bool:
        last = self.last_date(symbol)
        return last is not None and last >= calendar.last_completed_session(now)

    def _atomic_write(self, symbol: str, df: pd.DataFrame) -> None:
        target = self.path(symbol)
        fd, tmp = tempfile.mkstemp(suffix=".parquet.tmp", dir=self.root)
        os.close(fd)
        try:
            df.to_parquet(tmp)
            # Force the bytes to disk before the rename is visible, and force
            # the rename itself to disk, so a power loss can't reorder them.
            fd = os.open(tmp, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, target)
            dir_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _row_dict(row: pd.Series) -> dict[str, float | int]:
        return {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        }

    @staticmethod
    def _overlap_row_differs(old_row: pd.Series, new_row: pd.Series) -> bool:
        for col in ("open", "high", "low", "close"):
            old_v = float(old_row[col])
            new_v = float(new_row[col])
            denom = abs(old_v) if old_v != 0 else 1.0
            if abs(new_v - old_v) / denom > 1e-6:
                return True
        return int(old_row["volume"]) != int(new_row["volume"])

    def _log_revision(
        self,
        symbol: str,
        session: Any,
        old_row: pd.Series | None,
        new_row: pd.Series | None,
        action: str,
        close_rel_diff: float | None = None,
    ) -> None:
        """Best-effort append of one revision record. Never raises — a
        logging failure must never abort the price update itself."""
        try:
            record = {
                "symbol": symbol,
                "session": pd.Timestamp(session).date().isoformat(),
                "old": self._row_dict(old_row) if old_row is not None else None,
                "new": self._row_dict(new_row) if new_row is not None else None,
                "close_rel_diff": close_rel_diff,
                "action": action,
                "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            line = json.dumps(record, separators=(",", ":")) + "\n"
            path = self.root / REVISIONS_FILENAME
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            logger.warning(
                "failed to log price revision for %s @ %s", symbol, session, exc_info=True
            )

    def _truncate_incomplete(self, df: pd.DataFrame, now: dt.datetime | None) -> pd.DataFrame:
        """Drop any bar dated after the last completed session — a partial
        intraday bar must never be cached as if it were final."""
        last_ok = calendar.last_completed_session(now)
        return df[df.index.date <= last_ok]

    def rebuild(
        self,
        symbol: str,
        fetch: Callable[[str, dt.date | None], pd.DataFrame],
        validate: Callable[[str, pd.DataFrame], Any] | None = None,
        now: dt.datetime | None = None,
    ) -> str:
        """Full refetch of `symbol`, truncated to completed sessions and
        validated before writing. Returns "rebuilt" or "rejected: ...".
        """
        fresh = self._truncate_incomplete(fetch(symbol, None), now)
        if validate is not None:
            report = validate(symbol, fresh)
            if not report.ok:
                return f"rejected: {'; '.join(report.errors)}"
        self._atomic_write(symbol, fresh)
        return "rebuilt"

    def update(
        self,
        symbol: str,
        fetch: Callable[[str, dt.date | None], pd.DataFrame],
        now: dt.datetime | None = None,
        validate: Callable[[str, pd.DataFrame], Any] | None = None,
    ) -> str:
        """Gap-fill `symbol` up to the last completed session.

        Returns one of: "current" (nothing to do), "unchanged" (fetched but
        identical), "updated", "created", "rebuilt", or "rejected: ..." (a
        candidate frame failed `validate`; existing data, if any, is left
        untouched). Re-fetches from the last cached bar (inclusive) so a
        partial final bar gets corrected. If the fetch is missing the overlap
        bar, or the overlap bar disagrees with the cache (a split
        re-adjusted history), the whole series is refetched so the store
        stays consistently adjusted.
        """
        existing = self.load(symbol)
        if existing is not None and self.is_current(symbol, now):
            return "current"

        start = existing.index[-1].date() if existing is not None and not existing.empty else None
        fresh = self._truncate_incomplete(fetch(symbol, start), now)

        if existing is None or existing.empty:
            if validate is not None:
                report = validate(symbol, fresh)
                if not report.ok:
                    return f"rejected: {'; '.join(report.errors)}"
            self._atomic_write(symbol, fresh)
            return "created"

        overlap = existing.index[-1]
        if overlap not in fresh.index:
            # Can't confirm the cache still agrees with the source — rebuild.
            self._log_revision(symbol, overlap, existing.loc[overlap], None, "rebuilt")
            return self.rebuild(symbol, fetch, validate, now)

        old_row = existing.loc[overlap]
        new_row = fresh.loc[fresh.index == overlap].iloc[-1]
        old_close = float(old_row["close"])
        new_close = float(new_row["close"])
        close_rel_diff = abs(new_close - old_close) / (old_close if old_close != 0 else 1.0)
        rebuild_triggered = abs(new_close - old_close) > 0.001 * old_close

        if self._overlap_row_differs(old_row, new_row):
            action = "rebuilt" if rebuild_triggered else "absorbed"
            self._log_revision(symbol, overlap, old_row, new_row, action, close_rel_diff)

        if rebuild_triggered:
            return self.rebuild(symbol, fetch, validate, now)

        merged = pd.concat([existing, fresh])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        if merged.equals(existing):
            return "unchanged"
        if validate is not None:
            report = validate(symbol, merged)
            if not report.ok:
                return f"rejected: {'; '.join(report.errors)}"
        self._atomic_write(symbol, merged)
        return "updated"
