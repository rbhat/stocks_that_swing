"""Per-symbol data quality checks. Nothing feeds signals until it passes.

A symbol with `errors` is quarantined (excluded from signals) for the day;
`warnings` are logged but don't block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sts import calendar

# A close-to-close move beyond this is flagged for review (fat-finger bars,
# bad splits). Real moves this size exist, so it's a warning, not an error.
EXTREME_MOVE = 0.50
# Recent sessions may legitimately lag (fresh listing is handled separately);
# more than this many missing sessions inside the series is a data hole.
MAX_MISSING_SESSIONS = 0


@dataclass
class QualityReport:
    symbol: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check(symbol: str, df: pd.DataFrame) -> QualityReport:
    r = QualityReport(symbol)
    if df is None or df.empty:
        r.errors.append("no data")
        return r

    ohlc = df[["open", "high", "low", "close"]]
    if ohlc.isna().any().any() or df["volume"].isna().any():
        r.errors.append(f"NaN values on {int(df.isna().any(axis=1).sum())} bar(s)")
    if (ohlc <= 0).any().any():
        r.errors.append("non-positive price(s)")
    if (df["volume"] < 0).any():
        r.errors.append("negative volume")

    bad_range = (df["high"] < df["low"]) | (df["high"] < ohlc.max(axis=1) - 1e-9) | (
        df["low"] > ohlc.min(axis=1) + 1e-9
    )
    if bad_range.any():
        r.errors.append(f"inconsistent OHLC range on {int(bad_range.sum())} bar(s)")

    unsorted = not df.index.is_monotonic_increasing
    if unsorted:
        r.errors.append("index not sorted")
    duplicated = df.index.duplicated().any()
    if duplicated:
        r.errors.append("duplicate dates")
    if unsorted or duplicated:
        # A malformed index makes the calendar/missing-session and move math
        # below meaningless (and can silently no-op when start > end).
        return r

    expected = calendar.sessions_between(df.index[0].date(), df.index[-1].date())
    missing = expected.difference(df.index)
    if len(missing) > MAX_MISSING_SESSIONS:
        r.errors.append(f"{len(missing)} missing session(s), e.g. {missing[0].date()}")

    moves = df["close"].pct_change().abs()
    extreme = moves[moves > EXTREME_MOVE]
    if not extreme.empty:
        r.warnings.append(
            f"{len(extreme)} extreme move(s) >{EXTREME_MOVE:.0%}, e.g. {extreme.index[0].date()} ({extreme.iloc[0]:.0%})"
        )
    if (df["volume"] == 0).any():
        r.warnings.append(f"{int((df['volume'] == 0).sum())} zero-volume bar(s)")
    return r
