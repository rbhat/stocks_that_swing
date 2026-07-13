"""Google Drive sync for the forward-paper pipeline.

WHY: the ledgers' remote copy on Drive is the SOURCE OF TRUTH — it may hold
rows written by another machine/run that never reached this local copy.
Sync is therefore merge-only in both directions for ledger files: download
the remote copy, union it with the local copy (remote wins content
collisions, see `journal.merge_lines`), verify no remote line was lost
(the safety invariant), write the merged result locally, then upload it.
A destructive overwrite of the remote copy is never possible by construction
— the only upload is a strict superset of what was just downloaded.

Backtest artifacts (`runs/`, `docs/preregs`) are pushed one-way with a plain
`rclone copy` (adds/updates only, never deletes) since they have no local/
remote reconciliation need — the backtest folder is a write-mostly archive.

Every failure (rclone or safety-check) is alerted via Discord and swallowed:
`run_daily_sync` never raises, so a sync outage never fails the EOD job that
calls it.

KNOWN LIMITATION (TOCTOU): between the download (step 1) and the upload
(step 5) another writer could append to the remote copy; that append would
be clobbered by our upload, which is a superset only of what we downloaded.
This is inherent to file-level sync. The deployment assumption is a single
writer per book — one machine runs the forward jobs for a given ledger root
— so no concurrent remote appends occur in practice.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from sts.forward import alerts
from sts.forward.journal import merge_lines
from sts.forward.ledger import LedgerPaths

logger = logging.getLogger(__name__)

FORWARD_FOLDER_ID = "1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5"
BACKTEST_FOLDER_ID = "1i11V4ooDMRQbbVSkwzwbFr7lKlOoNcEQ"

RCLONE_BIN = "rclone"
# rclone exit codes meaning "the requested remote object does not exist":
# 3 = directory not found, 4 = file not found. Only these mean fresh start;
# any other non-zero exit is a real failure and must fail CLOSED (raise),
# never be misread as an empty remote.
_RCLONE_NOT_FOUND_EXITS = frozenset({3, 4})


def _remote() -> str:
    return os.environ.get("STS_RCLONE_REMOTE", "gdrive:")


class SyncError(RuntimeError):
    """Raised when a merge would drop a remote line; the caller must not
    upload in this state."""


def _rc(args: list[str], folder_id: str, dry_run: bool = False) -> subprocess.CompletedProcess:
    cmd = [RCLONE_BIN, *args, "--drive-root-folder-id", folder_id, "--retries", "3"]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """tmp+rename+fsync, mirroring Journal.append's durability contract."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(line + "\n" for line in lines if line)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text().splitlines() if ln]


def _family_key(rec: dict) -> Any:
    return (rec.get("entry_id"), rec.get("seq"))


def _equity_key(rec: dict) -> Any:
    return (str(rec.get("date")), rec.get("book"))


def _signals_key(rec: dict) -> Any:
    entry_id = rec.get("entry_id")
    if entry_id is not None:
        return (str(rec.get("signal_date")), rec.get("book"), entry_id)
    # missed_session/upkeep_done records carry no entry_id — fall back to a
    # key built from whatever identifying fields they do carry, and as a
    # last resort the raw sorted-JSON line so the key function is total and
    # never raises (a genuinely unparseable record would already have
    # failed json.loads upstream in merge_lines).
    return (
        str(rec.get("signal_date")),
        rec.get("book"),
        rec.get("kind"),
        rec.get("date"),
        json.dumps(rec, sort_keys=True, default=str),
    )


_LEDGER_FILES: tuple[tuple[str, Callable[[dict], Any]], ...] = (
    ("h1.jsonl", _family_key),
    ("h2.jsonl", _family_key),
    ("equity.jsonl", _equity_key),
    ("signals.jsonl", _signals_key),
)


def _download_remote(filename: str, tmp_dir: Path) -> list[str]:
    """Download the remote copy into tmp_dir. Downloads are non-destructive
    and therefore run even under --dry-run (the merge/safety check must see
    real remote content). Fails CLOSED: only a not-found exit (3/4) means
    fresh start; any other non-zero exit raises SyncError so a transient
    rclone failure can never be misread as an empty remote."""
    dest = tmp_dir / f"{filename}.remote"
    result = _rc(["copyto", f"{_remote()}:{filename}", str(dest)], FORWARD_FOLDER_ID)
    if result.returncode in _RCLONE_NOT_FOUND_EXITS:
        logger.info("sync: remote %s not found — treating as empty (fresh start)", filename)
        return []
    if result.returncode != 0:
        raise SyncError(
            f"rclone copyto for {filename} failed (exit {result.returncode}): {result.stderr}"
        )
    if not dest.exists():
        # exit 0 but nothing written (e.g. zero-byte remote quirk) — safe
        # to treat as empty only because rclone itself reported success.
        return []
    return _read_lines(dest)


