"""Run all Phase-3 studies strictly in sequence: H1 -> H3 -> H2.

Each study runs via subprocess with its default OOS start (the ratified
2024-01-01 wall baked into each runner). Resumable at two levels: a study
whose runs/<family>/oos_<wall>/report.json already exists is skipped here,
and each runner additionally resumes its own per-cell progress. A nonzero
exit from any study stops the sequence with a clear log line.

Logs per-study start/end, elapsed, and a naive ETA (remaining studies x mean
elapsed so far) to stdout -- the launcher redirects this to runs/run_all.log.

Usage:
    nohup caffeinate -i .venv/bin/python scripts/run_all_studies.py >> runs/run_all.log 2>&1 &
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OOS_WALL = "2024-01-01"
STUDIES = ["h1", "h3", "h2"]  # locked order


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def report_exists(family: str) -> bool:
    if family == "h1":
        # run_h1_study.py writes runs/h1/<utc-timestamp>/report.json; a run
        # counts as done if any existing report carries this wall.
        import json

        for p in sorted((ROOT / "runs" / "h1").glob("*/report.json")):
            try:
                if json.loads(p.read_text()).get("oos_start") == OOS_WALL:
                    return True
            except (OSError, ValueError):
                continue
        return False
    return (ROOT / "runs" / family / f"oos_{OOS_WALL}" / "report.json").exists()


def main() -> int:
    log(f"run_all_studies start -- order {' -> '.join(s.upper() for s in STUDIES)}, wall {OOS_WALL}")
    elapsed_done: list[float] = []
    for i, family in enumerate(STUDIES):
        if report_exists(family):
            log(f"{family.upper()}: report already exists for wall {OOS_WALL} -- skipping (resume)")
            continue
        script = ROOT / "scripts" / f"run_{family}_study.py"
        log(f"{family.upper()}: starting ({script.name})")
        t0 = time.monotonic()
        rc = subprocess.call([sys.executable, str(script)], cwd=ROOT)
        elapsed = time.monotonic() - t0
        if rc != 0:
            log(f"{family.upper()}: FAILED with exit code {rc} after {elapsed:.0f}s -- STOPPING SEQUENCE")
            return rc
        elapsed_done.append(elapsed)
        remaining = len(STUDIES) - i - 1
        eta = remaining * (sum(elapsed_done) / len(elapsed_done))
        log(f"{family.upper()}: done in {elapsed:.0f}s | {remaining} studies left, ETA ~{eta:.0f}s")
    log("run_all_studies complete -- all studies have report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
