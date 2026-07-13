"""Discord webhook alerts for the forward-paper pipeline.

`send` never raises: a missing webhook or exhausted retries logs a warning
and returns False so an alert failure can never crash a job. The three
format functions (`entry_alert`, `book_status`, `exit_alert`) are pure
string builders, independently testable without any network access.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_PT = ZoneInfo("America/Los_Angeles")
_MAX_CONTENT_LEN = 1900
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (2, 4)


def send(text: str, webhook: str | None = None) -> bool:
    """POST `text` to a Discord webhook. Retries up to 3 times (2s/4s
    backoff between attempts). Returns False (and logs a warning) on a
    missing webhook or if all attempts fail — never raises."""
    url = webhook if webhook is not None else os.environ.get("DISCORD_WEB_HOOK")
    if not url:
        logger.warning("alerts.send: no webhook configured, dropping alert")
        return False

    payload = json.dumps({"content": text[:_MAX_CONTENT_LEN]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            # Discord/Cloudflare rejects urllib's default Python-urllib UA with 403
            "User-Agent": "sts-forward-alerts/1.0",
        },
        method="POST",
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            return True
        except Exception as exc:
            logger.warning(
                "alerts.send: attempt %d/%d failed: %s", attempt, _MAX_ATTEMPTS, exc
            )
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_BACKOFF_SECONDS[attempt - 1])

    return False


def entry_alert(cand: dict, now: dt.datetime | None = None) -> str:
    """Format an entry-signal alert. `now` (aware or naive-UTC) defaults to
    the current time; injectable for deterministic tests."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    local = now.astimezone(_PT)
    timestamp = local.strftime("%Y-%m-%d %I:%M %p PT")

    low, high = cand["entry_price_range"]
    return (
        f"{cand['ticker']} Entry @{low:.2f}-{high:.2f}, "
        f"TP1: @{cand['tp1']:.2f}, TP2: @-, SL: {cand['sl']:.2f}. "
        f"Config: {cand['config_name']}. Alerted at {timestamp}."
    )


def book_status(snapshots: list[dict]) -> str:
    """One line per equity snapshot, joined with newlines."""
    lines = [
        f"{snap['book']}: equity=${snap['equity']:.2f} cash=${snap['cash']:.2f} "
        f"deployed=${snap['usd_deployed']:.2f} open={snap['open_count']}"
        for snap in snapshots
    ]
    return "\n".join(lines)


def exit_alert(row: dict) -> str:
    """Format an exit alert for a closed ledger row."""
    return (
        f"{row['ticker']} EXIT {row['exit_reason']} @{row['exit_price']:.2f}, "
        f"R={row['r_net']:+.2f} ({row['book']})"
    )
