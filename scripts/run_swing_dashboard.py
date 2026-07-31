#!/usr/bin/env python
"""uvicorn entry point for the swing-ranking-v1 dashboard.

Read-only: it serves the forward ledger and the sealed backtests and never
writes to a run directory. The scheduler remains the single writer.

Env overrides:
  STS_RUNS_ROOT     directory holding the runs (default "runs"). Point this at
                    a scratch copy for local testing.
  STS_REPO_ROOT     directory holding configs/ and logs/ (default ".").
  DASHBOARD_PORT    listen port (default 8010).
  DASHBOARD_HOST    listen host (default 0.0.0.0 so the compose mapping
                    127.0.0.1:8010:8010 reaches the process; only the
                    docker-proxy on the host side is loopback-bound).
  DASHBOARD_SECRET  session signing secret; required unless DASHBOARD_DEV=1.
  STS_LEGACY_DASHBOARD_URL  where the "legacy dashboard" link points
                    (default http://127.0.0.1:8000, the second -L forward).
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from sts.swing_ranking.dashboard.app import create_app

app = create_app(
    runs_root=Path(os.environ.get("STS_RUNS_ROOT", "runs")),
    repo_root=Path(os.environ.get("STS_REPO_ROOT", ".")),
)


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
        port=int(os.environ.get("DASHBOARD_PORT", 8010)),
    )


if __name__ == "__main__":
    main()
