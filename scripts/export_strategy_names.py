#!/usr/bin/env python
"""Export a compact identity -> strategy name index for a screening window.

`runs/swing-ranking-v1/<window>/strategies/` is 52 MB for development and 14 MB
for validation, almost all of it resolved entry geometries the dashboard never
reads. This writes the few kilobytes it does need — the revision identity, its
strategy name, and its readable rules — beside the window as
`strategy_names.json`, so the curated subset pushed to the VM can still show
names instead of hash prefixes.

Read-only with respect to every existing artifact: it writes one new file and
is deliberately excluded from the manifest content set it sits next to.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_WINDOWS = ("development-v1", "validation-v1", "oos-v1")
OUTPUT_NAME = "strategy_names.json"


def export_window(window_root: Path) -> int:
    """Write `strategy_names.json` for one window; return the entry count."""
    window_root = Path(window_root)
    strategies_dir = window_root / "strategies"
    if not strategies_dir.is_dir():
        raise FileNotFoundError(f"no strategies directory under {window_root}")

    strategies: dict[str, str] = {}
    rules: dict[str, list[str]] = {}
    for path in sorted(strategies_dir.glob("*.json")):
        record = json.loads(path.read_text())
        strategy = record.get("strategy")
        if not isinstance(strategy, dict):
            continue
        identity = record.get("strategy_identity") or path.stem
        name = strategy.get("strategy_name")
        if not isinstance(name, str) or not name:
            continue
        strategies[str(identity)] = name
        readable = strategy.get("readable_rules")
        if isinstance(readable, list):
            rules[str(identity)] = [r for r in readable if isinstance(r, str)]

    payload = {
        "schema_version": "swing-ranking-v1.dashboard-strategy-names.v1",
        "window": window_root.name,
        "count": len(strategies),
        "strategies": strategies,
        "readable_rules": rules,
    }
    (window_root / OUTPUT_NAME).write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return len(strategies)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs/swing-ranking-v1"),
        help="directory holding the screening windows",
    )
    parser.add_argument(
        "--window",
        action="append",
        dest="windows",
        help="window to export; repeatable (default: all three)",
    )
    args = parser.parse_args()

    for window in args.windows or DEFAULT_WINDOWS:
        root = args.runs_root / window
        if not root.is_dir():
            print(f"skip {window}: absent")
            continue
        count = export_window(root)
        print(f"{window}: {count} strategy names -> {root / OUTPUT_NAME}")


if __name__ == "__main__":
    main()
