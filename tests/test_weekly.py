import datetime as dt

import pandas as pd

from sts import calendar as cal
from sts.weekly import OHLCV_COLUMNS, WEEKLY_COLUMNS, align_to_daily, resample_weekly


def make_frame(rows: list[dict], start="2024-01-01") -> pd.DataFrame:
    """Business-day proxy frame, same convention as tests/test_signals.py's
    make_frame: lowercase OHLCV columns, tz-naive DatetimeIndex named "date".
    """
    idx = pd.bdate_range(start, periods=len(rows), name="date")
    return pd.DataFrame(rows, index=idx, columns=OHLCV_COLUMNS)


def flat_bar(o=100.0, h=101.0, l=99.0, c=100.0, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def three_full_weeks():
    # 2024-01-01 is a Monday -> 3 clean Mon-Fri weeks, Fridays 01-05, 01-12, 01-19.
    return [flat_bar(o=100 + i, h=101 + i, l=99 + i, c=100 + i, v=1000 + i) for i in range(15)]


# ---------------------------------------------------------------------------
# resample_weekly
# ---------------------------------------------------------------------------


def test_basic_aggregation_correctness():
    df = make_frame(three_full_weeks())
    out = resample_weekly(df)

    assert len(out) == 3
    assert list(out.index) == [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-12"), pd.Timestamp("2024-01-19")]

    # Week 1 = rows 0-4 (i=0..4).
    week1 = out.loc["2024-01-05"]
    assert week1["open"] == 100  # first bar's open (i=0)
    assert week1["high"] == 105  # max high (i=4 -> 101+4)
    assert week1["low"] == 99  # min low (i=0 -> 99+0)
    assert week1["close"] == 104  # last bar's close (i=4 -> 100+4)
    assert week1["volume"] == sum(1000 + i for i in range(5))

    # Week 3 = rows 10-14 (i=10..14).
    week3 = out.loc["2024-01-19"]
    assert week3["open"] == 110
    assert week3["high"] == 115
    assert week3["low"] == 109
    assert week3["close"] == 114
    assert week3["volume"] == sum(1000 + i for i in range(10, 15))


def test_trailing_partial_week_dropped_by_default():
    full = make_frame(three_full_weeks())
    truncated = full.iloc[:13]  # stop mid week-3, on Wednesday 2024-01-17
    assert truncated.index[-1] == pd.Timestamp("2024-01-17")

    out_full = resample_weekly(full)
    out_trunc = resample_weekly(truncated)  # drop_incomplete_trailing=True (default)

    assert len(out_trunc) == len(out_full) - 1
    # The two still-complete weeks are unaffected.
    pd.testing.assert_frame_equal(out_trunc, out_full.iloc[:2])


def test_drop_incomplete_trailing_false_keeps_partial_week():
    full = make_frame(three_full_weeks())
    truncated = full.iloc[:13]  # through Wednesday 2024-01-17 (rows i=10,11,12)

    out = resample_weekly(truncated, drop_incomplete_trailing=False)

    assert len(out) == 3
    partial = out.loc["2024-01-17"]
    assert partial["close"] == truncated["close"].iloc[-1]  # Wednesday's close, not a later day's
    assert partial["open"] == truncated.loc["2024-01-15", "open"]
    assert partial["high"] == truncated.iloc[10:13]["high"].max()
    assert partial["low"] == truncated.iloc[10:13]["low"].min()
    assert partial["volume"] == truncated.iloc[10:13]["volume"].sum()


def test_real_nyse_holiday_week_is_complete_without_friday_bar():
    # Independence Day 2025-07-04 fell on a Friday, so that ISO week's last
    # real NYSE session is Thursday 2025-07-03. Verified via sts.calendar
    # itself (not hand-guessed), per the calendar's own holiday schedule.
    assert not cal.is_session(dt.date(2025, 7, 4))
    assert cal.is_session(dt.date(2025, 7, 3))

    sessions = cal.sessions_between(dt.date(2025, 6, 16), dt.date(2025, 7, 3))
    df = pd.DataFrame(
        [flat_bar(o=100 + i, h=101 + i, l=99 + i, c=100 + i, v=1000) for i in range(len(sessions))],
        index=pd.DatetimeIndex(sessions, name="date"),
    )[OHLCV_COLUMNS]

    out = resample_weekly(df)  # drop_incomplete_trailing=True (default)

    # The holiday week must be present (COMPLETE) and indexed by its real
    # last session (Thursday), not dropped and not mislabeled onto Friday.
    assert out.index[-1] == pd.Timestamp("2025-07-03")
    expected_n_weeks = len(pd.DatetimeIndex(sessions).to_period("W-FRI").unique())
    assert len(out) == expected_n_weeks


def test_no_lookahead_completed_weeks_are_byte_identical():
    full = make_frame(three_full_weeks())
    # Truncate partway through the last week (Wednesday of week 3).
    truncated = full.iloc[:13]

    out_full = resample_weekly(full)
    out_trunc = resample_weekly(truncated, drop_incomplete_trailing=False)

    # Weeks 1 and 2 are complete in both versions -> must match exactly,
    # regardless of what data was appended afterward.
    pd.testing.assert_frame_equal(out_trunc.iloc[:2], out_full.iloc[:2])


def test_empty_input_returns_empty_frame_with_columns():
    empty = make_frame([])
    out = resample_weekly(empty)
    assert out.empty
    assert list(out.columns) == OHLCV_COLUMNS


# ---------------------------------------------------------------------------
# align_to_daily
# ---------------------------------------------------------------------------


def _small_weekly_frame():
    idx = pd.DatetimeIndex(["2024-01-05", "2024-01-12", "2024-01-19"], name="date")
    return pd.DataFrame(
        {
            "open": [100.0, 110.0, 120.0],
            "high": [105.0, 115.0, 125.0],
            "low": [99.0, 109.0, 119.0],
            "close": [104.0, 114.0, 124.0],
            "volume": [5000, 5500, 6000],
        },
        index=idx,
    )


def test_align_exact_match_resolves_to_that_weeks_bar():
    weekly = _small_weekly_frame()
    daily_index = pd.DatetimeIndex(["2024-01-12"], name="date")
    out = align_to_daily(weekly, daily_index)
    assert out.loc["2024-01-12", "week_close"] == 114.0
    assert out.loc["2024-01-12", "week_volume"] == 5500


def test_align_dates_between_weeks_resolve_to_earlier_completed_week():
    weekly = _small_weekly_frame()
    daily_index = pd.DatetimeIndex(["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"], name="date")
    out = align_to_daily(weekly, daily_index)
    # All of these fall strictly between the 01-05 and 01-12 weekly bars ->
    # must resolve to the earlier (already-completed) 01-05 bar, never 01-12.
    assert (out["week_close"] == 104.0).all()
    assert (out["week_volume"] == 5000).all()


def test_align_dates_before_first_weekly_bar_get_nan():
    weekly = _small_weekly_frame()
    daily_index = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03"], name="date")
    out = align_to_daily(weekly, daily_index)
    assert out.isna().all().all()
    assert list(out.columns) == WEEKLY_COLUMNS


def test_align_output_shape_and_column_names():
    weekly = _small_weekly_frame()
    daily_index = pd.bdate_range("2024-01-01", periods=20, name="date")
    out = align_to_daily(weekly, daily_index)
    assert list(out.index) == list(daily_index)
    assert list(out.columns) == WEEKLY_COLUMNS


def test_align_empty_weekly_returns_all_nan():
    weekly = resample_weekly(make_frame([]))
    daily_index = pd.bdate_range("2024-01-01", periods=5, name="date")
    out = align_to_daily(weekly, daily_index)
    assert out.isna().all().all()
    assert list(out.columns) == WEEKLY_COLUMNS
