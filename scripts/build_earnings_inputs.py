"""Collect archived Investing.com earnings rows and normalize causal inputs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from curl_cffi import requests

from sts.swing_ranking.source_inputs import (
    INVESTING_EARNINGS_URL,
    INVESTING_SEARCH_URL,
    SourceInputViolation,
    atomic_write,
    investing_access_token,
    investing_search_query,
    json_bytes,
    merge_earnings_snapshots,
    normalize_earnings_inputs,
    select_investing_instrument,
    sha256_bytes,
    sha256_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--security-master", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--snapshot-output", type=Path, required=True)
    parser.add_argument("--calendar-output", type=Path, required=True)
    parser.add_argument("--coverage-start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--coverage-end-exclusive", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--snapshot-date", type=dt.date.fromisoformat, required=True)
    parser.add_argument(
        "--retrieved-at",
        help="explicit ISO timestamp; defaults to current UTC",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="replace resumable raw symbol responses",
    )
    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="replace normalized outputs while preserving cached raw responses",
    )
    return parser


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceInputViolation(f"{label} is unreadable: {exc}") from exc


def _cached_or_fetch(
    *,
    path: Path,
    refresh: bool,
    fetch,
) -> object:
    if path.is_file() and not refresh:
        return _read_json(path, str(path))
    value = fetch()
    atomic_write(path, json_bytes(value), replace=refresh)
    return value


def _fmt_eta(seconds: float) -> str:
    minutes, remainder = divmod(int(max(0, seconds)), 60)
    return f"{minutes}m{remainder:02d}s"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    retrieved_at = args.retrieved_at or dt.datetime.now(dt.UTC).isoformat()
    master = _read_json(args.security_master, "security master")
    if not isinstance(master, dict) or not isinstance(master.get("securities"), list):
        raise SourceInputViolation("security master lacks securities")
    securities = tuple(master["securities"])
    session = requests.Session(impersonate="chrome")
    token, calendar_page = investing_access_token(session)
    headers = {"Authorization": f"Bearer {token}", "domain-id": "www"}
    raw_root = args.raw_dir / args.snapshot_date.isoformat()
    raw_root.mkdir(parents=True, exist_ok=True)
    page_hash = sha256_bytes(calendar_page)

    instruments: list[dict[str, object]] = []
    earnings_by_id: dict[int, tuple[dict[str, object], ...]] = {}
    started = time.monotonic()
    for index, security in enumerate(securities, start=1):
        symbol = str(security["symbol"])
        search_query = investing_search_query(symbol)
        search_path = raw_root / "search" / f"{symbol}.json"

        def fetch_search(
            query: str = search_query,
            requested_symbol: str = symbol,
        ) -> object:
            response = session.get(
                INVESTING_SEARCH_URL,
                params={"q": query},
                headers={"domain-id": "www"},
                timeout=30,
            )
            if response.status_code != 200:
                raise SourceInputViolation(
                    f"Investing.com search for {requested_symbol} failed with "
                    f"HTTP {response.status_code}"
                )
            return response.json()

        search = _cached_or_fetch(
            path=search_path,
            refresh=args.refresh,
            fetch=fetch_search,
        )
        instrument = select_investing_instrument(symbol, search)
        instruments.append(instrument)
        instrument_id = int(instrument["investing_instrument_id"])
        earnings_path = raw_root / "earnings" / f"{symbol}.json"

        def fetch_earnings(
            requested_id: int = instrument_id,
            requested_symbol: str = symbol,
        ) -> object:
            response = session.get(
                f"{INVESTING_EARNINGS_URL}/v1/instruments/{requested_id}/earnings",
                params={"limit": 100},
                headers=headers,
                timeout=30,
            )
            if response.status_code != 200:
                raise SourceInputViolation(
                    f"Investing.com earnings for {requested_symbol} failed with "
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            return response.json()

        earnings = _cached_or_fetch(
            path=earnings_path,
            refresh=args.refresh,
            fetch=fetch_earnings,
        )
        if not isinstance(earnings, dict) or not isinstance(earnings.get("earnings"), list):
            raise SourceInputViolation(f"earnings response for {symbol} is malformed")
        earnings_by_id[instrument_id] = tuple(earnings["earnings"])
        elapsed = time.monotonic() - started
        eta = (len(securities) - index) * elapsed / index
        if index == 1 or index % 25 == 0 or index == len(securities):
            print(
                f"[{index}/{len(securities)}] {symbol} "
                f"elapsed={_fmt_eta(elapsed)} ETA={_fmt_eta(eta)}",
                flush=True,
            )

    files = sorted(
        path
        for path in raw_root.rglob("*.json")
        if path.is_file() and path.name != "inventory.json"
    )
    file_hashes = {
        path.relative_to(raw_root).as_posix(): sha256_file(path)
        for path in files
    }
    archive_content = {"files": file_hashes}
    inventory_sha = sha256_bytes(json_bytes(archive_content, pretty=False))
    inventory = {
        "schema_version": "swing-ranking-v1.investing-archive.v1",
        "retrieved_at": retrieved_at,
        "snapshot_date": args.snapshot_date.isoformat(),
        "calendar_page_sha256": page_hash,
        "archive_content_sha256": inventory_sha,
        "files": file_hashes,
    }
    inventory_raw = json_bytes(inventory)
    atomic_write(raw_root / "inventory.json", inventory_raw, replace=True)
    normalized = normalize_earnings_inputs(
        securities=securities,
        instruments=instruments,
        earnings_by_instrument=earnings_by_id,
        raw_sha256=inventory_sha,
        retrieved_at=retrieved_at,
        snapshot_date=args.snapshot_date,
        coverage_start=args.coverage_start,
        coverage_end_exclusive=args.coverage_end_exclusive,
    )
    snapshot_raw = json_bytes(normalized)
    atomic_write(
        args.snapshot_output,
        snapshot_raw,
        replace=args.replace_output,
    )
    snapshot_documents = [
        _read_json(path, str(path))
        for path in sorted(args.snapshot_output.parent.glob("*.json"))
    ]
    consolidated = merge_earnings_snapshots(snapshot_documents)
    atomic_write(
        args.calendar_output,
        json_bytes(consolidated),
        replace=True,
    )
    print(
        f"events={len(normalized['events'])} raw_sha256={inventory_sha} "
        f"snapshot={args.snapshot_output} calendar={args.calendar_output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
