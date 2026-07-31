"""Copy verified forward/backtest artifacts to their dedicated Drive roots."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sts.swing_ranking.identity import sha256_hex

FORWARD_FOLDER_ID = "1VHPM0pz_BW-48tR6vs9PFJmPJ1YGy87R"
BACKTEST_FOLDER_ID = "1sQ6LdAmvsD2-nH9kBO-s9nJrsMChHwBy"
_REMOTE_RE = re.compile(r"^[A-Za-z0-9_-]+:$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--forward-root",
        type=Path,
        default=Path("runs/swing-ranking-v1-forward-01"),
    )
    parser.add_argument(
        "--backtest-root",
        type=Path,
        default=Path("runs/swing-ranking-v1"),
    )
    parser.add_argument(
        "--remote",
        default=os.environ.get("STS_RCLONE_REMOTE", "gdrive:"),
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--forward-only", action="store_true")
    scope.add_argument("--backtest-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"manifest must be an object: {path}")
    return value


def _verify_hashes(root: Path, manifest_path: Path) -> None:
    manifest = _read_object(manifest_path)
    hashes = manifest.get("content_hashes")
    if not isinstance(hashes, dict):
        raise TypeError(f"manifest lacks content_hashes: {manifest_path}")
    for relative, expected in hashes.items():
        path = root / str(relative)
        if not path.is_file() or sha256_hex(path.read_bytes()) != expected:
            raise ValueError(f"artifact hash mismatch: {path}")


def verify_forward(root: Path) -> None:
    if not root.is_dir():
        raise ValueError(f"forward root is missing: {root}")
    _verify_hashes(root, root / "manifest.json")
    sessions = root / "sessions"
    if sessions.is_dir():
        for manifest in sorted(sessions.glob("*/manifest.json")):
            _verify_hashes(manifest.parent, manifest)


def _copy_and_check(
    *,
    source: Path,
    remote: str,
    folder_id: str,
    dry_run: bool,
) -> None:
    common = [
        "--drive-root-folder-id",
        folder_id,
        "--checksum",
        "--retries",
        "3",
        "--low-level-retries",
        "10",
    ]
    copy = ["rclone", "copy", str(source), remote, *common]
    if dry_run:
        copy.append("--dry-run")
    print(f"syncing {source} to Drive folder {folder_id}", flush=True)
    subprocess.run(copy, check=True)
    if not dry_run:
        subprocess.run(
            ["rclone", "check", str(source), remote, *common, "--one-way"],
            check=True,
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not _REMOTE_RE.fullmatch(args.remote):
        raise ValueError("--remote must be an rclone remote name ending in ':'")
    if not args.backtest_only:
        verify_forward(args.forward_root)
        _copy_and_check(
            source=args.forward_root,
            remote=args.remote,
            folder_id=FORWARD_FOLDER_ID,
            dry_run=args.dry_run,
        )
    if not args.forward_only:
        if not args.backtest_root.is_dir():
            raise ValueError(f"backtest root is missing: {args.backtest_root}")
        _copy_and_check(
            source=args.backtest_root,
            remote=args.remote,
            folder_id=BACKTEST_FOLDER_ID,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
