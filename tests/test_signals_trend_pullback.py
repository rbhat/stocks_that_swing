import numpy as np
import pandas as pd
import pytest

from sts.signals.trend_pullback import DEFAULTS, detect

_PARAMS = {
    **DEFAULTS,
    "weekly_ma_window": 3,
    "weekly_rising_lag": 1,
    "rsi_window": 2,
    "rsi_oversold": 10.0,
    "reclaim_max_wait": 5,
    "swing_window": 10,
}


def make_frame(rows: list[dict]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _uptrend_base(n_weeks: int, start: float = 100.0, step: float = 1.0) -> list[dict]:
    """n_weeks full 5-day weeks, each week's close a bit higher than the
    last, so `weekly_ma_window=3`'s MA is both below price and rising by the
    end -- a clean weekly uptrend with no pullback machinery involved yet."""
    rows: list[dict] = []
    price = start
    for _ in range(n_weeks):
        for _ in range(5):
            price += step / 5
            rows.append(bar(price - 0.1, price + 0.3, price - 0.3, price))
    return rows


def test_detects_reclaim_after_oversold_in_uptrend():
    rows = _uptrend_base(n_weeks=8, start=100.0, step=2.0)
    last_close = rows[-1]["close"]
    # Two sharp down days (RSI(2) plunges), then a reclaim day closing above
    # the prior day's high, then 5 trailing pad days so the reclaim week is
    # not the (possibly-incomplete) trailing week.
    down1 = last_close * 0.90
    down2 = down1 * 0.90
    rows.append(bar(last_close - 0.1, last_close + 0.2, down1 - 0.2, down1))
    rows.append(bar(down1 - 0.1, down1 + 0.1, down2 - 0.2, down2))
    reclaim_high = rows[-1]["high"]
    rows.append(bar(down2, reclaim_high + 0.5, down2 - 0.1, reclaim_high + 0.3))
    for _ in range(5):
        c = rows[-1]["close"] * 1.01
        rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
    df = make_frame(rows)

    events = detect("TEST", df, _PARAMS, "trend_pullback")

    assert len(events) == 1
    ev = events[0]
    assert ev.symbol == "TEST"
    assert ev.trigger_values["rsi2_at_trigger"] < 10.0
    assert "swing_low" in ev.trigger_values and "swing_high" in ev.trigger_values


def test_no_event_in_weekly_downtrend():
    rows: list[dict] = []
    price = 200.0
    for _ in range(8 * 5):
        price -= 0.4
        rows.append(bar(price + 0.1, price + 0.3, price - 0.3, price))
    down1 = price * 0.90
    down2 = down1 * 0.90
    rows.append(bar(price - 0.1, price + 0.2, down1 - 0.2, down1))
    rows.append(bar(down1 - 0.1, down1 + 0.1, down2 - 0.2, down2))
    rows.append(bar(down2, down2 + 5, down2 - 0.1, down2 + 4))
    df = make_frame(rows)

    events = detect("TEST", df, _PARAMS, "trend_pullback")

    assert events == []


def test_consecutive_oversold_days_dedupe_to_one_event():
    rows = _uptrend_base(n_weeks=8, start=100.0, step=2.0)
    # Four extra uptrend pad days shift the weekday alignment so the
    # 3-day-down + reclaim sequence below lands with the reclaim NOT on the
    # last trading day of its ISO week -- otherwise the reclaim day's own
    # (still-declining, not-yet-recovered) week close reads as a weekly
    # downtrend via sts.weekly.align_to_daily's backward as-of join, which
    # only lets a day use its own week's stats once that week is the exact
    # match date (see module docstring: "exact matches are allowed").
    for _ in range(4):
        c = rows[-1]["close"] + 0.4
        rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
    last_close = rows[-1]["close"]
    # Three consecutive sharp down days (RSI(2) stays under threshold for
    # more than one day) before the reclaim -- must still fire exactly one
    # event, not one per oversold day.
    p = last_close
    for _ in range(3):
        p = p * 0.92
        rows.append(bar(p / 0.92 - 0.1, p / 0.92 + 0.1, p - 0.2, p))
    reclaim_high = rows[-1]["high"]
    rows.append(bar(p, reclaim_high + 0.5, p - 0.1, reclaim_high + 0.3))
    for _ in range(5):
        c = rows[-1]["close"] * 1.01
        rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
    df = make_frame(rows)

    events = detect("TEST", df, _PARAMS, "trend_pullback")

    assert len(events) == 1
