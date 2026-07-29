"""Canonical, byte-stable identities for ``swing-ranking-v1`` values."""

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
    """A value cannot participate in a canonical identity."""


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
            {item.name: getattr(value, item.name) for item in fields(value)},
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
        value,
        (str, bytes, bytearray),
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

__all__ = [
    "IdentityViolation",
    "canonical_bytes",
    "canonical_json",
    "decimal_string",
    "identity_hash",
    "require_sha256",
    "sha256_hex",
]
