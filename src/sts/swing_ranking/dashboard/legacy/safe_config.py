"""Validation contract for the legacy dashboard's bounded settings surface."""

from __future__ import annotations

from typing import Any

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


def validate(updates: dict[str, Any]) -> list[str]:
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
