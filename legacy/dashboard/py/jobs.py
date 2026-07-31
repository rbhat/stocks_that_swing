"""Job status from logs + hardcoded cron spec; locked sync-on-demand runner.

Cron spec mirrors the FORWARD_OPS schedule (PT / America/Los_Angeles,
weekdays): eod 17:30, fill 06:31, monitor 05:35-13:35 at :35, sync runs as
step 6 of eod (not scheduled standalone -> next_run None).

Logs: `logs/forward/{name}.log` (laptop launchd layout) with fallback
`logs/{name}.log` (VM cron layout). Missing log -> status "unknown".
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
STALE_LOCK_SECONDS = 30 * 60

# name -> (minute, hours tuple) fired Mon-Fri PT; None = not scheduled.
CRON_SPEC: dict[str, tuple[int, tuple[int, ...]] | None] = {
    "eod": (30, (17,)),
    "fill": (31, (6,)),
    "monitor": (35, (5, 6, 7, 8, 9, 10, 11, 12, 13)),
    "sync": None,  # step 6 of eod, not scheduled standalone
}

_SUCCESS_MARKERS = ("complete", "done —", "done -", "already processed", "nothing to do")
_FAILURE_MARKERS = ("fatal error", "Traceback (most recent call last)")


class SyncInProgress(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# job status
# ---------------------------------------------------------------------------


def _log_path(repo_root: Path, name: str) -> Path | None:
    for candidate in (
        repo_root / "logs" / "forward" / f"{name}.log",
        repo_root / "logs" / f"{name}.log",
    ):
        if candidate.exists():
            return candidate
    return None


def _tail(path: Path, n: int = 50) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _next_run(spec: tuple[int, tuple[int, ...]] | None, now: dt.datetime | None = None) -> str | None:
    if spec is None:
        return None
    minute, hours = spec
    now = now or dt.datetime.now(PT)
    t = now.replace(second=0, microsecond=0)
    for _ in range(14 * 24 * 60):  # bounded scan, minute resolution
        t += dt.timedelta(minutes=1)
        if t.weekday() < 5 and t.minute == minute and t.hour in hours:
            return t.isoformat()
    return None


def job_status(repo_root: Path) -> list[dict]:
    repo_root = Path(repo_root)
    out: list[dict] = []
    for name, spec in CRON_SPEC.items():
        rec: dict = {"name": name, "next_run": _next_run(spec)}
        path = _log_path(repo_root, name)
        if path is None:
            rec.update(status="unknown", last_run=None)
            out.append(rec)
            continue
        lines = _tail(path)
        # last marker (success or failure) wins
        status = "unknown"
        for line in lines:
            if any(m in line for m in _FAILURE_MARKERS):
                status = "failed"
            elif any(m in line for m in _SUCCESS_MARKERS):
                status = "ok"
        rec.update(
            status=status,
            last_run=dt.datetime.fromtimestamp(path.stat().st_mtime, tz=PT).isoformat(),
        )
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# sync-on-demand
# ---------------------------------------------------------------------------


def _lock_path(repo_root: Path) -> Path:
    return Path(repo_root) / "logs" / "dashboard-sync.lock"


def _state_path(repo_root: Path, sync_id: str) -> Path:
    return Path(repo_root) / "logs" / f"dashboard-sync-{sync_id}.json"


def _write_state(repo_root: Path, sync_id: str, status: str, **extra) -> None:
    rec = {"id": sync_id, "status": status, "updated_at": dt.datetime.now(dt.UTC).isoformat()}
    rec.update(extra)
    _state_path(repo_root, sync_id).write_text(json.dumps(rec, sort_keys=True))


def sync_state(repo_root: Path, sync_id: str) -> dict | None:
    path = _state_path(repo_root, sync_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def start_sync(repo_root: Path) -> str:
    """Launch scripts/forward_sync.py in the background. Returns sync id.
    Raises SyncInProgress if the lock is held (and not stale)."""
    repo_root = Path(repo_root)
    lock = _lock_path(repo_root)
    lock.parent.mkdir(parents=True, exist_ok=True)

    # break a stale lock (holder crashed without cleanup)
    if lock.exists():
        try:
            age = dt.datetime.now().timestamp() - lock.stat().st_mtime
            if age > STALE_LOCK_SECONDS:
                lock.unlink()
        except FileNotFoundError:
            pass

    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SyncInProgress("a sync is already running")
    sync_id = uuid.uuid4().hex[:12]
    os.write(fd, sync_id.encode())
    os.close(fd)

    out_log = repo_root / "logs" / f"dashboard-sync-{sync_id}.log"
    try:
        out_f = open(out_log, "w")
        proc = subprocess.Popen(
            [sys.executable, str(repo_root / "scripts" / "forward_sync.py")],
            cwd=repo_root,
            stdout=out_f,
            stderr=subprocess.STDOUT,
        )
    except BaseException:
        lock.unlink(missing_ok=True)
        raise
    _write_state(repo_root, sync_id, "running", log=str(out_log))

    def _reap():
        try:
            rc = proc.wait()
            _write_state(
                repo_root, sync_id, "ok" if rc == 0 else "failed", returncode=rc, log=str(out_log)
            )
        finally:
            try:
                out_f.close()
            except Exception:
                pass
            lock.unlink(missing_ok=True)

    threading.Thread(target=_reap, daemon=True).start()
    return sync_id
