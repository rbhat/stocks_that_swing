import datetime as dt

import pandas as pd
import pytest

from sts import risk
from sts.study.h1_events import collect_events, cost_r, slice_by, summarize


def make_frame(rows: list[dict]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_cost_r_scales_with_bps_and_shrinks_stop_distance():
    entry, stop = 100.0, 96.0  # stop distance = 4.0
    base = cost_r(entry, stop, bps_per_side=5.0, per_order=1.0)
    doubled = cost_r(entry, stop, bps_per_side=10.0, per_order=2.0)
    assert base > 0.0
    assert doubled > base  # 2x cost arm must cost more R than the base arm
    tighter_stop = cost_r(entry, 99.0, bps_per_side=5.0, per_order=1.0)
    assert tighter_stop > base  # same $ cost, smaller stop distance -> more R


def test_summarize_empty_and_single():
    assert summarize([]) == {"n": 0, "expectancy_r": 0.0, "expectancy_r_lower90": None}
    one = summarize([{"r_gross": 1.5}])
    assert one["n"] == 1
    assert one["expectancy_r"] == pytest.approx(1.5)
    assert one["expectancy_r_lower90"] is None


def test_slice_by_groups_and_summarizes():
    rows = [
        {"r_gross": 1.0, "year": "2024"},
        {"r_gross": -1.0, "year": "2024"},
        {"r_gross": 2.0, "year": "2025"},
    ]
    out = slice_by(rows, lambda r: r["year"])
    assert set(out) == {"2024", "2025"}
    assert out["2024"]["n"] == 2
    assert out["2025"]["expectancy_r"] == pytest.approx(2.0)


def test_collect_events_end_to_end_with_wall_and_cost_arms():
    # 25 flat warmup bars for ATR to settle, then a weekly-uptrend-in-miniature
    # + oversold + reclaim pattern re-using the same shape trend_pullback's
    # own tests use, twice: once before the wall, once after.
    rows = []
    price = 100.0
    for _ in range(30):
        rows.append(bar(price - 0.5, price + 0.5, price - 0.5, price))

    def _episode(rows, base):
        p = base
        for _ in range(8 * 5):
            p += 0.4
            rows.append(bar(p - 0.1, p + 0.3, p - 0.3, p))
        d1 = p * 0.85
        d2 = d1 * 0.85
        rows.append(bar(p - 0.1, p + 0.2, d1 - 0.2, d1))
        rows.append(bar(d1 - 0.1, d1 + 0.1, d2 - 0.2, d2))
        rh = rows[-1]["high"]
        rows.append(bar(d2, rh + 1.0, d2 - 0.1, rh + 0.8))
        for _ in range(6):
            c = rows[-1]["close"] * 1.01
            rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
        return rows[-1]["close"]

    last = _episode(rows, price)
    _episode(rows, last)
    df = make_frame(rows)
    prices = {"TEST": df}

    cost_arms = {"base": (5.0, 1.0), "2x": (10.0, 2.0)}
    all_rows = collect_events(
        prices, start=dt.date(2000, 1, 1), end=dt.date(2100, 1, 1), cost_arms=cost_arms
    )
    assert len(all_rows) >= 1
    for row in all_rows:
        assert "r_net_base" in row and "r_net_2x" in row
        assert row["r_net_2x"] <= row["r_net_base"]  # 2x costs never help expectancy

    wall = all_rows[len(all_rows) // 2]["signal_date"] if len(all_rows) > 1 else dt.date(2100, 1, 1)
    walled_rows = collect_events(prices, start=wall, end=dt.date(2100, 1, 1), cost_arms=cost_arms)
    assert all(r["signal_date"] >= wall for r in walled_rows)
    assert len(walled_rows) <= len(all_rows)
