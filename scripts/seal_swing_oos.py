"""Audit, analyze, and seal the approved swing-ranking-v1 OOS opening."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.swing_ranking.cohorts import build_oos_cohort_analysis, seal_oos
from sts.swing_ranking.config import load_cohort_selected_study


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--oos", required=True)
    parser.add_argument("--analysis-output", required=True)
    parser.add_argument("--seal-output", required=True)
    args = parser.parse_args(argv)
    _, selection = load_cohort_selected_study(Path(args.bundle), Path(args.selection))
    analysis = build_oos_cohort_analysis(
        oos_path=Path(args.oos),
        selection=selection,
        output=Path(args.analysis_output),
    )
    seal = seal_oos(
        oos_path=Path(args.oos),
        analysis_path=analysis.path,
        selection=selection,
        output=Path(args.seal_output),
    )
    print(
        {
            "analysis_identity": analysis.identity,
            "analysis_path": str(analysis.path),
            "seal_identity": seal.identity,
            "seal_path": str(seal.path),
        },
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
