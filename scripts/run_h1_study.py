"""H1 study runner -- executes the LOCKED primary cell of
docs/preregs/2026-07-11_h1-trend-pullback.md against the study roster and
reports the prereg's locked bars as PASS/FAIL/N/A.

This script REPORTS; it never writes a decisions.md verdict and never acts
on a PROCEED. Per the prereg's sign-off section, an independent review is
required before anything acts on a PROCEED, or before any risk-rule/method
change. Layer (a) and Layer (b) both run OOS-only (signal_date >=
--oos-start), matching the prereg's Universe & data section: this is the
confirmatory read the locked prereg exists to authorize.

Usage:
    python scripts/run_h1_study.py [--oos-start 2024-01-01] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar  # noqa: E402
from sts.catalyst import CatalystCalendar  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.eventsim import raw_forward_returns  # noqa: E402
from sts.signals.trend_pullback import DEFAULTS as TREND_PULLBACK_DEFAULTS  # noqa: E402
from sts.study.h1_events import collect_events, slice_by, summarize  # noqa: E402

DEFAULT_OOS_START = dt.date(2024, 1, 1)
COST_ARMS = {"base": (5.0, 1.0), "2x": (10.0, 2.0)}
DOLLAR_VOLUME_WINDOW = 20


def _catalyst_calendar() -> CatalystCalendar:
    return CatalystCalendar.load()


def _era(signal_date: dt.date) -> str:
    return "post-2015" if signal_date.year >= 2015 else "pre-2015"


def _regime_key_fn(spy_df):
    if spy_df is None or spy_df.empty:
        return lambda row: "unknown"
    ma200 = spy_df["close"].rolling(200).mean()
    ma200_by_date = {ts.date(): v for ts, v in ma200.items()}
    close_by_date = {ts.date(): v for ts, v in spy_df["close"].items()}

    def _key(row):
        d = row["signal_date"]
        ma = ma200_by_date.get(d)
        close = close_by_date.get(d)
        if ma is None or close is None or pd.isna(ma):
            return "unknown"
        return "bull" if close > ma else "bear"

    return _key


def _dollar_volume_tercile_key_fn(prices: dict):
    """Same computation serves both the prereg's "Symbol-liquidity tercile"
    and "Dollar-volume interaction" slices -- both are the trailing dollar
    volume at signal date, bucketed into terciles across all events."""
    dv_by_symbol_date: dict[tuple[str, dt.date], float] = {}
    for symbol, df in prices.items():
        dollar_vol = (df["close"] * df["volume"]).rolling(DOLLAR_VOLUME_WINDOW).mean()
        for ts, v in dollar_vol.items():
            dv_by_symbol_date[(symbol, ts.date())] = v

    def _dv(row):
        return dv_by_symbol_date.get((row["symbol"], row["signal_date"]))

    def _key(rows):
        vals = sorted(v for v in (_dv(r) for r in rows) if v is not None and not pd.isna(v))
        if not vals:
            return lambda row: "unknown"
        lo_cut = vals[len(vals) // 3]
        hi_cut = vals[2 * len(vals) // 3]

        def _bucket(row):
            v = _dv(row)
            if v is None or pd.isna(v):
                return "unknown"
            if v <= lo_cut:
                return "low"
            if v <= hi_cut:
                return "mid"
            return "high"

        return _bucket

    return _key


def _bar(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def build_report(prices: dict, oos_start: dt.date, oos_end: dt.date) -> dict:
    layer_a = raw_forward_returns(
        prices, "trend_pullback", TREND_PULLBACK_DEFAULTS,
        horizons=(5, 10, 15), start=oos_start, end=oos_end,
    )

    cal = _catalyst_calendar()
    rows = collect_events(prices, oos_start, oos_end, COST_ARMS, catalyst_calendar=cal)

    layer_b = {
        "gross": summarize(rows, "r_gross"),
        "cost_arms": {arm: summarize(rows, f"r_net_{arm}") for arm in COST_ARMS},
    }

    spy_df = prices.get("SPY")
    slices = {
        "year": slice_by(rows, lambda r: str(r["signal_date"].year)),
        "era": slice_by(rows, lambda r: _era(r["signal_date"])),
        "regime": slice_by(rows, _regime_key_fn(spy_df)),
        "dollar_volume_tercile": slice_by(rows, _dollar_volume_tercile_key_fn(prices)(rows)),
    }

    h15 = layer_a["by_horizon"].get(15, {})
    layer_a_pass = h15.get("mean_return") is not None and h15["mean_return"] > 0
    base_summary = layer_b["cost_arms"]["base"]
    x2_summary = layer_b["cost_arms"]["2x"]
    n_ok = base_summary["n"] >= 100
    base_expectancy_positive = base_summary["expectancy_r"] > 0
    x2_survives = n_ok and base_expectancy_positive and x2_summary["expectancy_r"] > 0

    bars = [
        _bar(
            "layer_a_positive_h15",
            "PASS" if layer_a_pass else "FAIL",
            f"h=15 mean_return={h15.get('mean_return')} n={h15.get('n')}",
        ),
        _bar(
            "layer_b_oos_n_ge_100",
            "PASS" if n_ok else "FAIL",
            f"n={base_summary['n']} (floor 100; below floor is PARK-on-adequacy, not STOP)",
        ),
        _bar(
            "layer_b_oos_expectancy_positive",
            "PASS" if base_expectancy_positive else "FAIL",
            f"base-cost expectancy_r={base_summary['expectancy_r']}",
        ),
        _bar(
            "cost_2x_survives",
            "PASS" if x2_survives else ("N/A" if not n_ok else "FAIL"),
            f"2x-cost expectancy_r={x2_summary['expectancy_r']}",
        ),
    ]

    return {
        "oos_start": oos_start.isoformat(),
        "oos_end": oos_end.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "layer_a": layer_a,
        "layer_b": layer_b,
        "slices": slices,
        "bars": bars,
        "n_events_oos": len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START.isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    oos_start = dt.date.fromisoformat(args.oos_start)
    oos_end = calendar.last_completed_session() + dt.timedelta(days=1)

    store = StudyStore()
    prices = store.load_all()
    print(f"loaded {len(prices)} study-roster symbols; OOS window {oos_start} .. {oos_end}")

    if args.dry_run:
        print("DRY RUN -- not running the study.")
        return

    report = build_report(prices, oos_start, oos_end)

    print(f"\nH1 primary cell -- OOS events: {report['n_events_oos']}")
    for b in report["bars"]:
        print(f"  [{b['status']:>4}] {b['name']}: {b['detail']}")
    print(
        "\nThis is a REPORT, not a verdict -- PROCEED/PARK/STOP recording in "
        "decisions.md requires independent review first (prereg sign-off section)."
    )

    run_dir = ROOT / "runs" / "h1" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "report.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
