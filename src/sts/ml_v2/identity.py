"""Canonical, byte-stable identities for ML-v2 pure values."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IdentityViolation(ValueError):
    """A value cannot participate in a canonical ML-v2 identity."""


def decimal_string(value: Decimal) -> str:
    """Return a non-exponent, minimal decimal representation."""
    if not value.is_finite():
        raise IdentityViolation("canonical decimals must be finite")
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _canonical(value: Any, path: str = "payload") -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, float):
        raise IdentityViolation(f"{path} contains a float; use Decimal")
    if isinstance(value, dt.datetime):
        raise IdentityViolation(f"{path} contains a datetime; use a date")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical(value.value, path)
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(
            {
                item.name: getattr(value, item.name)
                for item in fields(value)
            },
            path,
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise IdentityViolation(f"{path} mapping keys must be strings")
            result[key] = _canonical(item, f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            _canonical(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise IdentityViolation(
        f"{path} contains unsupported type {type(value).__name__}"
    )


def canonical_json(value: Any) -> str:
    """Encode a value as canonical UTF-8 JSON text."""
    return json.dumps(
        _canonical(value),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def identity_hash(domain: str, payload: Any) -> str:
    if not isinstance(domain, str) or not domain.strip():
        raise IdentityViolation("identity domain must be a non-empty string")
    return sha256_hex(
        canonical_bytes({"domain": domain.strip(), "payload": payload})
    )


def require_sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise IdentityViolation(f"{name} must be lowercase SHA-256 hex")
    return value


def setup_identity(config: Any) -> str:
    return identity_hash("ml-v2/setup/v1", config)


def candidate_identity(candidate: Any) -> str:
    return identity_hash(
        "ml-v2/candidate/v1",
        {
            "setup_id": candidate.setup_id,
            "fold_id": candidate.fold_id,
            "permanent_id": candidate.permanent_id,
            "signal_session": candidate.signal_session,
            "entry_session": candidate.entry_session,
            "score": candidate.score,
            "signal_close": candidate.signal_close,
            "atr14": candidate.atr14,
            "mdv20": candidate.mdv20,
            "facts_as_of": candidate.facts_as_of,
            "control_values": candidate.control_values,
            "signal_to_entry_split_ratio": candidate.signal_to_entry_split_ratio,
            "stale": candidate.stale,
            "source_identity": candidate.source_identity,
        },
    )


def tie_breaker(
    setup_id: str,
    signal_session: dt.date,
    permanent_id: str,
) -> int:
    """Locked unsigned first-16-hex tie key; symbol text never participates."""
    payload = f"{setup_id}|{signal_session.isoformat()}|{permanent_id}"
    return int(sha256_hex(payload)[:16], 16)


def control_seed(
    study_id: str,
    setup_id: str,
    fold_id: str,
    signal_session: dt.date,
    replicate: int,
    control_id: str,
) -> int:
    payload = (
        f"{study_id}|{setup_id}|{fold_id}|{signal_session.isoformat()}|"
        f"{replicate}|{control_id}"
    )
    return int(sha256_hex(payload)[:16], 16)


def event_hash(
    *,
    sequence: int,
    event_type: str,
    payload: Mapping[str, Any],
    previous_hash: str | None,
) -> str:
    if sequence < 0:
        raise IdentityViolation("event sequence must be non-negative")
    if previous_hash is not None:
        require_sha256(previous_hash, "previous_hash")
    return identity_hash(
        "ml-v2/ledger-event/v1",
        {
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
        },
    )
