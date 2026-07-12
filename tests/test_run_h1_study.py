import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_h1_study as rhs  # noqa: E402


def make_frame(rows: list[dict]) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-02", periods=len(rows), name="date")
    df = pd.DataFrame(rows, index=idx)
    return df[["open", "high", "low", "close", "volume"]]


def bar(o, h, l, c, v=1_000_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _uptrend_with_episode(n_pad_weeks=60):
    rows = []
    price = 50.0
    for _ in range(n_pad_weeks * 5):
        price += 0.15
        rows.append(bar(price - 0.1, price + 0.3, price - 0.3, price))
    d1 = price * 0.85
    d2 = d1 * 0.85
    rows.append(bar(price - 0.1, price + 0.2, d1 - 0.2, d1))
    rows.append(bar(d1 - 0.1, d1 + 0.1, d2 - 0.2, d2))
    rh = rows[-1]["high"]
    rows.append(bar(d2, rh + 1.0, d2 - 0.1, rh + 0.8))
    for _ in range(10):
        c = rows[-1]["close"] * 1.01
        rows.append(bar(c - 0.1, c + 0.3, c - 0.3, c))
    return rows


def test_build_report_shape_and_bars(monkeypatch):
    rows = _uptrend_with_episode()
    df = make_frame(rows)
    spy = make_frame([bar(p, p + 1, p - 1, p) for p in [400.0 + i * 0.1 for i in range(len(rows))]])
    prices = {"TEST": df, "SPY": spy}
    monkeypatch.setattr(rhs, "_catalyst_calendar", lambda: __import__("sts.catalyst", fromlist=["CatalystCalendar"]).CatalystCalendar([]))

    oos_start = df.index[len(df.index) // 2].date()
    oos_end = df.index[-1].date() + dt.timedelta(days=1)
    report = rhs.build_report(prices, oos_start, oos_end)

    assert report["oos_start"] == oos_start.isoformat()
    assert report["oos_end"] == oos_end.isoformat()
    assert "layer_a" in report and "layer_b" in report
    assert set(report["layer_b"]["cost_arms"]) == {"base", "2x"}
    assert "slices" in report
    assert set(report["slices"]) >= {"year", "era", "regime", "dollar_volume_tercile"}
    assert "bars" in report
    bar_keys = {b["name"] for b in report["bars"]}
    assert bar_keys == {
        "layer_a_positive_h15",
        "layer_b_oos_n_ge_100",
        "layer_b_oos_expectancy_positive",
        "cost_2x_survives",
    }
    for b in report["bars"]:
        assert b["status"] in {"PASS", "FAIL", "N/A"}
