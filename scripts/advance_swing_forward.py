"""Advance the sealed swing-ranking forward paper run by one completed session."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.swing_ranking.config import load_cohort_selected_study
from sts.swing_ranking.forward import advance_forward_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--session", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--parquet-root", required=True)
    parser.add_argument("--security-master", required=True)
    parser.add_argument("--earnings-snapshot", required=True)
    args = parser.parse_args(argv)
    study, selection = load_cohort_selected_study(
        Path(args.bundle),
        Path(args.selection),
    )
    result = advance_forward_run(
        study=study,
        selection=selection,
        output=Path(args.run),
        session=args.session,
        parquet_root=Path(args.parquet_root),
        security_master=Path(args.security_master),
        earnings_snapshot=Path(args.earnings_snapshot),
    )
    print(
        {
            "session": result.session.isoformat(),
            "session_identity": result.session_identity,
            "created": result.created,
            "candidates": result.candidate_count,
            "filled_orders": result.filled_order_count,
            "closed_trades": result.closed_trade_count,
        },
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
