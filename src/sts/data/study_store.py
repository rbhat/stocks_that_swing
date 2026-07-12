"""Study store: cache/study_frames/{SYMBOL}.parquet — wide-roster evidence data.

Feeds ONLY stm.validate's signal-level (layer 1) evidence: a wide cross-
section of symbols (configs/study_roster.yaml), backtested at the event
level. These symbols are never traded and never mixed into cache/ohlcv/ (the
source-of-truth price store, see stm.data.store.PriceStore) or the live
universe. Frames share PriceStore's shape — OHLCV daily bars, a DatetimeIndex,
split- and dividend-adjusted total-return prices from stm.data.fetch —
so study and traded symbols can be pooled in one evaluation without mixing
adjustment bases.

Deliberately NOT PriceStore, despite mirroring its atomic-write and
validate-before-write discipline: this store is read-only for signal
evaluation, so it has none of PriceStore's overlap-revision detection or
full-history rebuild machinery. A re-fetched frame here just overwrites the
old one once it clears the quality gate — evidence data, not the trade-facing
source of truth.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from sts import calendar
from sts.data import quality

logger = logging.getLogger(__name__)

DEFAULT_ROOT = Path("cache/study_frames")


def _truncate_incomplete(df: pd.DataFrame) -> pd.DataFrame:
    """Drop any bar dated after the last completed session — a partial bar
    is never cached as if it were final (same rule as PriceStore)."""
    last_ok = calendar.last_completed_session()
    return df[df.index.date <= last_ok]


class StudyStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, symbol: str) -> Path:
        return self.root / f"{symbol.upper()}.parquet"

    def symbols(self) -> list[str]:
        """Sorted symbols with a parquet file present."""
        return sorted(p.stem for p in self.root.glob("*.parquet"))

    def load(self, symbol: str) -> pd.DataFrame | None:
        """The cached frame for `symbol`, or None if absent or unreadable."""
        p = self.path(symbol)
        if not p.exists():
            return None
        try:
            return pd.read_parquet(p)
        except Exception:
            logger.warning("unreadable study frame for %s at %s", symbol, p, exc_info=True)
            return None

    def load_all(self) -> dict[str, pd.DataFrame]:
        """Every readable frame, keyed by symbol; unreadable ones are
        skipped (and logged by `load`)."""
        frames: dict[str, pd.DataFrame] = {}
        for sym in self.symbols():
            df = self.load(sym)
            if df is not None:
                frames[sym] = df
        return frames

    def last_date(self, symbol: str) -> dt.date | None:
        df = self.load(symbol)
        return df.index[-1].date() if df is not None and not df.empty else None

    def write(self, symbol: str, df: pd.DataFrame) -> None:
        """Truncate incomplete bars, gate through quality, then atomic-write.

        Raises ValueError (message = the quality report's errors) if `df`
        fails stm.data.quality.check; any existing file is left untouched.
        """
        truncated = _truncate_incomplete(df)
        report = quality.check(symbol, truncated)
        if not report.ok:
            raise ValueError(f"{symbol}: {'; '.join(report.errors)}")
        self._atomic_write(symbol, truncated)

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
