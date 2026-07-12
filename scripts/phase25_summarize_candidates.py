"""Phase 2.5 stage: rank sweep_signals/screen_features output into a short
candidates list. Screening, not judging — no PROCEED/PARK/STOP verdict here
(docs/PLAN.md Phase 2.5). Output is candidates, never verdicts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase25_common import atomic_write_json, setup_stage_logger

# Adequacy floor reused verbatim from docs/PREREG_TEMPLATE.md ("n ≥ 100
# OOS events" — same minimum sample size applied here to IS sweep candidates).
DEFAULT_MIN_EVENTS = 100

DISCLAIMER = (
    "**Output is candidates, never verdicts.** This phase cannot itself "
    "produce PROCEED / PARK / STOP — it has no locked prereg and no untouched "
    "OOS to judge against, so nothing it produces is evidence."
)


def _load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def run_summary(run_dir: Path, min_events: int = DEFAULT_MIN_EVENTS) -> None:
    logger = setup_stage_logger("summarize_candidates", run_dir)

    sweep_results = _load_json(run_dir / "sweep_signals" / "results.json")
    screen_result = _load_json(run_dir / "screen_features" / "results.json")

    candidates = []
    if sweep_results is not None:
        candidates = [r for r in sweep_results if r.get("n_events", 0) >= min_events]
        candidates.sort(key=lambda r: r.get("expectancy_r_lower90", float("-inf")),
                         reverse=True)
        logger.info("sweep_signals: %d/%d configs above adequacy floor (n>=%d)",
                    len(candidates), len(sweep_results), min_events)
    else:
        logger.info("sweep_signals results.json not found — skipping")

    if screen_result is None:
        logger.info("screen_features results.json not found — skipping")

    atomic_write_json(candidates, run_dir / "candidates.json")

    lines = [DISCLAIMER, "", "# Phase 2.5 Candidates", ""]
    if candidates:
        lines.append(f"Top configs by `expectancy_r_lower90` (n_events >= {min_events}):")
        lines.append("")
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"{i}. **{c['detector']}** {c['params']} — "
                f"n_events={c['n_events']}, expectancy_r={c.get('expectancy_r'):.4f}, "
                f"expectancy_r_lower90={c.get('expectancy_r_lower90'):.4f}"
            )
    else:
        lines.append("No sweep_signals candidates above the adequacy floor.")

    if screen_result is not None:
        lines.append("")
        lines.append("## Feature-screen model (informational, not ranked)")
        lines.append("")
        frozen_config = screen_result.get("frozen_config")
        lines.append(f"- frozen_config: {frozen_config}")
        by_detector = screen_result.get("by_detector")
        if by_detector is not None:
            for detector, sub in by_detector.items():
                lines.append("")
                lines.append(f"### {detector}")
                lines.append("")
                if sub is None:
                    lines.append("- no result (too few events)")
                    continue
                lines.append(f"- model: {sub.get('model')}")
                lines.append(f"- cv_score: {sub.get('cv_score')}")
                lines.append(f"- n_events: {sub.get('n_events')}")
                lines.append(f"- positive_rate: {sub.get('positive_rate')}")
                lines.append(f"- precision: {sub.get('precision')}")
                lines.append(f"- recall: {sub.get('recall')}")
                lines.append(f"- f1: {sub.get('f1')}")
        else:
            # legacy flat shape fallback
            lines.append(f"- model: {screen_result.get('model')}")
            lines.append(f"- cv_score: {screen_result.get('cv_score')}")
            lines.append(f"- n_events: {screen_result.get('n_events')}")

    (run_dir / "candidates.md").write_text("\n".join(lines) + "\n")
    logger.info("summarize_candidates done: %d candidates written", len(candidates))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--min-events", type=int, default=DEFAULT_MIN_EVENTS)
    args = ap.parse_args()
    run_summary(args.run_dir, args.min_events)


if __name__ == "__main__":
    main()
