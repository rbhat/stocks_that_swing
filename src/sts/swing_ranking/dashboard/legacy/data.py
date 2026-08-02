"""Defensive, read-only readers for the retired H1/H2 dashboard data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from sts.swing_ranking.dashboard.legacy import LegacyRoots

_ENV_ALLOWLIST = {"TZ", "DASHBOARD_PORT"}
_REDACTED = "•••"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read valid object rows, skipping missing, unreadable, and corrupt data."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def equity_series(ledger_root: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(Path(ledger_root) / "equity.jsonl")
    return sorted(rows, key=lambda row: (str(row.get("book", "")), str(row.get("date", ""))))


def family_rows(ledger_root: Path, family: str) -> list[dict[str, Any]]:
    return read_jsonl(Path(ledger_root) / f"{family}.jsonl")


def _latest_state(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry_id = row.get("entry_id")
        if entry_id is None:
            continue
        key = str(entry_id)
        if key not in latest or _sequence(row) > _sequence(latest[key]):
            latest[key] = row
    return latest


def _sequence(row: dict[str, Any]) -> float:
    value = row.get("seq", 0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def open_positions(ledger_root: Path) -> list[dict[str, Any]]:
    rows = family_rows(ledger_root, "h1") + family_rows(ledger_root, "h2")
    return [row for row in _latest_state(rows).values() if row.get("status") == "open"]


def overview_stats(ledger_root: Path) -> dict[str, Any]:
    rows = family_rows(ledger_root, "h1") + family_rows(ledger_root, "h2")
    latest = list(_latest_state(rows).values())
    opened = [row for row in latest if row.get("status") == "open"]
    closed = [row for row in latest if row.get("status") == "closed"]

    def number(value: Any) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    total_pnl = sum(number(row.get("pnl_usd")) for row in closed)
    wins = sum(1 for row in closed if number(row.get("pnl_usd")) > 0)
    return {
        "total_pnl": total_pnl,
        "open_count": len(opened),
        "usd_deployed": sum(number(row.get("usd_deployed")) for row in opened),
        "win_rate": wins / len(closed) if closed else None,
    }


def signals(ledger_root: Path, limit: int = 200) -> list[dict[str, Any]]:
    return read_jsonl(Path(ledger_root) / "signals.jsonl")[-limit:]


def _read_yaml(path: Path) -> Any | None:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _read_env(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            result[key] = value if key in _ENV_ALLOWLIST else _REDACTED
    return result


def config_view(roots: LegacyRoots) -> dict[str, Any]:
    return {
        "universe": _read_yaml(roots.configs.parent / "universe.yaml"),
        "study_roster": _read_yaml(roots.configs / "study_roster.yaml"),
        "env": _read_env(roots.env_file),
    }


def read_settings(configs_root: Path) -> dict[str, Any]:
    value = _read_yaml(Path(configs_root) / "dashboard_settings.yaml")
    return value if isinstance(value, dict) else {}


def runs_summary(runs_summary_root: Path) -> dict[str, dict[str, Any]]:
    root = Path(runs_summary_root)
    if not root.is_dir():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            result[path.stem] = value
    return result


def runs_summary_family(runs_summary_root: Path, family: str) -> dict[str, Any] | None:
    return runs_summary(runs_summary_root).get(family)
