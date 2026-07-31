"""Defensive read layer for the dashboard: ledger rows, equity, signals,
configs, and exported runs-summary artifacts.

Every function here is read-only and tolerant of missing/corrupt files —
missing directories/files yield empty results, never an exception. This
module must NOT instantiate `sts.forward.ledger.Ledger` (the writing
ledger); it reimplements the read/replay semantics it needs directly on
top of `sts.forward.journal`-style JSONL files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_ENV_ALLOWLIST = {"TZ", "DASHBOARD_PORT"}
_REDACTED = "•••"  # "•••"


def read_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, skipping any line that fails to parse. Missing
    file -> empty list."""
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return rows


def equity_series(root: Path) -> list[dict]:
    """Rows from `equity.jsonl`, sorted by (book, date)."""
    root = Path(root)
    rows = read_jsonl(root / "equity.jsonl")
    return sorted(rows, key=lambda r: (str(r.get("book", "")), str(r.get("date", ""))))


def family_rows(root: Path, family: str) -> list[dict]:
    """Raw rows from `{family}.jsonl` (family in {'h1', 'h2'})."""
    root = Path(root)
    return read_jsonl(root / f"{family}.jsonl")


def _latest_state(rows: list[dict]) -> dict[str, dict]:
    """entry_id -> latest row (max seq), mirroring Ledger.state()."""
    latest: dict[str, dict] = {}
    for r in rows:
        eid = r.get("entry_id")
        if eid is None:
            continue
        if eid not in latest or r.get("seq", 0) > latest[eid].get("seq", 0):
            latest[eid] = r
    return latest


def open_positions(root: Path) -> list[dict]:
    """Latest row per entry_id across h1.jsonl + h2.jsonl, kept when
    status == 'open' — a read-only mirror of Ledger.open_rows()."""
    root = Path(root)
    rows = read_jsonl(root / "h1.jsonl") + read_jsonl(root / "h2.jsonl")
    latest = _latest_state(rows)
    return [r for r in latest.values() if r.get("status") == "open"]


def overview_stats(root: Path) -> dict:
    """Stat tiles: total realized P&L, open count, USD deployed on open
    positions, win rate over closed trades (None if no closed trades)."""
    root = Path(root)
    rows = read_jsonl(root / "h1.jsonl") + read_jsonl(root / "h2.jsonl")
    latest = _latest_state(rows)
    open_ = [r for r in latest.values() if r.get("status") == "open"]
    closed = [r for r in latest.values() if r.get("status") == "closed"]

    def _num(v: Any) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0

    total_pnl = sum(_num(r.get("pnl_usd")) for r in closed)
    usd_deployed = sum(_num(r.get("usd_deployed")) for r in open_)
    wins = sum(1 for r in closed if _num(r.get("pnl_usd")) > 0)
    win_rate = (wins / len(closed)) if closed else None
    return {
        "total_pnl": total_pnl,
        "open_count": len(open_),
        "usd_deployed": usd_deployed,
        "win_rate": win_rate,
    }


def signals(root: Path, limit: int = 200) -> list[dict]:
    """Most recent `limit` rows from `signals.jsonl` (file order preserved,
    tail-truncated)."""
    root = Path(root)
    rows = read_jsonl(root / "signals.jsonl")
    return rows[-limit:]


def _read_yaml(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return None


def _read_env(path: Path) -> dict[str, str]:
    """Parse `.env` KEY=VALUE lines, redacting values except the allowlist."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value and value[0] in "'\"":
            value = value.strip("'\"")
        if not key:
            continue
        out[key] = value if key in _ENV_ALLOWLIST else _REDACTED
    return out


def config_view(repo_root: Path) -> dict:
    """`universe.yaml`, `configs/study_roster.yaml`, and redacted `.env`."""
    repo_root = Path(repo_root)
    return {
        "universe": _read_yaml(repo_root / "universe.yaml"),
        "study_roster": _read_yaml(repo_root / "configs" / "study_roster.yaml"),
        "env": _read_env(repo_root / ".env"),
    }


def runs_summary(repo_root: Path) -> dict:
    """family -> parsed runs-summary/{family}.json, skipping corrupt files."""
    repo_root = Path(repo_root)
    summary_dir = repo_root / "runs-summary"
    if not summary_dir.is_dir():
        return {}
    out: dict[str, Any] = {}
    for p in sorted(summary_dir.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text())
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def runs_summary_family(repo_root: Path, family: str) -> dict | None:
    return runs_summary(repo_root).get(family)
