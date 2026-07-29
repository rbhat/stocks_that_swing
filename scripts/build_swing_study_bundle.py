"""Freeze the initial swing-ranking bundle from non-performance metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar
from sts.swing_ranking.config import load_study_bundle
from sts.swing_ranking.source_inputs import atomic_write, json_bytes, sha256_bytes
from sts.swing_ranking.study_bundle import (
    build_corporate_actions,
    build_exchange_calendar,
    build_source_hashes,
    build_study_bundle,
    derive_study_dates,
    read_roster,
    resolved_parquets_from_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--roster-manifest", type=Path, required=True)
    parser.add_argument("--security-master", type=Path, required=True)
    parser.add_argument("--symbol-history", type=Path, required=True)
    parser.add_argument("--earnings-calendar", type=Path, required=True)
    parser.add_argument("--parquet-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-cutoff", type=dt.date.fromisoformat, required=True)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace unequal derived outputs",
    )
    return parser


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def _relative(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not calendar.is_session(args.data_cutoff):
        raise SystemExit("--data-cutoff must be an XNYS session")
    roster = read_roster(args.roster)
    manifest = _read_json(args.roster_manifest, "roster manifest")
    security_master = _read_json(args.security_master, "security master")
    securities = security_master.get("securities")
    if not isinstance(securities, list) or not securities:
        raise SystemExit("security master lacks securities")
    earnings = _read_json(args.earnings_calendar, "earnings calendar")
    if not isinstance(earnings.get("coverage"), list) or not isinstance(
        earnings.get("events"),
        list,
    ):
        raise SystemExit("earnings calendar lacks coverage or events")
    evaluation_start, evaluation_end, coverage_end = derive_study_dates(
        manifest=manifest,
        data_cutoff=args.data_cutoff,
    )
    roster_manifest_bytes = args.roster_manifest.read_bytes()
    corporate_actions = build_corporate_actions(
        securities=securities,
        evaluation_start=evaluation_start,
        coverage_end_exclusive=coverage_end,
        data_cutoff=args.data_cutoff,
        roster_manifest_sha256=sha256_bytes(roster_manifest_bytes),
    )
    exchange_calendar = build_exchange_calendar(evaluation_start, coverage_end)
    corporate_actions_bytes = json_bytes(corporate_actions)
    exchange_calendar_bytes = json_bytes(exchange_calendar)
    resolved_parquets = resolved_parquets_from_manifest(
        roster=roster,
        manifest=manifest,
        securities=securities,
    )
    source_hashes = build_source_hashes(
        roster_bytes=args.roster.read_bytes(),
        security_master_bytes=args.security_master.read_bytes(),
        symbol_history_bytes=args.symbol_history.read_bytes(),
        corporate_actions_bytes=corporate_actions_bytes,
        earnings_calendar_bytes=args.earnings_calendar.read_bytes(),
        exchange_calendar_bytes=exchange_calendar_bytes,
        resolved_parquets=resolved_parquets,
    )
    roster_as_of = str(roster.get("as_of", "unknown"))
    bundle = build_study_bundle(
        source_hashes=source_hashes,
        evaluation_start=evaluation_start,
        evaluation_end_exclusive=evaluation_end,
        data_cutoff=args.data_cutoff,
        coverage_end_exclusive=coverage_end,
        roster_as_of=roster_as_of,
    )
    bundle_bytes = json_bytes(bundle)
    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        handle.write(bundle_bytes)
        handle.flush()
        configured = load_study_bundle(Path(handle.name))
    facts = configured.protocol.source_facts
    source_manifest = {
        "schema_version": "swing-ranking-v1.source-manifest.v1",
        "sources": {
            fact.kind: {
                "content_sha256": fact.content_hash,
                "as_of": fact.as_of.isoformat(),
                "coverage_start": fact.coverage_start.isoformat(),
                "coverage_end_exclusive": fact.coverage_end_exclusive.isoformat(),
                "adjustment_basis": fact.adjustment_basis,
            }
            for fact in facts
        },
    }
    output_dir = args.output_dir.resolve()
    preflight_paths = {
        "roster": _relative(args.roster, output_dir),
        "roster_manifest": _relative(args.roster_manifest, output_dir),
        "source_manifest": "source_manifest.json",
        "security_master": _relative(args.security_master, output_dir),
        "symbol_history": _relative(args.symbol_history, output_dir),
        "corporate_actions": "corporate_actions.json",
        "earnings_calendar": _relative(args.earnings_calendar, output_dir),
        "exchange_calendar": "exchange_calendar.json",
        "parquet_root": _relative(args.parquet_root, output_dir),
    }
    outputs = {
        output_dir / "corporate_actions.json": corporate_actions_bytes,
        output_dir / "exchange_calendar.json": exchange_calendar_bytes,
        output_dir / "source_manifest.json": json_bytes(source_manifest),
        output_dir / "study_bundle.json": bundle_bytes,
        output_dir / "preflight_paths.json": json_bytes(preflight_paths),
    }
    for path, content in outputs.items():
        atomic_write(path, content, replace=args.replace)
    print(
        f"strategies={len(configured.strategies)} "
        f"evaluation={evaluation_start}/{evaluation_end} "
        f"cutoff={args.data_cutoff} "
        f"protocol_identity={configured.protocol.identity} "
        f"bundle={output_dir / 'study_bundle.json'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
