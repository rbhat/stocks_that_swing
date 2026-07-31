"""Allowlisted operational settings, stored in configs/dashboard_settings.yaml.

The hardcoded SAFE_SCHEMA is the entire editable surface — strategy/prereg
configs are permanently read-only from the dashboard. Writes are atomic
(tmp + rename). Pipeline consumption of these settings is out of scope; the
file format is the contract.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

# key -> (type, validator, human description of the constraint)
SAFE_SCHEMA: dict[str, dict] = {
    "discord_alerts": {"type": bool, "check": lambda v: True, "constraint": "bool"},
    "monitor_gap_alert_pct": {
        "type": float,
        "check": lambda v: 0 < v <= 0.5,
        "constraint": "float, 0 < x <= 0.5",
    },
    "monitor_dd_alert_pct": {
        "type": float,
        "check": lambda v: 0 < v <= 0.5,
        "constraint": "float, 0 < x <= 0.5",
    },
}


def settings_path(repo_root: Path) -> Path:
    return Path(repo_root) / "configs" / "dashboard_settings.yaml"


def read_settings(repo_root: Path) -> dict:
    path = settings_path(repo_root)
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def validate(updates: dict) -> list[str]:
    """Return a list of violation messages (empty = valid)."""
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


def apply_updates(repo_root: Path, updates: dict) -> tuple[dict, dict]:
    """Validated-updates writer: atomic tmp+rename. Returns (old, new)
    full settings dicts. Caller must have run validate() first."""
    old = read_settings(repo_root)
    new = dict(old)
    for key, value in updates.items():
        if SAFE_SCHEMA[key]["type"] is float:
            value = float(value)
        new[key] = value
    path = settings_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(yaml.safe_dump(new, sort_keys=True))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return old, new
