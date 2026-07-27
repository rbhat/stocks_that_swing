"""Run the success-v2 Phase-3 screen through the hard pre-2024 wall."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.study.success_v2_discovery import (
    load_config,
    load_is_frames,
    run_discovery,
)


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/success_v2_phase3.yaml",
    )
    parser.add_argument(
        "--output",
        default="runs/success-v2/phase3/discovery.json",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    data = config["data"]
    import datetime as dt

    frames, manifest = load_is_frames(
        data["price_root"],
        start_inclusive=dt.date.fromisoformat(data["start_inclusive"]),
        end_exclusive=dt.date.fromisoformat(data["end_exclusive"]),
        minimum_filtered_rows=int(data["minimum_filtered_rows"]),
    )
    catalyst_exists = Path(data["catalyst_path"]).exists()
    artifact = run_discovery(
        config,
        frames,
        input_manifest=manifest,
        catalyst_exists=catalyst_exists,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(
        f"{artifact['verdict']}: {artifact['candidate_count']} candidate(s); "
        f"artifact={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
