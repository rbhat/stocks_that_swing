"""Standalone Drive sync runner: merge-only ledger sync + one-way backtest
artifact push. Also invoked as stage 6 of forward_eod.py's nightly job; this
script exists for manual/cron-independent runs and --dry-run inspection.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import env  # noqa: E402
from sts.forward.ledger import LedgerPaths  # noqa: E402
from sts.forward.sync import push_backtest_artifacts, sync_ledgers  # noqa: E402

logger = logging.getLogger("forward_sync")


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="pass --dry-run to rclone, skip local writes/uploads")
    parser.add_argument("--ledger-root", default="ledger")
    parser.add_argument("--no-backtest", action="store_true", help="skip backtest artifact push")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    env.load()
    paths = LedgerPaths(root=Path(args.ledger_root))

    ledger_outcomes = sync_ledgers(paths, dry_run=args.dry_run)
    print("ledgers:")
    for filename, outcome in ledger_outcomes.items():
        print(f"  {filename}: {outcome}")

    if not args.no_backtest:
        backtest_outcomes = push_backtest_artifacts(dry_run=args.dry_run)
        print("backtest artifacts:")
        for local_dir, outcome in backtest_outcomes.items():
            print(f"  {local_dir}: {outcome}")
    else:
        print("backtest artifacts: skipped (--no-backtest)")

    any_error = any(o.startswith("error") for o in ledger_outcomes.values())
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
