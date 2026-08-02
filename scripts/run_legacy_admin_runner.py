#!/usr/bin/env python
"""Internal-only sidecar for two bounded legacy admin operations.

This file is mounted into the retained legacy image, whose fixed sync command
is ``/app/scripts/forward_sync.py``. It exposes no host port, accepts one
shared-token header, and cannot dispatch arbitrary commands.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any

import uvicorn
import yaml
from fastapi import Body, FastAPI, Header, HTTPException

ROOT = Path("/app")
LOG_ROOT = ROOT / "logs" / "dashboard"
SYNC_COMMAND = (sys.executable, "/app/scripts/forward_sync.py")
STALE_LOCK_SECONDS = 30 * 60

SAFE_SCHEMA: dict[str, dict[str, Any]] = {
    "discord_alerts": {"type": bool, "check": lambda value: True, "constraint": "bool"},
    "monitor_gap_alert_pct": {
        "type": float,
        "check": lambda value: 0 < value <= 0.5,
        "constraint": "float, 0 < x <= 0.5",
    },
    "monitor_dd_alert_pct": {
        "type": float,
        "check": lambda value: 0 < value <= 0.5,
        "constraint": "float, 0 < x <= 0.5",
    },
}

app = FastAPI(title="Legacy admin runner", docs_url=None, redoc_url=None, openapi_url=None)


def _authorize(token: str | None) -> None:
    expected = os.environ.get("LEGACY_ADMIN_TOKEN")
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="forbidden")


def _validate(updates: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, value in updates.items():
        spec = SAFE_SCHEMA.get(key)
        if spec is None:
            errors.append(f"unknown key: {key}")
            continue
        expected = spec["type"]
        if expected is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{key}: expected {spec['constraint']}")
                continue
            value = float(value)
        elif not isinstance(value, expected):
            errors.append(f"{key}: expected {spec['constraint']}")
            continue
        if not spec["check"](value):
            errors.append(f"{key}: out of range ({spec['constraint']})")
    return errors


def _read_settings() -> dict[str, Any]:
    path = ROOT / "configs" / "dashboard_settings.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_settings(updates: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = ROOT / "configs" / "dashboard_settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = LOG_ROOT / "config.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = _read_settings()
        new = dict(old)
        for key, value in updates.items():
            new[key] = float(value) if SAFE_SCHEMA[key]["type"] is float else value
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(yaml.safe_dump(new, sort_keys=True))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return old, new


def _state_path(sync_id: str) -> Path:
    return LOG_ROOT / f"sync-{sync_id}.json"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_state(sync_id: str, status: str, **extra: Any) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    record = {
        "id": sync_id,
        "status": status,
        "updated_at": dt.datetime.now(dt.UTC).isoformat(),
        **extra,
    }
    path = _state_path(sync_id)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.put("/config")
def update_config(
    updates: Annotated[dict[str, Any], Body()],
    x_legacy_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(x_legacy_admin_token)
    errors = _validate(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    old, new = _atomic_settings(updates)
    return {"old": old, "new": new}


@app.post("/sync")
def start_sync(x_legacy_admin_token: str | None = Header(default=None)) -> dict[str, str]:
    _authorize(x_legacy_admin_token)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = LOG_ROOT / "sync.lock"
    if lock_path.exists():
        try:
            if dt.datetime.now(dt.UTC).timestamp() - lock_path.stat().st_mtime > STALE_LOCK_SECONDS:
                lock_path.unlink()
        except FileNotFoundError:
            pass
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="sync already running") from exc
    sync_id = uuid.uuid4().hex[:12]
    os.write(descriptor, sync_id.encode())
    os.close(descriptor)
    log_path = LOG_ROOT / f"sync-{sync_id}.log"
    try:
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            SYNC_COMMAND,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    except BaseException:
        lock_path.unlink(missing_ok=True)
        raise
    _write_state(sync_id, "running", log=str(log_path))

    def reap() -> None:
        try:
            return_code = process.wait()
            _write_state(
                sync_id,
                "ok" if return_code == 0 else "failed",
                returncode=return_code,
                log=str(log_path),
            )
        finally:
            log_handle.close()
            lock_path.unlink(missing_ok=True)

    threading.Thread(target=reap, daemon=True).start()
    return {"id": sync_id}


@app.get("/sync/{sync_id}")
def sync_status(
    sync_id: str, x_legacy_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    _authorize(x_legacy_admin_token)
    if not sync_id.isalnum() or len(sync_id) != 12:
        raise HTTPException(status_code=404, detail="unknown sync id")
    try:
        value = json.loads(_state_path(sync_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail="unknown sync id") from None
    if not isinstance(value, dict):
        raise HTTPException(status_code=404, detail="unknown sync id")
    return value


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8020)
