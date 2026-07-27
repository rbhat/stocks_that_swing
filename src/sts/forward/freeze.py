"""Fail-closed boundary for the retired, unversioned forward-paper book.

The success-v2 restart preserves the legacy ledgers for history and permits
upkeep of positions that were already open, but it never permits another
legacy candidate or fill on or after the clean OOS wall.
"""

from __future__ import annotations

import datetime as dt

LEGACY_ENTRY_FREEZE_WALL = dt.date(2026, 7, 27)


def legacy_entries_frozen(asof: dt.date) -> bool:
    """Return whether the retired legacy book is barred from new entries."""
    return asof >= LEGACY_ENTRY_FREEZE_WALL
