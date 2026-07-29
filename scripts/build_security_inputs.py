"""Build permanent-ID security-master inputs from the frozen roster."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.swing_ranking.source_inputs import (
    atomic_write,
    fetch_openfigi_mappings,
    json_bytes,
    normalize_security_inputs,
    roster_symbols,
    sha256_bytes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--roster-manifest", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--security-master-output", type=Path, required=True)
    parser.add_argument("--symbol-history-output", type=Path, required=True)
    parser.add_argument("--coverage-end-exclusive", type=dt.date.fromisoformat, required=True)
    parser.add_argument(
        "--retrieved-at",
        help="explicit ISO timestamp; defaults to current UTC",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENFIGI_API_KEY",
        help="optional OpenFIGI API-key environment variable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    retrieved_at = args.retrieved_at or dt.datetime.now(dt.UTC).isoformat()
    symbols = roster_symbols(args.roster)
    try:
        manifest = json.loads(args.roster_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"roster manifest is unreadable: {exc}") from exc
    if args.raw_output.is_file():
        try:
            raw_document = json.loads(args.raw_output.read_text(encoding="utf-8"))
            archives = raw_document["batches"]
            results = tuple(
                result
                for batch in archives
                for result in batch["response"]
            )
            retrieved_at = raw_document["retrieved_at"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SystemExit(f"OpenFIGI raw archive is malformed: {exc}") from exc
        raw = args.raw_output.read_bytes()
    else:
        api_key = os.environ.get(args.api_key_env)
        archives, results = fetch_openfigi_mappings(symbols, api_key=api_key)
        raw_document = {
            "schema_version": "swing-ranking-v1.openfigi-archive.v1",
            "endpoint": "https://api.openfigi.com/v3/mapping",
            "retrieved_at": retrieved_at,
            "batches": archives,
        }
        raw = json_bytes(raw_document)
        atomic_write(args.raw_output, raw, replace=False)
    raw_sha256 = sha256_bytes(raw)
    security_master, symbol_history = normalize_security_inputs(
        symbols=symbols,
        mapping_results=results,
        roster_manifest=manifest,
        raw_sha256=raw_sha256,
        retrieved_at=retrieved_at,
        coverage_end_exclusive=args.coverage_end_exclusive,
    )
    atomic_write(
        args.security_master_output,
        json_bytes(security_master),
        replace=True,
    )
    atomic_write(
        args.symbol_history_output,
        json_bytes(symbol_history),
        replace=True,
    )
    print(
        f"resolved={len(symbols)} raw_sha256={raw_sha256} "
        f"security_master={args.security_master_output} "
        f"symbol_history={args.symbol_history_output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
