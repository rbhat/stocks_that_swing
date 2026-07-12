"""Append-only trade log: trades.jsonl.

Invariants (CLAUDE.md hard rule, tested):
- The file is append-only. Never opened in a truncating mode ("w", "w+",
  O_TRUNC) and never rewritten in place — every write is a single
  os.write() on a descriptor opened with O_APPEND, followed by fsync.
- Every record carries a stable "id" (uuid4) and a "source"; readers dedupe
  on id, keeping the first occurrence, so two writers (or a Drive sync
  merge) can never stomp each other.
- A corrupt or truncated line (e.g. from a torn concurrent write) is
  skipped with a logged warning — it never crashes the reader and never
  blocks subsequent good lines from being read.

Drive sync (merging a remote trades.jsonl into the local one, and vice
versa) is handled by stm/data/sync.py; `merge_from` here is only the local
half of that contract — copying records from another file that aren't
already present locally.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import uuid
from pathlib import Path

from sts.models import TRADE_FIELDS

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("trades.jsonl")


class TradeLog:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)

    def append(self, record: dict) -> str:
        """Validate and append `record` as one JSON line. Returns its id."""
        rec = dict(record)
        if not rec.get("id"):
            rec["id"] = str(uuid.uuid4())
        if not rec.get("timestamp"):
            rec["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()

        missing = [k for k in TRADE_FIELDS if k not in rec]
        if missing:
            raise ValueError(f"trade record missing fields: {missing}")

        line = json.dumps(rec, default=str, separators=(",", ":")) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return rec["id"]

    def _read_tolerant(self, path: Path) -> list[dict]:
        """Read a trades.jsonl-style file, skipping corrupt lines. Missing
        file returns []. Does not dedupe."""
        if not path.exists():
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "skipping corrupt trade record at %s:%d", path, lineno
                    )
        return records

    def read(self) -> list[dict]:
        """All records, deduped on id, first occurrence wins."""
        seen = set()
        out = []
        for rec in self._read_tolerant(self.path):
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            out.append(rec)
        return out

    def merge_from(self, other_path: Path | str) -> int:
        """Append records from `other_path` whose ids aren't already local.
        Returns the number of records appended."""
        local_ids = {rec.get("id") for rec in self.read()}
        appended = 0
        for rec in self._read_tolerant(Path(other_path)):
            rid = rec.get("id")
            if rid in local_ids:
                continue
            self.append(rec)
            local_ids.add(rid)
            appended += 1
        return appended
