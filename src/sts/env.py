"""Minimal .env loader — no python-dotenv dependency.

Loads KEY=VALUE lines from a .env file into os.environ at job startup so
local runs behave like Docker's --env-file. Real environment variables
always win: an existing key is never overridden (mounted secrets / CI env
take precedence over the file). Values are never logged.
"""

from __future__ import annotations

import os
from pathlib import Path


def load(path: Path | str = ".env") -> int:
    """Load `path` into os.environ (existing keys untouched). Returns the
    number of keys set. Missing file is a silent no-op."""
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value and value[0] in "'\"":
            value = value.strip("'\"")
        elif " #" in value:  # unquoted inline comment (dotenv convention)
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n
