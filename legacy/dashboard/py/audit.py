"""Append-only audit log: logins, failed logins, sync triggers, config edits.

One JSON line per event to `logs/dashboard-audit.log` under `root`.
Best-effort: audit failures never break the request path.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def log(event: str, who: str, detail: dict, root: Path) -> None:
    rec = {
        "ts": dt.datetime.now(dt.UTC).isoformat(),
        "event": event,
        "who": who,
        "detail": detail,
    }
    try:
        path = Path(root) / "logs" / "dashboard-audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    except OSError:
        logger.warning("audit log write failed", exc_info=True)
