"""Read legacy cron health without importing or invoking either scheduler."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

CRON_SPEC: dict[str, tuple[int, tuple[int, ...]] | None] = {
    "eod": (30, (17,)),
    "fill": (31, (6,)),
    "monitor": (35, (5, 6, 7, 8, 9, 10, 11, 12, 13)),
    "sync": None,
}

_SUCCESS_MARKERS = ("complete", "done —", "done -", "already processed", "nothing to do")
_FAILURE_MARKERS = ("fatal error", "Traceback (most recent call last)")


def _log_path(logs_root: Path, name: str) -> Path | None:
    for path in (Path(logs_root) / "forward" / f"{name}.log", Path(logs_root) / f"{name}.log"):
        if path.is_file():
            return path
    return None


def _next_run(
    spec: tuple[int, tuple[int, ...]] | None, now: dt.datetime | None = None
) -> str | None:
    if spec is None:
        return None
    minute, hours = spec
    current = (now or dt.datetime.now(PT)).replace(second=0, microsecond=0)
    for _ in range(14 * 24 * 60):
        current += dt.timedelta(minutes=1)
        if current.weekday() < 5 and current.minute == minute and current.hour in hours:
            return current.isoformat()
    return None


def job_status(logs_root: Path) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []
    for name, spec in CRON_SPEC.items():
        record: dict[str, str | None] = {"name": name, "next_run": _next_run(spec)}
        path = _log_path(logs_root, name)
        if path is None:
            record.update(status="unknown", last_run=None)
            result.append(record)
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
            modified = path.stat().st_mtime
        except OSError:
            lines = []
            modified = 0
        status = "unknown"
        for line in lines:
            if any(marker in line for marker in _FAILURE_MARKERS):
                status = "failed"
            elif any(marker in line for marker in _SUCCESS_MARKERS):
                status = "ok"
        record.update(
            status=status,
            last_run=dt.datetime.fromtimestamp(modified, tz=PT).isoformat() if modified else None,
        )
        result.append(record)
    return result