def _sync_one_file(filename: str, key_fn: Callable[[dict], Any], paths: LedgerPaths,
                    tmp_dir: Path, dry_run: bool) -> str:
    local_path = paths.root / filename
    # Download is non-destructive (into tmp) and runs even under dry_run so
    # the merge + safety check below validate against REAL remote content;
    # only the local write and upload are skipped in dry-run mode.
    remote_lines = _download_remote(filename, tmp_dir)
    local_lines = _read_lines(local_path)

    merged = merge_lines(remote_lines, local_lines, key_fn)

    # SAFETY INVARIANT: every remote line's key must survive the merge.
    # Content may be superseded (remote wins on collision anyway, so this
    # should be a no-op check), but a KEY present remotely must be present
    # in the merged set — losing one would mean we're about to upload a
    # file that has silently dropped a remote row.
    remote_keys = {key_fn(json.loads(line)) for line in remote_lines}
    merged_keys = {key_fn(json.loads(line)) for line in merged}
    missing = remote_keys - merged_keys
    if missing:
        raise SyncError(
            f"sync safety check failed for {filename}: {len(missing)} remote key(s) "
            f"would be lost in merge: {sorted(map(str, missing))[:5]}"
        )

    if dry_run:
        return "dry-run"

    _atomic_write_lines(local_path, merged)
    result = _rc(["copyto", str(local_path), f"{_remote()}:{filename}"], FORWARD_FOLDER_ID)
    if result.returncode != 0:
        raise SyncError(
            f"rclone copyto upload for {filename} failed (exit {result.returncode}): {result.stderr}"
        )
    return "synced"


def sync_ledgers(paths: LedgerPaths, dry_run: bool = False) -> dict[str, str]:
    """Merge-only sync of the four ledger files with the remote copy.
    Returns {filename: outcome} where outcome is one of "synced",
    "dry-run", or "error: <message>". Never raises — a per-file SyncError
    (or rclone failure) is caught, alerted, and recorded, but does not stop
    the remaining files from syncing."""
    outcomes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="sts-sync-") as tmp:
        tmp_dir = Path(tmp)
        for filename, key_fn in _LEDGER_FILES:
            try:
                outcomes[filename] = _sync_one_file(filename, key_fn, paths, tmp_dir, dry_run)
            except Exception as exc:  # noqa: BLE001 — any failure is alerted, never fatal
                logger.error("sync: %s failed: %s", filename, exc)
                alerts.send(f"forward sync FAILED for {filename}: {exc}")
                outcomes[filename] = f"error: {exc}"
    return outcomes


def push_backtest_artifacts(dry_run: bool = False) -> dict[str, str]:
    """One-way `rclone copy` of runs/ and docs/preregs to the backtest
    folder — adds/updates only, never deletes. Never raises."""
    outcomes: dict[str, str] = {}
    for local_dir, remote_dir in (("runs", "runs"), ("docs/preregs", "preregs")):
        try:
            if not Path(local_dir).exists():
                outcomes[local_dir] = "skipped: local dir absent"
                continue
            result = _rc(
                ["copy", local_dir, f"{_remote()}:{remote_dir}"], BACKTEST_FOLDER_ID, dry_run=dry_run
            )
            if result.returncode != 0:
                raise SyncError(
                    f"rclone copy {local_dir} -> {remote_dir} failed "
                    f"(exit {result.returncode}): {result.stderr}"
                )
            outcomes[local_dir] = "dry-run" if dry_run else "synced"
        except Exception as exc:  # noqa: BLE001 — alerted, never fatal
            logger.error("push_backtest_artifacts: %s failed: %s", local_dir, exc)
            alerts.send(f"backtest artifact push FAILED for {local_dir}: {exc}")
            outcomes[local_dir] = f"error: {exc}"
    return outcomes


def run_daily_sync(paths: LedgerPaths | None = None, dry_run: bool = False) -> dict[str, dict[str, str]]:
    """sync_ledgers + push_backtest_artifacts. Every sub-step's failures
    are caught and alerted inside those functions already; this wrapper
    additionally guarantees run_daily_sync itself never raises, so a caller
    (the EOD job) can treat sync as alerted-but-nonfatal."""
    if paths is None:
        paths = LedgerPaths()
    result: dict[str, dict[str, str]] = {}
    try:
        result["ledgers"] = sync_ledgers(paths, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders, sync_ledgers already catches
        logger.error("run_daily_sync: sync_ledgers raised unexpectedly: %s", exc)
        alerts.send(f"forward sync FAILED (ledgers): {exc}")
        result["ledgers"] = {"error": str(exc)}
    try:
        result["backtest"] = push_backtest_artifacts(dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        logger.error("run_daily_sync: push_backtest_artifacts raised unexpectedly: %s", exc)
        alerts.send(f"forward sync FAILED (backtest artifacts): {exc}")
        result["backtest"] = {"error": str(exc)}
    return result
