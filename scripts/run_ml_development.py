"""Run locked ML Task 5 twice and freeze the exact pre-2024 verdict."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.ml.development import execute_locked_development, sha256_file


def _starting_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _code_hashes() -> dict[str, str]:
    relative_paths = (
        "uv.lock",
        "src/sts/ml/contracts.py",
        "src/sts/ml/walls.py",
        "src/sts/ml/units.py",
        "src/sts/ml/features.py",
        "src/sts/ml/labels.py",
        "src/sts/ml/data.py",
        "src/sts/ml/models.py",
        "src/sts/ml/controls.py",
        "src/sts/ml/evaluation.py",
        "src/sts/ml/development.py",
        "scripts/run_ml_development.py",
    )
    return {
        relative_path: sha256_file(ROOT / relative_path)
        for relative_path in relative_paths
    }


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default="runs/ml-restart/development",
    )
    parser.add_argument(
        "--output",
        default="runs/ml-restart/development/report.json",
    )
    args = parser.parse_args(argv)
    report = execute_locked_development(
        input_dir=ROOT / args.input_dir,
        output_path=ROOT / args.output,
        starting_commit=_starting_commit(),
        code_hashes=_code_hashes(),
        progress=lambda message: print(message, flush=True),
    )
    print(
        f"{report['verdict']}: {report['candidate_count']} candidate(s); "
        f"arms={len(report['arms'])}; attempts={len(report['attempts'])}; "
        f"artifact={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
