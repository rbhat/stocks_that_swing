"""Build the locked, pre-2024 ML development matrices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.ml.data import build_from_paths, verify_artifact_determinism


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", default="configs/study_roster.yaml")
    parser.add_argument("--price-root", default="cache/study_frames")
    parser.add_argument(
        "--detector-config", default="configs/success_v2_phase3.yaml"
    )
    parser.add_argument(
        "--output-dir", default="runs/ml-restart/development"
    )
    parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="build twice and require byte-identical outputs",
    )
    args = parser.parse_args(argv)
    builder = verify_artifact_determinism if args.verify_determinism else build_from_paths
    manifest = builder(
        roster_path=args.roster,
        price_root=args.price_root,
        detector_config_path=args.detector_config,
        output_dir=args.output_dir,
    )
    print(
        "PASS: "
        f"Track A={manifest['matrices']['track_a']['rows']} rows; "
        f"Track B={manifest['matrices']['track_b']['rows']} rows; "
        f"post-wall={manifest['walls']['post_wall_rows_observed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
