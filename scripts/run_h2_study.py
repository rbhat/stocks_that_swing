"""H2 study runner -- earnings-reaction drift / PEAD price-proxy
(docs/preregs/2026-07-12_h2-pead.md).

Builds reaction events once over the full roster history (no OOS filtering
yet), assigns causal deciles once over that full history, then per cell
filters to the OOS window and runs the appropriate entry mode. Three cells:
"top_decile_day2_open" (PRIMARY, judged), "top_decile_pullback" (secondary,
descriptive), "bottom_decile_day2_open" (descriptive, other tail, never
traded).

This script REPORTS; it never writes a decisions.md verdict.

Resumable: each cell's report is written to the run dir as it completes;
re-running with the same --oos-start / --run-dir skips finished cells.

Usage:
    python scripts/run_h2_study.py [--oos-start 2024-01-01] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar  # noqa: E402
from sts.catalyst import EARNINGS_PATH, CatalystCalendar  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.study.h1_events import slice_by, summarize  # noqa: E402
from sts.study.h2_events import (  # noqa: E402
    _PARAM_DEFAULTS,
    assign_deciles,
    build_reaction_events,
    collect_events,
    load_earnings_dates,
    raw_forward_returns_from_events,
)

DEFAULT_OOS_START = dt.date(2024, 1, 1)
COST_ARMS = {"base": (5.0, 1.0), "2x": (10.0, 2.0)}
DOLLAR_VOLUME_WINDOW = 20
PRIMARY_CELL = "top_decile_day2_open"

# cell_name -> (decile_flag to select, entry_mode)
CELLS: dict[str, tuple[str, str]] = {
    "top_decile_day2_open": ("top", "day2_open"),
    "top_decile_pullback": ("top", "pullback"),
    "bottom_decile_day2_open": ("bottom", "day2_open"),
}


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


def build_cell_report(
    cell: str,
    entry_mode: str,
    cell_events: list[dict],
    prices: dict,
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst_calendar: CatalystCalendar,
) -> dict:
    windowed_events = [e for e in cell_events if oos_start <= e["signal_date"] < oos_end]
    layer_a = raw_forward_returns_from_events(prices, windowed_events, horizons=(5, 10, 15))

    rows = collect_events(
        prices, cell_events, oos_start, oos_end, COST_ARMS,
        catalyst_calendar=catalyst_calendar, entry_mode=entry_mode,
    )

    layer_b = {
        "gross": summarize(rows, "r_gross"),
        "cost_arms": {arm: summarize(rows, f"r_net_{arm}") for arm in COST_ARMS},
    }

    spy_df = prices.get("SPY")
    slices = {
        "year": slice_by(rows, lambda r: str(r["signal_date"].year)),
        "regime": slice_by(rows, _regime_key_fn(spy_df)),
        "dollar_volume_tercile": slice_by(rows, _dollar_volume_tercile_key_fn(prices)(rows)),
        "exit_reason": slice_by(rows, lambda r: r["exit_reason"]),
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
        "cell": cell,
        "entry_mode": entry_mode,
        "oos_start": oos_start.isoformat(),
        "oos_end": oos_end.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_candidate_events": len(windowed_events),
        "layer_a": layer_a,
        "layer_b": layer_b,
        "slices": slices,
        "bars": bars,
        "n_events_oos": len(rows),
        "judged": cell == PRIMARY_CELL,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START.isoformat())
    parser.add_argument(
        "--run-dir", default=None,
        help="run directory (default runs/h2/oos_<oos-start>); reruns resume it",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    oos_start = dt.date.fromisoformat(args.oos_start)
    oos_end = calendar.last_completed_session() + dt.timedelta(days=1)

    run_dir = Path(args.run_dir) if args.run_dir else ROOT / "runs" / "h2" / f"oos_{oos_start.isoformat()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    store = StudyStore()
    prices = store.load_all()
    print(f"loaded {len(prices)} study-roster symbols; OOS window {oos_start} .. {oos_end}")
    print(f"run dir: {run_dir} (per-cell reports resume across reruns)")

    if args.dry_run:
        print(f"DRY RUN -- cells: {', '.join(CELLS)}. Not running the study.")
        return

    cal = CatalystCalendar.load()
    spy_df = prices.get("SPY")
    if spy_df is None or spy_df.empty:
        raise RuntimeError("SPY not found in study roster prices -- required as master session axis")
    session_index = spy_df.index

    earnings_dates = load_earnings_dates(EARNINGS_PATH)
    total_reports = sum(len(v) for v in earnings_dates.values())
    all_events = build_reaction_events(prices, earnings_dates, session_index)
    # Reports lost before decile assignment: mostly the volume-confirmation
    # drop, but also <20 prior sessions, missing bars, and non-positive
    # prices -- a diagnostic aggregate, never a judged number.
    dropped_pre_decile = total_reports - len(all_events)
    decile_events = assign_deciles(all_events, session_index)
    min_trailing = _PARAM_DEFAULTS["decile_min_trailing"]
    dropped_insufficient_comparison = sum(
        1
        for e in decile_events
        if e["decile_flag"] is None and e["n_trailing_comparison"] < min_trailing
    )
    n_top = sum(1 for e in decile_events if e["decile_flag"] == "top")
    n_bottom = sum(1 for e in decile_events if e["decile_flag"] == "bottom")

    top_events = [e for e in decile_events if e["decile_flag"] == "top"]
    bottom_events = [e for e in decile_events if e["decile_flag"] == "bottom"]
    events_by_flag = {"top": top_events, "bottom": bottom_events}

    event_funnel = {
        "total_past_reports": total_reports,
        "dropped_pre_decile": dropped_pre_decile,
        "dropped_insufficient_comparison": dropped_insufficient_comparison,
        "n_top": n_top,
        "n_bottom": n_bottom,
    }
    print(f"event funnel: {event_funnel}")

    reports: dict[str, dict] = {}
    pending = [c for c in CELLS if not (run_dir / f"cell_{c}.json").exists()]
    done_prior = [c for c in CELLS if c not in pending]
    for c in done_prior:
        reports[c] = json.loads((run_dir / f"cell_{c}.json").read_text())
        print(f"[resume] cell {c}: already done, skipping")

    t0 = time.monotonic()
    for i, cell in enumerate(pending):
        flag, entry_mode = CELLS[cell]
        print(f"\n[{i + 1}/{len(pending)}] running cell {cell} ({entry_mode}, decile={flag}) ...", flush=True)
        cell_t0 = time.monotonic()
        report = build_cell_report(
            cell, entry_mode, events_by_flag[flag], prices, oos_start, oos_end, cal
        )
        (run_dir / f"cell_{cell}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str)
        )
        reports[cell] = report
        elapsed = time.monotonic() - t0
        per_cell = elapsed / (i + 1)
        remaining = per_cell * (len(pending) - i - 1)
        print(
            f"  cell {cell}: {report['n_events_oos']} OOS events in "
            f"{time.monotonic() - cell_t0:.0f}s | elapsed {elapsed:.0f}s, ~{remaining:.0f}s left"
        )

    print(f"\nH2 cells -- OOS window {oos_start} .. {oos_end}")
    for cell in CELLS:
        report = reports[cell]
        judged_note = " [JUDGED -- primary cell]" if report["judged"] else " [reported, not judged]"
        print(f"\n{cell} (n={report['n_events_oos']}){judged_note}:")
        for b in report["bars"]:
            print(f"  [{b['status']:>4}] {b['name']}: {b['detail']}")

    combined = {
        "oos_start": oos_start.isoformat(),
        "oos_end": oos_end.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "event_funnel": event_funnel,
        "cells": reports,
    }
    out_path = run_dir / "report.json"
    out_path.write_text(json.dumps(combined, indent=2, sort_keys=True, default=str))
    print(
        "\nThis is a REPORT, not a verdict -- primary cell = top_decile_day2_open per "
        "docs/preregs/2026-07-12_h2-pead.md; the other cells are descriptive only. Any "
        "PROCEED needs independent review."
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
