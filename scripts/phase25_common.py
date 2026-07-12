"""Shared plumbing for every Phase 2.5 exploratory-discovery stage script.

Hard rule (docs/PLAN.md Phase 2.5): every stage reads only strictly-pre-OOS-wall
data. This is enforced HERE, once, so no stage script can accidentally (or
deliberately) read past it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

import pandas as pd

from sts.data.study_store import StudyStore

OOS_WALL = dt.date(2024, 1, 1)

_STORE: StudyStore | None = None


def _study_store() -> StudyStore:
    global _STORE
    if _STORE is None:
        _STORE = StudyStore()
    return _STORE


def load_is_frames() -> dict[str, pd.DataFrame]:
    """Every study-roster frame, truncated to bars strictly before OOS_WALL."""
    frames = {}
    for sym, df in _study_store().load_all().items():
        truncated = df[df.index.date < OOS_WALL]
        if not truncated.empty:
            frames[sym] = truncated
    return frames


def setup_stage_logger(stage_name: str, run_dir: Path) -> logging.Logger:
    """A logger that writes to runs/phase25/<stage>/stage.log AND stdout, line-
    buffered so `tail -f` works when the orchestrator redirects it."""
    stage_dir = run_dir / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"phase25.{stage_name}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(stage_dir / "stage.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    logger.addHandler(sh)
    return logger


def atomic_write_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))
    os.replace(tmp, path)
