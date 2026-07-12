"""Phase-4 portfolio study runner -- turns the three PROCEED families (H1
trend-pullback, H3 re-geometried breakout, H2 PEAD) into real portfolio
backtests via `sts.portfolio.simulate_portfolio`, judged against the
Phase-4 absolute bars (net_return>0 base-arm, max_drawdown<=25%,
avg_deployed>=20%; see docs/superpowers/plans/2026-07-12-phase4-portfolio.md).

This script REPORTS; it never writes a decisions.md verdict, and per Phase-3
convention, an independent review is required before anything acts on a
PROCEED. Year-by-year stability is reported in `slices` only (analyst-judged,
same as Phase 3) -- it is deliberately NOT one of the machine-checkable
`bars`.

Resumable: an existing `runs/h4/<family>/report.json` for the requested
`--oos-start` is left alone and this run is skipped with a log line, so a
sequential multi-family driver (mirroring `run_all_studies.py`) can re-invoke
this script per family without redoing finished work.

Usage:
    python scripts/run_h4_study.py --family {h1,h3,h2,combined} \
        [--oos-start 2024-01-01] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar  # noqa: E402
from sts.catalyst import CatalystCalendar  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.portfolio import simulate_portfolio  # noqa: E402
from sts.study.h4_candidates import FAMILY_PARAMS, candidates_for  # noqa: E402
from sts.study.h4_gate import bootstrap_expectancy, jitter_grid, year_stability  # noqa: E402

DEFAULT_OOS_START = dt.date(2024, 1, 1)
COST_ARMS = {"base": (5.0, 1.0), "2x": (10.0, 2.0)}
SUB_FAMILIES = ("h1", "h3", "h2")
FAMILIES = (*SUB_FAMILIES, "combined")

# Provisional jitter spec (one-at-a-time perturbation of each family's locked
# ATR stop/target multiples, +/-25%): this is NOT the prereg-named jitter
# spec the plan's Task 5 preregs will lock -- those preregs are out of scope
# for this runner's implementation (Task 4 only) and must supersede this
# constant before any real Phase-4 run. See final-report deviation note.
JITTER_SPECS: dict[str, dict[str, list]] = {
    family: {
        "atr_stop_multiple": [
            round(FAMILY_PARAMS[family]["risk_params"]["atr_stop_multiple"] * 0.75, 4),
            round(FAMILY_PARAMS[family]["risk_params"]["atr_stop_multiple"] * 1.25, 4),
        ],
        "atr_target_multiple": [
            round(FAMILY_PARAMS[family]["risk_params"]["atr_target_multiple"] * 0.75, 4),
            round(FAMILY_PARAMS[family]["risk_params"]["atr_target_multiple"] * 1.25, 4),
        ],
    }
    for family in SUB_FAMILIES
}


def _bar(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _build_candidates(
    family: str,
    prices: dict,
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    """`family` in {"h1","h3","h2"} -> that family's candidates alone.
    `family == "combined"` -> the concatenation of all three (family never
    enters the entry-priority tiebreak -- `simulate_portfolio` sorts
    candidates by (signal_date, symbol) regardless of family). `overrides`
    maps a sub-family name to a risk-params dict that replaces its LOCKED
    `FAMILY_PARAMS` for this call only (used by the jitter arms); every
    other sub-family stays at its locked params."""
    overrides = overrides or {}
    if family in SUB_FAMILIES:
        return candidates_for(family, prices, oos_start, oos_end, catalyst, overrides.get(family))
    if family == "combined":
        out: list[dict] = []
        for sub in SUB_FAMILIES:
            out.extend(
                candidates_for(sub, prices, oos_start, oos_end, catalyst, overrides.get(sub))
            )
        return out
    raise ValueError(f"unknown family {family!r}, expected one of {FAMILIES}")


def _spy_reference(prices: dict, oos_start: dt.date, oos_end: dt.date) -> dict | None:
    """SPY buy-and-hold over the same OOS window, reported for reference
    only -- never a bar, never a relative pass/fail criterion."""
    spy_df = prices.get("SPY")
    if spy_df is None or spy_df.empty:
        return None
    window = spy_df.loc[
        (spy_df.index.date >= oos_start) & (spy_df.index.date < oos_end)
    ]
    if window.empty:
        return None
    first_close = float(window["close"].iloc[0])
    last_close = float(window["close"].iloc[-1])
    if first_close <= 0:
        return None
    return {"net_return": last_close / first_close - 1.0, "n_sessions": len(window)}


def build_report(
    family: str,
    prices: dict,
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
) -> dict:
    cost_arm_results = {}
    for arm_name, (bps, fee) in COST_ARMS.items():
        candidates = _build_candidates(family, prices, oos_start, oos_end, catalyst)
        cost_arm_results[arm_name] = simulate_portfolio(
            prices, candidates, oos_start, oos_end, bps_per_side=bps, per_order=fee
        )

    base_result = cost_arm_results["base"]
    base_summary = base_result["summary"]

    net_return_pass = base_summary["net_return"] > 0
    max_dd_pass = base_summary["max_drawdown"] <= 0.25
    avg_deployed_pass = base_summary["avg_deployed"] >= 0.20

    bars = [
        _bar(
            "net_return_positive_base_arm",
            "PASS" if net_return_pass else "FAIL",
            f"net_return={base_summary['net_return']}",
        ),
        _bar(
            "max_drawdown_le_25pct",
            "PASS" if max_dd_pass else "FAIL",
            f"max_drawdown={base_summary['max_drawdown']}",
        ),
        _bar(
            "avg_deployed_ge_20pct",
            "PASS" if avg_deployed_pass else "FAIL",
            f"avg_deployed={base_summary['avg_deployed']}",
        ),
    ]

    r_values = [t["r_net"] for t in base_result["trades"]]
    bootstrap = bootstrap_expectancy(r_values)
    stability = year_stability(base_summary["by_year"])

    jitter_table = []
    if family == "combined":
        for sub in SUB_FAMILIES:
            grid = jitter_grid(FAMILY_PARAMS[sub]["risk_params"], JITTER_SPECS[sub])
            for variant in grid:
                cands = _build_candidates(
                    family, prices, oos_start, oos_end, catalyst, overrides={sub: variant}
                )
                res = simulate_portfolio(prices, cands, oos_start, oos_end)
                jitter_table.append(
                    {
                        "jittered_family": sub,
                        "params": variant,
                        "net_return": res["summary"]["net_return"],
                        "expectancy_r_net": res["summary"]["expectancy_r_net"],
                    }
                )
    else:
        grid = jitter_grid(FAMILY_PARAMS[family]["risk_params"], JITTER_SPECS[family])
        for variant in grid:
            cands = _build_candidates(
                family, prices, oos_start, oos_end, catalyst, overrides={family: variant}
            )
            res = simulate_portfolio(prices, cands, oos_start, oos_end)
            jitter_table.append(
                {
                    "params": variant,
                    "net_return": res["summary"]["net_return"],
                    "expectancy_r_net": res["summary"]["expectancy_r_net"],
                }
            )

    slices = {
        "by_year": base_summary["by_year"],
        "year_stability": stability,
        "cost_arms": {name: r["summary"] for name, r in cost_arm_results.items()},
        "jitter": jitter_table,
        "bootstrap_expectancy": bootstrap,
        "spy_reference": _spy_reference(prices, oos_start, oos_end),
    }

    return {
        "family": family,
        "oos_start": oos_start.isoformat(),
        "oos_end": oos_end.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_trades_base_arm": base_summary["n_trades"],
        "bars": bars,
        "slices": slices,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START.isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    oos_start = dt.date.fromisoformat(args.oos_start)
    oos_end = calendar.last_completed_session() + dt.timedelta(days=1)

    run_dir = ROOT / "runs" / "h4" / args.family
    out_path = run_dir / "report.json"

    store = StudyStore()
    prices = store.load_all()
    print(f"loaded {len(prices)} study-roster symbols; OOS window {oos_start} .. {oos_end}")
    print(f"family: {args.family} | run dir: {run_dir}")

    if args.dry_run:
        print("DRY RUN -- not running the study.")
        return

    if out_path.exists():
        existing = json.loads(out_path.read_text())
        if existing.get("oos_start") == oos_start.isoformat():
            print(f"[resume] {out_path} already exists for this OOS wall -- skipping.")
            return
        print(f"[resume] {out_path} exists for a different OOS wall; re-running.")

    t0 = time.monotonic()
    cal = CatalystCalendar.load()
    report = build_report(args.family, prices, oos_start, oos_end, cal)
    elapsed = time.monotonic() - t0
    print(f"{args.family}: {report['n_trades_base_arm']} base-arm trades in {elapsed:.0f}s", file=sys.stderr)

    print(f"\nH4 portfolio -- family={args.family} -- OOS {oos_start} .. {oos_end}")
    for b in report["bars"]:
        print(f"  [{b['status']:>4}] {b['name']}: {b['detail']}")
    print(
        "\nThis is a REPORT, not a verdict -- PROCEED/PARK/STOP recording in "
        "decisions.md requires independent review first, and year-stability "
        "is analyst-judged from `slices`, not a machine bar."
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
