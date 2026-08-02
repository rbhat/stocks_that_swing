"""Append-only unified audit log for authentication and bounded controls.

One JSON line per event to `logs/dashboard-audit.log` under `root`.
Best-effort: audit failures never break the request path.

Legacy control records carry an explicit scope and target in this same log.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def log(
    event: str,
    who: str,
    detail: dict,
    root: Path,
    *,
    scope: str = "v1",
    target: str | None = None,
) -> None:
    rec = {
        "ts": dt.datetime.now(dt.UTC).isoformat(),
        "event": event,
        "who": who,
        "scope": scope,
        "detail": detail,
    }
    if target is not None:
        rec["target"] = target
    try:
        path = Path(root) / "logs" / "dashboard-audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    except OSError:
        logger.warning("audit log write failed", exc_info=True)
