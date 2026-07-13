"""Append-only JSONL journal primitive for the forward-paper pipeline.

Invariants:
- `append` writes exactly one line per record, `json.dumps(record,
  sort_keys=True, default=str)`, flushed and fsynced before returning.
- `read` tolerates a truncated trailing line (e.g. a crash mid-write): if
  only the LAST line fails to parse, it is skipped with a warning. An
  invalid line anywhere else raises `ValueError` naming the line number.
- `merge_lines` is a pure function (no I/O) for reconciling two journals'
  raw lines, e.g. after pulling a remote copy down for merge.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Journal:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        """Append `record` as one JSON line. Caller owns all fields."""
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        with open(self.path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def read(self) -> list[dict]:
        """Parse all lines. A trailing partial line is skipped with a
        warning; an invalid line elsewhere raises ValueError."""
        if not self.path.exists():
            return []
        raw = self.path.read_text()
        lines = raw.split("\n")
        # A well-formed file ends with "\n", so the last split element is "".
        # Drop it; anything else in that slot is a genuine partial line.
        trailing_partial = lines[-1] if lines and lines[-1] != "" else None
        if trailing_partial is not None:
            lines = lines[:-1]
        else:
            lines = lines[:-1] if lines and lines[-1] == "" else lines

        records: list[dict] = []
        for i, line in enumerate(lines, start=1):
            if line == "":
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {i} of {self.path}") from exc

        if trailing_partial:
            try:
                records.append(json.loads(trailing_partial))
            except json.JSONDecodeError:
                logger.warning(
                    "skipping truncated trailing line in %s (line %d)",
                    self.path,
                    len(lines) + 1,
                )
        return records

    def __len__(self) -> int:
        return len(self.read())


def merge_lines(a: list[str], b: list[str], key_fn: Callable[[dict], Any]) -> list[str]:
    """Union raw JSONL lines from `a` and `b`, preserving first-seen order
    of `a` then new-from-`b`, deduping by `key_fn(json.loads(line))`.

    On a key collision with differing content, keeps the line whose parsed
    `updated_at` field is larger (falling back to the larger raw string
    when `updated_at` is absent or equal), logging a warning. Pure, no I/O.
    """
    by_key: dict[Any, str] = {}
    order: list[Any] = []

    def resolve(key: Any, existing: str, candidate: str) -> str:
        if existing == candidate:
            return existing
        existing_parsed = json.loads(existing)
        candidate_parsed = json.loads(candidate)
        existing_ts = existing_parsed.get("updated_at")
        candidate_ts = candidate_parsed.get("updated_at")
        if existing_ts is not None and candidate_ts is not None and existing_ts != candidate_ts:
            winner = candidate if candidate_ts > existing_ts else existing
        else:
            winner = max(existing, candidate)
        logger.warning("merge_lines: content collision for key %r; keeping newer line", key)
        return winner

    for line in a + b:
        if line == "":
            continue
        key = key_fn(json.loads(line))
        if key not in by_key:
            by_key[key] = line
            order.append(key)
        else:
            by_key[key] = resolve(key, by_key[key], line)

    return [by_key[k] for k in order]
