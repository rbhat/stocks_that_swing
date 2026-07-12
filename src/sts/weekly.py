"""Weekly resampling of daily OHLCV bars, with shift-safety against in-progress weeks.

Why this module exists
-----------------------
A naive ``df.resample("W-FRI").agg(...)`` is NOT safe to use as-is: if the
input daily frame currently ends mid-week (e.g. data fetched only through a
Wednesday), pandas will still happily emit a "weekly" row for that
in-progress week, built from whatever partial days happen to be present. If
that partial bar is later treated as a completed week's bar, any signal
computed against it is silently using a bar that doesn't really exist yet —
it can still change once more days land (Thursday, Friday). This is the
exact bug class this module exists to prevent.

The fix: after grouping daily bars into ISO weeks (Monday-Friday, labeled by
each week's real Friday), only the LAST (most recent) week-group's
completeness is ever in doubt — every earlier group is already proven
complete by the mere existence of a later group in the data (trading days
don't get inserted retroactively). For that last group we ask the real NYSE
trading calendar whether any sessions were still expected between the
group's last bar and that week's Friday. If yes, the week is still forming
(INCOMPLETE) and — by default — gets dropped rather than risk being read as
final. If no (either the last bar genuinely was the week's last session, or
the remaining calendar days were holidays), the week is COMPLETE and is kept
regardless of whether its last bar happens to fall on a Friday.
"""

from __future__ import annotations

import pandas as pd

from sts.calendar import sessions_between

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
WEEKLY_COLUMNS = [f"week_{c}" for c in OHLCV_COLUMNS]


def _is_last_group_complete(last_bar_date: pd.Timestamp, week_period: pd.Period) -> bool:
    """True if no NYSE sessions were still expected after `last_bar_date` before
    (and including) the Friday that closes `week_period`.
    """
    friday = week_period.end_time.date()
    last_date = last_bar_date.date()
    # last_bar_date always falls inside week_period by construction, so
    # last_date <= friday and this range is always valid (start <= end).
    sessions_through_friday = sessions_between(last_date, friday)
    sessions_after = sessions_through_friday[sessions_through_friday > last_bar_date]
    return len(sessions_after) == 0


def resample_weekly(df: pd.DataFrame, drop_incomplete_trailing: bool = True) -> pd.DataFrame:
    """Aggregate daily OHLCV bars into weekly (Monday-Friday) bars.

    Each output row is indexed by the REAL last trading date present in that
    week's group of `df` — never a synthetic calendar period-end that might
    not be a real trading day — so downstream code aligning weekly bars to
    daily dates can match on dates that actually occur in `df.index`.

    The trailing (most recent) week-group is checked for completeness
    against the real NYSE calendar (see module docstring for why only the
    trailing group needs checking). Complete weeks are always kept. The
    trailing week, if incomplete, is dropped when `drop_incomplete_trailing`
    is True (the default — correct for backtest/study use, where a
    still-forming bar must never be read as final) and kept when False (for
    live/forward use, where an in-progress week is a legitimate partial
    observation).
    """
    if df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS, index=pd.DatetimeIndex([], name=df.index.name))

    df = df.sort_index()
    periods = df.index.to_period("W-FRI")
    grouped = df.groupby(periods, sort=True)

    labels: list[pd.Timestamp] = []
    records: list[dict] = []
    period_keys = list(grouped.groups.keys())
    for period in period_keys:
        sub = grouped.get_group(period)
        last_date = sub.index[-1]
        labels.append(last_date)
        records.append(
            {
                "open": sub["open"].iloc[0],
                "high": sub["high"].max(),
                "low": sub["low"].min(),
                "close": sub["close"].iloc[-1],
                "volume": sub["volume"].sum(),
            }
        )

    last_period = period_keys[-1]
    last_bar_date = labels[-1]
    if not _is_last_group_complete(last_bar_date, last_period) and drop_incomplete_trailing:
        labels.pop()
        records.pop()

    out = pd.DataFrame(records, index=pd.DatetimeIndex(labels, name=df.index.name), columns=OHLCV_COLUMNS)
    return out


def align_to_daily(weekly: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Attach each daily date's most recently completed weekly bar (backward as-of join).

    Exact matches are allowed on purpose: a weekly bar's index date is the
    date its own last session closed, and by the end of that session's
    processing the bar's full OHLCV is genuinely known — so a daily date
    equal to a weekly bar's own date may use that bar (mirrors this
    codebase's convention that a value dated on day t is usable for a signal
    firing on day t itself; only rolling *prior*-window values get shifted).

    Daily dates before the first available weekly bar get all-NaN weekly
    columns rather than an error or a false match.
    """
    daily_index = pd.DatetimeIndex(daily_index)
    rename_map = dict(zip(OHLCV_COLUMNS, WEEKLY_COLUMNS))

    if weekly.empty:
        return pd.DataFrame(float("nan"), index=daily_index, columns=WEEKLY_COLUMNS)

    right = weekly.sort_index().reset_index()
    right = right.rename(columns={right.columns[0]: "_week_date", **rename_map})
    right = right[["_week_date", *WEEKLY_COLUMNS]]

    sorted_daily = daily_index.sort_values()
    left = pd.DataFrame({"_daily_date": sorted_daily})

    merged = pd.merge_asof(
        left,
        right,
        left_on="_daily_date",
        right_on="_week_date",
        direction="backward",
        allow_exact_matches=True,
    )
    merged = merged.set_index("_daily_date")[WEEKLY_COLUMNS]

    # merge_asof required sorted keys; restore the caller's original order.
    result = merged.reindex(daily_index)
    result.index.name = daily_index.name
    return result
