"""Read/control boundary for the retired pre-v1 dashboard.

The modules in this package operate only on explicit legacy paths. They never
import the recovered ``legacy/dashboard`` package or the v1 scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LegacyRoots:
    """Filesystem roots mounted from the retired deployment."""

    ledger: Path
    runs: Path
    runs_summary: Path
    logs: Path
    configs: Path
    env_file: Path | None = None

    @classmethod
    def under(cls, root: Path) -> LegacyRoots:
        root = Path(root)
        return cls(
            ledger=root / "ledger",
            runs=root / "runs",
            runs_summary=root / "runs-summary",
            logs=root / "logs",
            configs=root / "configs",
            env_file=root / ".env",
        )
