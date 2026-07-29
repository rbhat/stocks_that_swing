"""Canonical identity primitives shared with the repository serializer.

This module deliberately re-exports the one canonical serializer.  Study
contracts may add domains and payload shapes, but never serialization rules.
"""

from sts.ml_v2.identity import (
    IdentityViolation,
    canonical_bytes,
    canonical_json,
    decimal_string,
    identity_hash,
    require_sha256,
    sha256_hex,
)

__all__ = [
    "IdentityViolation",
    "canonical_bytes",
    "canonical_json",
    "decimal_string",
    "identity_hash",
    "require_sha256",
    "sha256_hex",
]
