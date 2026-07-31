#!/usr/bin/env python
"""uvicorn entry point for the STS admin dashboard.

Env overrides:
  STS_LEDGER_ROOT  ledger directory to read (default "ledger"). Point this
                   at a scratch dir for local/e2e testing so real ledger/
                   and Drive are never touched.
  DASHBOARD_PORT   listen port (default 8000).
  DASHBOARD_HOST   listen host (default 0.0.0.0 so the compose port
                   mapping 127.0.0.1:8000:8000 reaches the process; only
                   the docker-proxy on the host side is loopback-bound).
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from sts.dashboard.app import create_app

app = create_app(ledger_root=Path(os.environ.get("STS_LEDGER_ROOT", "ledger")))


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
        port=int(os.environ.get("DASHBOARD_PORT", 8000)),
    )


if __name__ == "__main__":
    main()
