"""NYSE trading calendar helpers. All times New York; holidays and half-days respected."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def nyse():
    # default bounds are only ~20y back; full histories reach the 1960s+
    return xcals.get_calendar("XNYS", start="1960-01-01")


def sessions_between(start: dt.date, end: dt.date) -> pd.DatetimeIndex:
    """All trading sessions in [start, end], as tz-naive dates."""
    return nyse().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))


def is_session(day: dt.date) -> bool:
    return nyse().is_session(pd.Timestamp(day))


def last_completed_session(now: dt.datetime | None = None) -> dt.date:
    """Most recent session whose close has passed (NY time).

    Half-days close early; exchange_calendars knows the real close.
    """
    if now is not None and now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(NY) if now else dt.datetime.now(NY)
    cal = nyse()
    session = cal.date_to_session(pd.Timestamp(now.date()), direction="previous")
    while True:
        close = cal.session_close(session).tz_convert(NY)
        if close <= now:
            return session.date()
        session = cal.previous_session(session)
