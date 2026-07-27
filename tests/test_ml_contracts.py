import datetime as dt
import hashlib

import pytest

from sts.ml.contracts import (
    ContractViolation,
    canonical_config_hash,
    canonical_json,
    deterministic_noise,
    row_identity,
)


def test_canonical_config_hash_is_order_independent_and_strict():
    left = {"target": "T1", "params": {"alpha": 10, "enabled": True}}
    right = {"params": {"enabled": True, "alpha": 10}, "target": "T1"}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_config_hash(left) == canonical_config_hash(right)
    assert canonical_config_hash({"values": [1, 2]}) != canonical_config_hash(
        {"values": [2, 1]}
    )
    with pytest.raises(ContractViolation, match="finite"):
        canonical_config_hash({"alpha": float("nan")})


def test_row_identity_is_normalized_stable_and_track_specific():
    day = dt.date(2023, 12, 29)

    first = row_identity("A", " aapl ", day)
    assert first == row_identity("track_a", "AAPL", day)
    assert first != row_identity("B", "AAPL", day)
    assert first.startswith("ml-row-v1:")
    assert len(first.removeprefix("ml-row-v1:")) == 64


def test_noise_matches_preregistered_identity_formula():
    config_hash = canonical_config_hash({"model": "M1", "target": "T1"})
    row_id = row_identity("A", "AAPL", dt.date(2023, 12, 29))
    assert config_hash == (
        "1450ca228e5a3c6d8605fe59c7d9c53564c29f4aea7464dbbb10bd2c06ed75fc"
    )
    assert row_id == (
        "ml-row-v1:"
        "ea218b1451e0844d3b80589dcca53d350055e771b36054c26df0c03a449f89e6"
    )
    expected_u = int(
        hashlib.sha256(f"{config_hash}|{row_id}".encode()).hexdigest()[:16],
        16,
    ) / 2**64

    assert deterministic_noise(config_hash, row_id) == 2 * expected_u - 1
    assert deterministic_noise(config_hash, row_id) == deterministic_noise(
        config_hash, row_id
    )
