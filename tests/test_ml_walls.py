import datetime as dt

import pytest

from sts.ml.walls import (
    CLEAN_EVIDENCE_LOWER_BOUND,
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_START_INCLUSIVE,
    SessionSequence,
    WallViolation,
    require_development_session,
    require_fresh_session,
)


def test_development_wall_is_strict_and_post_wall_canary_fails_closed():
    assert require_development_session(DEVELOPMENT_START_INCLUSIVE) == dt.date(
        2010, 1, 1
    )
    assert require_development_session(dt.date(2023, 12, 31)) == dt.date(
        2023, 12, 31
    )
    with pytest.raises(WallViolation, match="before development start"):
        require_development_session(dt.date(2009, 12, 31))
    with pytest.raises(WallViolation, match="development end"):
        require_development_session(DEVELOPMENT_END_EXCLUSIVE)
    with pytest.raises(WallViolation, match="development end"):
        require_development_session(dt.date(2026, 7, 27))


def test_fresh_wall_requires_a_locked_future_session():
    day = dt.date(2026, 8, 4)
    with pytest.raises(WallViolation, match="not locked"):
        require_fresh_session(day, actual_event_wall=None)
    with pytest.raises(WallViolation, match="clean evidence lower bound"):
        require_fresh_session(
            day,
            actual_event_wall=CLEAN_EVIDENCE_LOWER_BOUND - dt.timedelta(days=1),
        )
    with pytest.raises(WallViolation, match="before actual event wall"):
        require_fresh_session(
            CLEAN_EVIDENCE_LOWER_BOUND,
            actual_event_wall=day,
        )
    assert require_fresh_session(day, actual_event_wall=day) == day


def test_explicit_session_arithmetic_skips_non_sessions_and_checks_bounds():
    sessions = SessionSequence(
        (
            dt.date(2023, 12, 28),
            dt.date(2023, 12, 29),
            dt.date(2024, 1, 2),
            dt.date(2024, 1, 3),
        )
    )

    assert sessions.offset(dt.date(2023, 12, 29), 1) == dt.date(2024, 1, 2)
    assert sessions.distance(dt.date(2023, 12, 29), dt.date(2024, 1, 3)) == 2
    assert sessions.window_after(dt.date(2023, 12, 29), 2) == (
        dt.date(2024, 1, 2),
        dt.date(2024, 1, 3),
    )
    with pytest.raises(WallViolation, match="not in supplied sessions"):
        sessions.offset(dt.date(2023, 12, 30), 1)
    with pytest.raises(WallViolation, match="incomplete session path"):
        sessions.window_after(dt.date(2024, 1, 2), 2)


def test_session_sequence_rejects_unsorted_or_duplicate_inputs():
    with pytest.raises(WallViolation, match="strictly increasing"):
        SessionSequence((dt.date(2024, 1, 3), dt.date(2024, 1, 2)))
    with pytest.raises(WallViolation, match="strictly increasing"):
        SessionSequence((dt.date(2024, 1, 2), dt.date(2024, 1, 2)))
