"""Initialize the sealed VF9/MC5 forward paper run without backfill."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.swing_ranking.config import load_cohort_selected_study
from sts.swing_ranking.forward import initialize_forward_run


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--seal", required=True)
    parser.add_argument("--upcoming-earnings-snapshot", required=True)
    parser.add_argument("--authorization-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    study, selection = load_cohort_selected_study(Path(args.bundle), Path(args.selection))
    result = initialize_forward_run(
        study=study,
        selection=selection,
        seal_path=Path(args.seal),
        upcoming_earnings_snapshot=Path(args.upcoming_earnings_snapshot),
        authorization_date=dt.date.fromisoformat(args.authorization_date),
        output=Path(args.output),
    )
    print(
        {
            "forward_identity": result.identity,
            "path": str(result.path),
            "created": result.created,
        },
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
