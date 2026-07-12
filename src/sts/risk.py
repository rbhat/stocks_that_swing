"""Swing-native risk engine.

Every number in this module comes from the ratified charter (VISION.md
"Charter rules", 2026-07-11) — risk is anchored to the instrument's own
volatility (ATR) and structure, never to a fixed percent designed for a
multi-year hold. Position size is risk-budget-divided-by-stop-distance, not
a fixed fraction of equity; this is the entire point of a swing-native
engine (see LESSONS.md §2 "geometry mismatch" for what happens when it
isn't).

Invariants held by this module:
- Long only. Every helper and `Position` assumes a stop below entry and
  (when set) a target above entry.
- Stops are fixed at entry and never widened — there is no trailing or
  breakeven-raise mechanic here. `Position.stop` does not change after
  construction.
- Never average down — there is no averaging mechanic anywhere in this
  module, so a position's size is fixed at open.
- Every stop is sanity-bounded to <= 12% of entry (`MAX_STOP_PCT`), enforced
  both in the stop helpers and as a hard invariant of `Position` itself, so
  there is no path to constructing an out-of-bound position.
- Targets carry no bound and no hard reward:risk floor — expectancy after
  friction is the governing criterion, not a fixed R:R (a fixed floor is the
  single biggest thing that broke swing sizing in the parent project).
- A hard 15-session time stop applies to every position, unconditionally.

Nothing here touches a portfolio, a calendar, or a broker — this module is
pure per-position sizing and exit arithmetic.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import pandas as pd

START_CAPITAL = 100_000.0
RISK_PER_TRADE_PCT = 0.0075       # 0.75% of equity risked per trade
MAX_POSITION_NOTIONAL_PCT = 0.15  # 15% per-position notional cap
MAX_POSITIONS = 8                 # max concurrent positions
MAX_DEPLOYED_PCT = 0.80           # max 80% of equity deployed
MAX_STOP_PCT = 0.12               # stop distance sanity bound: never >12% of entry
TIME_STOP_SESSIONS = 15           # hard time stop, not a tunable (LESSONS §8)
DEFAULT_ATR_WINDOW = 14


class RuleViolation(Exception):
    """A risk-engine invariant would be violated (e.g. an out-of-bound stop
    or a target that isn't above entry)."""


def atr(df: pd.DataFrame, window: int = DEFAULT_ATR_WINDOW) -> pd.Series:
    """Simple (non-Wilder-smoothed) average true range: a rolling mean of
    true range over `window` bars, `min_periods=window` so there is no
    partial-window leakage (NaN until fully warmed).

    True range = max(high-low, |high-prev_close|, |low-prev_close|), where
    prev_close = close.shift(1). The first row has no prev_close; using
    `pd.concat([...], axis=1).max(axis=1, skipna=True)` makes NaN columns
    drop out of that row's max instead of poisoning it, so the first row
    correctly reduces to high-low rather than NaN.

    This is a deliberate simplicity choice, not an oversight: Wilder's
    smoothed ATR is a reasonable alternative, but a plain rolling mean is
    easier to reason about and to hand-verify in tests, and this module
    doesn't need the smoother's extra persistence.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1, skipna=True)
    return tr.rolling(window, min_periods=window).mean()


def _bound_stop(entry: float, candidate: float) -> float:
    """Shared floor: a stop can be tighter than MAX_STOP_PCT below entry,
    never wider."""
    return max(candidate, entry * (1 - MAX_STOP_PCT))


def atr_stop(entry: float, atr_value: float, multiple: float = 2.0) -> float:
    """Stop = entry - multiple*ATR, bounded to <= MAX_STOP_PCT below entry."""
    if not (entry > 0):
        raise ValueError(f"entry must be positive, got {entry!r}")
    if not (math.isfinite(atr_value) and atr_value > 0):
        raise ValueError(f"atr_value must be positive and finite, got {atr_value!r}")
    if not (multiple > 0):
        raise ValueError(f"multiple must be positive, got {multiple!r}")
    candidate = entry - multiple * atr_value
    return _bound_stop(entry, candidate)


def structure_stop(entry: float, level: float) -> float:
    """Stop = a structure price below entry (e.g. pullback low / gap base),
    bounded to <= MAX_STOP_PCT below entry."""
    if not (entry > 0):
        raise ValueError(f"entry must be positive, got {entry!r}")
    if not (math.isfinite(level) and 0 < level < entry):
        raise ValueError(f"level must be finite and in (0, entry), got {level!r}")
    return _bound_stop(entry, level)


def atr_target(entry: float, atr_value: float, multiple: float = 2.0) -> float:
    """Target = entry + multiple*ATR. No bound — no hard R:R floor is a
    ratified charter principle."""
    if not (entry > 0):
        raise ValueError(f"entry must be positive, got {entry!r}")
    if not (math.isfinite(atr_value) and atr_value > 0):
        raise ValueError(f"atr_value must be positive and finite, got {atr_value!r}")
    if not (multiple > 0):
        raise ValueError(f"multiple must be positive, got {multiple!r}")
    return entry + multiple * atr_value


def structure_target(level: float) -> float:
    """Target = a structure price (e.g. prior swing high / measured move).
    Only validates `level` is finite and positive; the caller is responsible
    for it being above entry — `Position.__post_init__` enforces that as a
    hard invariant."""
    if not (math.isfinite(level) and level > 0):
        raise ValueError(f"level must be finite and positive, got {level!r}")
    return level


def r_multiple(entry: float, exit_price: float, initial_stop: float) -> float:
    """R multiple of an exit relative to the initial risk (entry - stop)."""
    return (exit_price - entry) / (entry - initial_stop)


def position_size(
    equity: float,
    entry: float,
    stop: float,
    deployed: float = 0.0,
    cash: float | None = None,
    open_positions: int = 0,
) -> int:
    """Pure sizing formula, no state: shares = floor of the binding minimum
    across four independent caps.

    This is the swing-native core: size is driven by risk-budget (0.75% of
    equity) divided by stop distance — not a fixed fraction of equity. A
    fixed-fraction sizing scheme (the parent project's approach) decouples
    size from how far the stop actually sits, which is exactly the
    "geometry mismatch" LESSONS §2 identifies as the parent's killer flaw:
    a wide fixed-% stop makes 1R practically unreachable at swing horizons.
    Here, size adapts so a real stop-out always costs ~RISK_PER_TRADE_PCT of
    equity, regardless of how tight or wide that particular stop is (subject
    to the 15% notional / 80% deployed / cash / position-count caps below).
    """
    if open_positions >= MAX_POSITIONS:
        return 0
    stop_distance = entry - stop
    if stop_distance <= 0:
        raise ValueError("stop must be below entry")
    if cash is None:
        cash = equity
    by_risk = (RISK_PER_TRADE_PCT * equity) / stop_distance
    by_notional = (MAX_POSITION_NOTIONAL_PCT * equity) / entry
    by_deployed = max(0.0, MAX_DEPLOYED_PCT * equity - deployed) / entry
    by_cash = cash / entry
    shares = math.floor(min(by_risk, by_notional, by_deployed, by_cash) + 1e-9)
    return max(0, shares)


@dataclass
class Position:
    """A single open (or resolved) swing position. `stop` is fixed at entry
    per charter — never widened, no trailing/breakeven mechanic."""

    symbol: str
    entry: float
    shares: int
    stop: float
    target: float | None
    opened: dt.date
    config: str
    bars_held: int = 0

    def __post_init__(self) -> None:
        if self.shares < 1:
            raise RuleViolation(f"shares must be >= 1, got {self.shares!r}")
        if self.stop >= self.entry:
            raise RuleViolation(
                f"stop ({self.stop!r}) must be below entry ({self.entry!r})"
            )
        if self.target is not None and self.target <= self.entry:
            raise RuleViolation(
                f"target ({self.target!r}) must be above entry ({self.entry!r})"
            )
        if (self.entry - self.stop) > MAX_STOP_PCT * self.entry + 1e-9:
            raise RuleViolation(
                f"stop distance {(self.entry - self.stop) / self.entry:.4f} "
                f"exceeds MAX_STOP_PCT ({MAX_STOP_PCT})"
            )


def manage_bar(
    pos: Position,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    bar_close: float,
) -> list[tuple[str, float, int]]:
    """Advance `pos` by one session/bar, mutating it in place. Returns an
    ordered list of `(reason, price, shares)` exits — at most one entry:
    this design has no partial-exit/runner mechanic, every exit is a full
    flatten.

    Priority, checked in order:
    1. bars_held += 1.
    2. Stop (conservative same-bar rule): if bar_low <= stop, exit ALL
       shares at min(stop, bar_open) — a gap below stop fills at the open.
       reason "stop_gap" if the bar opened below the stop, else "stop".
    3. Else target (if set) hit intrabar: exit ALL shares at
       max(target, bar_open), reason "target".
    4. Else hard time stop once bars_held >= TIME_STOP_SESSIONS: exit ALL
       shares at bar_close, reason "time". This is the charter's 15-session
       rule, baked into the engine unconditionally.
    5. Else no exit: return [].
    """
    pos.bars_held += 1

    if bar_low <= pos.stop:
        price = min(pos.stop, bar_open)
        reason = "stop_gap" if bar_open < pos.stop else "stop"
        shares = pos.shares
        pos.shares = 0
        return [(reason, price, shares)]

    if pos.target is not None and bar_high >= pos.target:
        price = max(pos.target, bar_open)
        shares = pos.shares
        pos.shares = 0
        return [("target", price, shares)]

    if pos.bars_held >= TIME_STOP_SESSIONS:
        shares = pos.shares
        pos.shares = 0
        return [("time", bar_close, shares)]

    return []
