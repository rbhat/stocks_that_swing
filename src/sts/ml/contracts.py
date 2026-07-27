"""Canonical identities shared by the pure ML research contracts.

This module deliberately performs no I/O. Configurations and row keys are
normalized before hashing so later artifacts can prove that the exact same
research contract was used across reruns.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

ROW_ID_SCHEMA = "ml-row-v1"
CONFIG_HASH_SCHEMA = "ml-config-v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractViolation(ValueError):
    """A locked ML contract was incomplete, invalid, or ambiguous."""


def require_date(value: Any, name: str) -> dt.date:
    """Return a date while rejecting datetimes and string coercion."""
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ContractViolation(f"{name} must be a datetime.date")
    return value


def normalize_track(value: str) -> str:
    if not isinstance(value, str):
        raise ContractViolation("track must be 'A' or 'B'")
    normalized = value.strip().lower().replace("-", "_")
    aliases = {"a": "A", "track_a": "A", "b": "B", "track_b": "B"}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ContractViolation("track must be 'A' or 'B'") from exc


def normalize_symbol(value: str) -> str:
    if not isinstance(value, str):
        raise ContractViolation("symbol must be a non-empty string")
    normalized = value.strip().upper()
    if not normalized or any(character.isspace() for character in normalized):
        raise ContractViolation("symbol must be a non-empty string without whitespace")
    return normalized


def _canonical_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractViolation(f"{path} must be finite")
        return 0.0 if value == 0 else value
    if isinstance(value, dt.datetime):
        raise ContractViolation(f"{path} datetime values are not canonical config facts")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractViolation(f"{path} mapping keys must be strings")
            normalized[key] = _canonical_value(item, f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            _canonical_value(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ContractViolation(
        f"{path} contains unsupported canonical type {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    """Encode JSON with stable key ordering and no non-finite values."""
    normalized = _canonical_value(value, "config")
    return json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_config_hash(config: Mapping[str, Any]) -> str:
    """Hash a config inside a versioned envelope."""
    if not isinstance(config, Mapping):
        raise ContractViolation("config must be a mapping")
    envelope = {"schema": CONFIG_HASH_SCHEMA, "config": config}
    return hashlib.sha256(canonical_json(envelope).encode()).hexdigest()


def row_identity(track: str, symbol: str, signal_session: dt.date) -> str:
    """Return the deterministic identity for one research row."""
    payload = {
        "schema": ROW_ID_SCHEMA,
        "track": normalize_track(track),
        "symbol": normalize_symbol(symbol),
        "signal_session": require_date(
            signal_session, "signal_session"
        ).isoformat(),
    }
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return f"{ROW_ID_SCHEMA}:{digest}"


def deterministic_noise(config_hash: str, row_id: str) -> float:
    """Return the exact preregistered deterministic noise feature."""
    if not isinstance(config_hash, str) or not _SHA256_RE.fullmatch(config_hash):
        raise ContractViolation("config_hash must be a lowercase SHA-256 hex digest")
    if not isinstance(row_id, str) or not row_id.startswith(f"{ROW_ID_SCHEMA}:"):
        raise ContractViolation(f"row_id must use the {ROW_ID_SCHEMA} schema")
    digest = hashlib.sha256(f"{config_hash}|{row_id}".encode()).hexdigest()
    unit_interval = int(digest[:16], 16) / 2**64
    return 2 * unit_interval - 1
