"""Run the guarded forward daily coordinator on an hourly retry cadence."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("STS_FORWARD_INTERVAL_SECONDS", "3600")),
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.interval_seconds < 60:
        parser.error("--interval-seconds must be at least 60")
    command = [sys.executable, "scripts/run_swing_forward_daily.py"]
    while True:
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode:
            print(
                f"forward coordinator failed with exit {completed.returncode}; will retry",
                file=sys.stderr,
                flush=True,
            )
        if args.once:
            return completed.returncode
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
