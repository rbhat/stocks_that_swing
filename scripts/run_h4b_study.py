"""Phase-4b portfolio study runner -- H1 re-expressed with ranked selection
+ burst throttle, per the locked prereg
docs/preregs/2026-07-12_h4b-h1-ranked-expression.md. Same signal as Phase-4
H1 (no detector/geometry retest); only the entry-priority ordering and a
new-entries throttle change, via `sts.portfolio.simulate_portfolio`'s
`entry_rank_key` / `max_new_entries_per_window` kwargs.

This script REPORTS; it never writes a decisions.md verdict, and per
Phase-3/4 convention, an independent review is required before anything
acts on a PROCEED. Year-by-year stability is reported in `slices` only
(analyst-judged) -- it is deliberately NOT one of the machine-checkable
`bars`.

Resumable: an existing `runs/h4b/h1/report.json` for the requested
`--oos-start` is left alone and this run is skipped with a log line.

Usage:
    python scripts/run_h4b_study.py [--oos-start 2024-01-01] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar, risk  # noqa: E402
from sts.catalyst import CatalystCalendar  # noqa: E402
from sts.data.study_store import StudyStore  # noqa: E402
from sts.portfolio import simulate_portfolio  # noqa: E402
from sts.study.h4_candidates import FAMILY_PARAMS, candidates_for  # noqa: E402
from sts.study.h4_gate import bootstrap_expectancy, year_stability  # noqa: E402

DEFAULT_OOS_START = dt.date(2024, 1, 1)
COST_ARMS = {"base": (5.0, 1.0), "2x": (10.0, 2.0)}
BASE_BPS, BASE_FEE = COST_ARMS["base"]
PRIMARY_THROTTLE = (4, 5)
JITTER_THROTTLE_ARMS = [(3, 5), (5, 5)]

# Prereg-locked rank key: seed-preferred first, then deeper dislocation
# (lower rsi2_at_trigger), then faster demand response (lower
# reclaim_wait_sessions); last two keys are deterministic tiebreaks only.
def RANK_KEY(c: dict) -> tuple:
    return (
        not c["is_seed"],
        c["rsi2_at_trigger"],
        c["reclaim_wait_sessions"],
        c["signal_date"],
        c["symbol"],
    )


# Provisional ATR jitter spec, one-at-a-time +/-25% around the locked H1
# risk params -- mirrors run_h4_study's JITTER_SPECS for h1.
_H1_RISK = FAMILY_PARAMS["h1"]["risk_params"]
ATR_JITTER_SPEC = {
    "atr_stop_multiple": [1.5, 2.5],
    "atr_target_multiple": [1.5, 2.5],
}


def _bar(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def event_r_net(df, cand: dict, bps: float = BASE_BPS, fee: float = BASE_FEE):
    """Standalone per-event walk, base costs -- reused verbatim (same cost/
    geometry treatment) from .scratch/diag_h1_h3.py's event_r_net, kept local
    to this script per the prereg (selection-quality read helper, not a
    src.sts function)."""
    idx_dates = list(df.index.date)
    try:
        e = idx_dates.index(cand["entry_date"])
    except ValueError:
        return None
    entry, stop, target = cand["entry"], cand["stop"], cand.get("target")
    try:
        pos = risk.Position(
            cand["symbol"], entry, 1, stop, target, cand["entry_date"], cand["family"]
        )
    except risk.RuleViolation:
        return None
    exit_price = None
    for j in range(e, len(df)):
        row = df.iloc[j]
        ex = risk.manage_bar(
            pos, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        )
        if ex:
            exit_price = ex[0][1]
            break
    if exit_price is None:
        exit_price = float(df["close"].iloc[-1])
    cost_per_share = (entry + exit_price) * bps / 10_000 + 2 * fee  # $1/order x2, 1 share
    return (exit_price - entry - cost_per_share) / (entry - stop)


def _spy_reference(prices: dict, oos_start: dt.date, oos_end: dt.date) -> dict | None:
    spy_df = prices.get("SPY")
    if spy_df is None or spy_df.empty:
        return None
    window = spy_df.loc[(spy_df.index.date >= oos_start) & (spy_df.index.date < oos_end)]
    if window.empty:
        return None
    first_close = float(window["close"].iloc[0])
    last_close = float(window["close"].iloc[-1])
    if first_close <= 0:
        return None
    return {"net_return": last_close / first_close - 1.0, "n_sessions": len(window)}


def _exit_reason_mix(trades: list[dict]) -> dict:
    counts = Counter(t["exit_reason"] for t in trades)
    return dict(sorted(counts.items()))


def build_report(
    prices: dict,
    oos_start: dt.date,
    oos_end: dt.date,
    catalyst: CatalystCalendar,
) -> dict:
    candidates = candidates_for("h1", prices, oos_start, oos_end, catalyst)

    # Primary cell + 2x cost arm: ranked selection + primary throttle.
    cost_arm_results = {}
    for arm_name, (bps, fee) in COST_ARMS.items():
        cost_arm_results[arm_name] = simulate_portfolio(
            prices,
            candidates,
            oos_start,
            oos_end,
            bps_per_side=bps,
            per_order=fee,
            entry_rank_key=RANK_KEY,
            max_new_entries_per_window=PRIMARY_THROTTLE,
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

    # Jitter table: one-at-a-time ATR risk-param perturbations (locked
    # ranking + primary throttle, base costs) + two throttle-only arms
    # (locked ATR params, ranking on) per the prereg's expression-jitter arm.
    jitter_table = []
    for key, values in ATR_JITTER_SPEC.items():
        for value in values:
            variant = dict(_H1_RISK)
            variant[key] = value
            cands = candidates_for("h1", prices, oos_start, oos_end, catalyst, variant)
            res = simulate_portfolio(
                prices,
                cands,
                oos_start,
                oos_end,
                entry_rank_key=RANK_KEY,
                max_new_entries_per_window=PRIMARY_THROTTLE,
            )
            jitter_table.append(
                {
                    "jittered": "risk_param",
                    "param": key,
                    "value": value,
                    "net_return": res["summary"]["net_return"],
                    "expectancy_r_net": res["summary"]["expectancy_r_net"],
                }
            )
    for cap, window in JITTER_THROTTLE_ARMS:
        res = simulate_portfolio(
            prices,
            candidates,
            oos_start,
            oos_end,
            entry_rank_key=RANK_KEY,
            max_new_entries_per_window=(cap, window),
        )
        jitter_table.append(
            {
                "jittered": "throttle",
                "param": "max_new_entries_per_window",
                "value": [cap, window],
                "net_return": res["summary"]["net_return"],
                "expectancy_r_net": res["summary"]["expectancy_r_net"],
            }
        )

    # Descriptive arm: ranking only, throttle off. Never load-bearing.
    ranking_only_result = simulate_portfolio(
        prices, candidates, oos_start, oos_end, entry_rank_key=RANK_KEY
    )

    # Seed vs non-seed slice: taken trades in the primary base arm, looked
    # up via a symbol -> is_seed map built from the candidate list (is_seed
    # is a per-symbol universe fact, not per-event).
    seed_of_symbol = {c["symbol"]: c["is_seed"] for c in candidates}
    seed_trades = [t for t in base_result["trades"] if seed_of_symbol.get(t["symbol"])]
    non_seed_trades = [t for t in base_result["trades"] if not seed_of_symbol.get(t["symbol"])]

    def _mean_r(trades: list[dict]) -> float | None:
        return sum(t["r_net"] for t in trades) / len(trades) if trades else None

    seed_slice = {
        "seed": {"n": len(seed_trades), "mean_r_net": _mean_r(seed_trades)},
        "non_seed": {"n": len(non_seed_trades), "mean_r_net": _mean_r(non_seed_trades)},
    }

    # Selection-quality read: independent event-level mean r_net for ALL
    # candidates vs the taken subset of the primary base arm.
    taken_keys = {(t["symbol"], t["entry_date"]) for t in base_result["trades"]}
    all_r, taken_r = [], []
    for c in candidates:
        df = prices.get(c["symbol"])
        if df is None or df.empty:
            continue
        r = event_r_net(df, c)
        if r is None:
            continue
        all_r.append(r)
        if (c["symbol"], c["entry_date"]) in taken_keys:
            taken_r.append(r)
    selection_quality = {
        "all_candidates": {"n": len(all_r), "mean_r_net": _mean_r([{"r_net": r} for r in all_r])},
        "taken_subset": {
            "n": len(taken_r),
            "mean_r_net": _mean_r([{"r_net": r} for r in taken_r]),
        },
    }

    slices = {
        "by_year": base_summary["by_year"],
        "year_stability": stability,
        "cost_arms": {name: r["summary"] for name, r in cost_arm_results.items()},
        "jitter": jitter_table,
        "bootstrap_expectancy": bootstrap,
        "spy_reference": _spy_reference(prices, oos_start, oos_end),
        "ranking_only_arm": ranking_only_result["summary"],
        "seed_slice": seed_slice,
        "selection_quality": selection_quality,
        "exit_reason_mix": _exit_reason_mix(base_result["trades"]),
        "friction_share": base_summary.get("friction_share"),
        "slot_pressure": {
            "n_slot_skipped": base_summary["n_slot_skipped"],
            "n_dup_symbol": base_summary["n_dup_symbol"],
            "n_throttle_skipped": base_summary["n_throttle_skipped"],
        },
    }

    return {
        "family": "h1",
        "study": "h4b-h1-ranked-expression",
        "oos_start": oos_start.isoformat(),
        "oos_end": oos_end.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_trades_base_arm": base_summary["n_trades"],
        "bars": bars,
        "slices": slices,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START.isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    oos_start = dt.date.fromisoformat(args.oos_start)
    oos_end = calendar.last_completed_session() + dt.timedelta(days=1)

    run_dir = ROOT / "runs" / "h4b" / "h1"
    out_path = run_dir / "report.json"

    store = StudyStore()
    prices = store.load_all()
    print(f"loaded {len(prices)} study-roster symbols; OOS window {oos_start} .. {oos_end}")
    print(f"study: h4b h1 ranked-expression | run dir: {run_dir}")

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
    report = build_report(prices, oos_start, oos_end, cal)
    elapsed = time.monotonic() - t0
    print(f"h4b h1: {report['n_trades_base_arm']} base-arm trades in {elapsed:.0f}s", file=sys.stderr)

    print(f"\nH4b portfolio -- H1 ranked expression -- OOS {oos_start} .. {oos_end}")
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
