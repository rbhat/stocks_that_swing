"""Archive one immutable, complete 250-security forward price snapshot."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts import calendar
from sts.data.fetch import fetch_daily
from sts.data.study_store import StudyStore
from sts.swing_ranking.identity import canonical_bytes, sha256_hex
from sts.swing_ranking.source_inputs import atomic_write


def _eta(seconds: float) -> str:
    minutes, remainder = divmod(int(max(0, seconds)), 60)
    return f"{minutes}m{remainder:02d}s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument("--session", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args(argv)
    if not calendar.is_session(args.session):
        parser.error("--session must be an XNYS session")
    if args.session != calendar.last_completed_session():
        parser.error("--session must equal the latest completed XNYS session")
    master = json.loads(args.security_master.read_text(encoding="utf-8"))
    securities = master.get("securities")
    if not isinstance(securities, list) or len(securities) != 250:
        parser.error("--security-master must contain the frozen 250 securities")
    symbols = sorted(str(row["symbol"]).upper() for row in securities)
    if len(set(symbols)) != 250:
        parser.error("--security-master symbols must be unique")
    destination = args.output_root / args.session.isoformat()
    manifest_path = destination / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest.get("parquet_sha256", {})
        if (
            manifest.get("session") == args.session.isoformat()
            and isinstance(recorded, dict)
            and set(recorded) == set(symbols)
            and all(
                (destination / f"{symbol}.parquet").is_file()
                and sha256_hex((destination / f"{symbol}.parquet").read_bytes())
                == recorded[symbol]
                for symbol in symbols
            )
        ):
            print(f"snapshot already complete: {destination}", flush=True)
            return 0
        raise ValueError("existing forward price manifest is malformed")
    store = StudyStore(destination)
    started = time.monotonic()
    for index, symbol in enumerate(symbols, start=1):
        existing = store.load(symbol)
        if existing is not None and not existing.empty and existing.index[-1].date() == args.session:
            continue
        frame = fetch_daily(symbol)
        frame = frame[frame.index.date <= args.session]
        if frame.empty or frame.index[-1].date() != args.session:
            raise ValueError(f"{symbol} lacks a completed {args.session} daily bar")
        store.write(symbol, frame)
        elapsed = time.monotonic() - started
        eta = (len(symbols) - index) * elapsed / index
        if index == 1 or index % 10 == 0 or index == len(symbols):
            print(
                f"[{index}/250] {symbol} elapsed={_eta(elapsed)} ETA={_eta(eta)}",
                flush=True,
            )
        if index < len(symbols):
            time.sleep(args.sleep * random.uniform(0.75, 1.25))
    parquet_hashes = {
        symbol: sha256_hex(store.path(symbol).read_bytes()) for symbol in symbols
    }
    manifest = {
        "schema_version": "swing-ranking-v1.forward-price-snapshot.v1",
        "session": args.session,
        "security_master_sha256": sha256_hex(args.security_master.read_bytes()),
        "parquet_sha256": parquet_hashes,
    }
    atomic_write(
        manifest_path,
        canonical_bytes(manifest) + b"\n",
        replace=False,
    )
    print(f"snapshot complete: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
