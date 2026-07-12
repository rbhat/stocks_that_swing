import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from sts import calendar

NY = ZoneInfo("America/New_York")


def test_half_day_before_early_close_falls_back_to_prior_session():
    # 2025-11-28 is a half-day (13:00 ET close); Thanksgiving (11-27) is closed,
    # so before the early close the last completed session is Wed 11-26.
    now = dt.datetime(2025, 11, 28, 12, 0, tzinfo=NY)
    assert calendar.last_completed_session(now) == dt.date(2025, 11, 26)


def test_half_day_after_early_close_counts_same_day():
    now = dt.datetime(2025, 11, 28, 13, 5, tzinfo=NY)
    assert calendar.last_completed_session(now) == dt.date(2025, 11, 28)


def test_naive_datetime_raises():
    with pytest.raises(ValueError):
        calendar.last_completed_session(dt.datetime(2025, 11, 28, 12, 0))
