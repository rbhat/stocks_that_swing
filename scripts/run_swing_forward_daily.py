"""Fetch one completed session and advance the sealed forward run once."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("configs/swing_ranking_v1/study_bundle.json"),
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=Path("configs/swing_ranking_v1/oos_cohort_selection.json"),
    )
    parser.add_argument(
        "--run",
        type=Path,
        default=Path("runs/swing-ranking-v1-forward-01"),
    )
    parser.add_argument(
        "--security-master",
        type=Path,
        default=Path("configs/swing_ranking_v1/security_master.json"),
    )
    parser.add_argument(
        "--price-root",
        type=Path,
        default=Path("cache/swing_forward_inputs/prices"),
    )
    parser.add_argument(
        "--earnings-raw-root",
        type=Path,
        default=Path("cache/swing_forward_inputs/raw/earnings"),
    )
    parser.add_argument(
        "--earnings-snapshot-root",
        type=Path,
        default=Path("configs/swing_ranking_v1/upcoming_earnings_snapshots"),
    )
    parser.add_argument(
        "--earnings-calendar",
        type=Path,
        default=Path("configs/swing_ranking_v1/upcoming_earnings_calendar.json"),
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("logs/swing-forward.lock"),
    )
    parser.add_argument("--session", type=dt.date.fromisoformat)
    return parser


def _read_state(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"forward state must be an object: {path}")
    return value


def _run(argv: list[str]) -> None:
    print(f"running: {' '.join(argv)}", flush=True)
    subprocess.run(argv, cwd=ROOT, check=True)


def _sync_forward() -> None:
    _run([sys.executable, "scripts/sync_swing_artifacts.py", "--forward-only"])


@contextmanager
def _single_writer(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another forward writer is already running") from exc
        yield


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with _single_writer(args.lock):
        state = _read_state(args.run / "state.json")
        expected_value = state.get("next_eligible_signal_session")
        if not isinstance(expected_value, str):
            raise TypeError("forward state lacks next_eligible_signal_session")
        expected = dt.date.fromisoformat(expected_value)
        session = args.session or calendar.last_completed_session()
        if session < expected:
            print(
                f"no-op: latest completed session {session} precedes expected {expected}",
                flush=True,
            )
            _sync_forward()
            return 0
        if session > expected:
            raise RuntimeError(
                f"no-backfill run expected {expected}, but latest completed session is {session}"
            )

        price_dir = args.price_root / session.isoformat()
        snapshot = args.earnings_snapshot_root / f"{session.isoformat()}.json"
        _run(
            [
                sys.executable,
                "scripts/fetch_swing_forward_prices.py",
                "--security-master",
                str(args.security_master),
                "--session",
                session.isoformat(),
                "--output-root",
                str(args.price_root),
            ]
        )
        if snapshot.is_file():
            print(f"earnings snapshot already exists: {snapshot}", flush=True)
        else:
            _run(
                [
                    sys.executable,
                    "scripts/build_earnings_inputs.py",
                    "--security-master",
                    str(args.security_master),
                    "--raw-dir",
                    str(args.earnings_raw_root),
                    "--snapshot-output",
                    str(snapshot),
                    "--calendar-output",
                    str(args.earnings_calendar),
                    "--coverage-start",
                    session.isoformat(),
                    "--coverage-end-exclusive",
                    (session + dt.timedelta(days=370)).isoformat(),
                    "--snapshot-date",
                    session.isoformat(),
                ]
            )
        _run(
            [
                sys.executable,
                "scripts/advance_swing_forward.py",
                "--bundle",
                str(args.bundle),
                "--selection",
                str(args.selection),
                "--run",
                str(args.run),
                "--session",
                session.isoformat(),
                "--parquet-root",
                str(price_dir),
                "--security-master",
                str(args.security_master),
                "--earnings-snapshot",
                str(snapshot),
            ]
        )
        _sync_forward()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
