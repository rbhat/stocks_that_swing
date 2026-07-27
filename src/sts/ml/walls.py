"""Strict date walls and explicit exchange-session arithmetic.

Callers must provide the ordered exchange sessions they are authorized to
use. No calendar, filesystem, cache, or network fallback is hidden here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from itertools import pairwise

from sts.ml.contracts import ContractViolation, require_date

DEVELOPMENT_START_INCLUSIVE = dt.date(2010, 1, 1)
DEVELOPMENT_END_EXCLUSIVE = dt.date(2024, 1, 1)
QUARANTINE_END_EXCLUSIVE = dt.date(2026, 7, 27)
CLEAN_EVIDENCE_LOWER_BOUND = dt.date(2026, 7, 27)


class WallViolation(ContractViolation):
    """A row or requested session crossed a locked evidence wall."""


def require_development_session(value: dt.date) -> dt.date:
    day = require_date(value, "development session")
    if day < DEVELOPMENT_START_INCLUSIVE:
        raise WallViolation(
            f"{day} is before development start {DEVELOPMENT_START_INCLUSIVE}"
        )
    if day >= DEVELOPMENT_END_EXCLUSIVE:
        raise WallViolation(
            f"{day} is on or after development end {DEVELOPMENT_END_EXCLUSIVE}"
        )
    return day


def require_fresh_session(
    value: dt.date,
    *,
    actual_event_wall: dt.date | None,
) -> dt.date:
    """Require a row to be on/after an already locked prospective wall."""
    day = require_date(value, "fresh session")
    if actual_event_wall is None:
        raise WallViolation("actual event wall is not locked")
    wall = require_date(actual_event_wall, "actual_event_wall")
    if wall < CLEAN_EVIDENCE_LOWER_BOUND:
        raise WallViolation(
            "actual event wall is before the clean evidence lower bound "
            f"{CLEAN_EVIDENCE_LOWER_BOUND}"
        )
    if day < wall:
        raise WallViolation(f"{day} is before actual event wall {wall}")
    return day


@dataclass(frozen=True)
class SessionSequence:
    """An explicit, strictly ordered sequence of exchange sessions."""

    sessions: tuple[dt.date, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            require_date(value, f"sessions[{index}]")
            for index, value in enumerate(self.sessions)
        )
        if any(left >= right for left, right in pairwise(normalized)):
            raise WallViolation("supplied sessions must be strictly increasing")
        object.__setattr__(self, "sessions", normalized)

    def _index(self, session: dt.date) -> int:
        day = require_date(session, "session")
        try:
            return self.sessions.index(day)
        except ValueError as exc:
            raise WallViolation(f"{day} is not in supplied sessions") from exc

    def offset(self, session: dt.date, offset: int) -> dt.date:
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise WallViolation("session offset must be an integer")
        start = self._index(session)
        target = start + offset
        if target < 0 or target >= len(self.sessions):
            raise WallViolation(
                f"incomplete session path from {session} at offset {offset}"
            )
        return self.sessions[target]

    def distance(self, start: dt.date, end: dt.date) -> int:
        return self._index(end) - self._index(start)

    def window_after(self, session: dt.date, count: int) -> tuple[dt.date, ...]:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise WallViolation("session count must be a non-negative integer")
        start = self._index(session) + 1
        end = start + count
        if end > len(self.sessions):
            raise WallViolation(
                f"incomplete session path after {session}: need {count} sessions"
            )
        return self.sessions[start:end]
