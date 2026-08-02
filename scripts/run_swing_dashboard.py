#!/usr/bin/env python
"""uvicorn entry point for the swing-ranking-v1 dashboard.

It serves the v1 artifacts and the retired legacy books without writing either
ledger. Optional legacy mutations are delegated to an isolated admin sidecar.

Env overrides:
  STS_RUNS_ROOT     directory holding the runs (default "runs"). Point this at
                    a scratch copy for local testing.
  STS_REPO_ROOT     directory holding configs/ and logs/ (default ".").
  DASHBOARD_PORT    listen port (default 8010).
  DASHBOARD_HOST    listen host (default 0.0.0.0 so the compose mapping
                    127.0.0.1:8010:8010 reaches the process; only the
                    docker-proxy on the host side is loopback-bound).
  DASHBOARD_SECRET  session signing secret; required unless DASHBOARD_DEV=1.
  STS_LEGACY_ROOT   mount containing ledger/, runs/, runs-summary/, logs/, and
                    configs/ (default /app/legacy).
  STS_LEGACY_ADMIN_URL  internal URL of the optional bounded admin sidecar.
  LEGACY_ADMIN_TOKEN     shared sidecar authentication token.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from sts.swing_ranking.dashboard.app import create_app
from sts.swing_ranking.dashboard.legacy import LegacyRoots

app = create_app(
    runs_root=Path(os.environ.get("STS_RUNS_ROOT", "runs")),
    repo_root=Path(os.environ.get("STS_REPO_ROOT", ".")),
    legacy_roots=LegacyRoots.under(Path(os.environ.get("STS_LEGACY_ROOT", "/app/legacy"))),
    legacy_admin_url=os.environ.get("STS_LEGACY_ADMIN_URL"),
    legacy_admin_token=os.environ.get("LEGACY_ADMIN_TOKEN"),
)


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
        port=int(os.environ.get("DASHBOARD_PORT", "8010")),
    )


if __name__ == "__main__":
    main()
