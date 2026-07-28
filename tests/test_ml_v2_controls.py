from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import pytest

import sts.ml_v2.controls as controls_module
from sts.ml_v2.contracts import (
    REQUIRED_AS_OF_FACTS,
    REQUIRED_SOURCE_KINDS,
    Candidate,
    PointInTimeManifest,
    SourceRecord,
)
from sts.ml_v2.controls import (
    control_rank,
    rank_all_dates,
    rank_candidates,
    synchronized_permutation,
)
from sts.ml_v2.identity import tie_breaker


def _manifest() -> PointInTimeManifest:
    return PointInTimeManifest(
        dt.date(2024, 1, 1),
        dt.date(2025, 1, 1),
        tuple(
            SourceRecord(
                kind,
                hashlib.sha256(kind.encode()).hexdigest(),
                "synthetic-v1",
            )
            for kind in REQUIRED_SOURCE_KINDS
        ),
    )


def _pool() -> tuple[Candidate, ...]:
    manifest = _manifest()
    signal = dt.date(2024, 1, 2)
    return tuple(
        Candidate(
            "P-D",
            "F1",
            permanent_id,
            symbol,
            signal,
            dt.date(2024, 1, 3),
            Decimal(1),
            Decimal(100),
            Decimal(2),
            Decimal(100000000),
            manifest.identity,
            {name: signal for name in REQUIRED_AS_OF_FACTS},
            {
                "adjusted_return_20": Decimal(index),
                "adjusted_return_5": Decimal(index),
                "volume_to_median_20": Decimal(10 - index),
            },
        )
        for index, (permanent_id, symbol) in enumerate(
            (("perm-c", "AAA"), ("perm-a", "ZZZ"), ("perm-b", "MMM"))
        )
    )


def test_equal_scores_follow_hash_tie_not_symbol_order():
    pool = _pool()
    ranked = rank_candidates(pool)
    expected = sorted(
        pool,
        key=lambda item: tie_breaker(
            item.setup_id, item.signal_session, item.permanent_id
        ),
    )
    assert [item.permanent_id for item in ranked] == [
        item.permanent_id for item in expected
    ]
    assert [item.symbol for item in ranked] != sorted(item.symbol for item in pool)


def test_fixed_and_random_controls_are_deterministic_and_pool_preserving():
    pool = _pool()
    momentum = control_rank(pool, control_id="momentum")
    pullback = control_rank(pool, control_id="pullback")
    activity = control_rank(pool, control_id="activity")
    assert [item.permanent_id for item in momentum] == [
        "perm-b", "perm-a", "perm-c"
    ]
    assert [item.permanent_id for item in pullback] == [
        "perm-c", "perm-a", "perm-b"
    ]
    assert [item.permanent_id for item in activity] == [
        "perm-c", "perm-a", "perm-b"
    ]
    random_one = control_rank(pool, control_id="random", replicate=7)
    random_two = control_rank(tuple(reversed(pool)), control_id="random", replicate=7)
    assert random_one == random_two
    assert {item.permanent_id for item in random_one} == {
        item.permanent_id for item in pool
    }


def test_date_grouping_and_synchronized_permutation_preserve_facts():
    pool = _pool()
    ranked = rank_all_dates(pool, control_id="random", replicate=3)
    assert len(ranked) == len(pool)
    permuted_one = synchronized_permutation(pool, replicate=4)
    permuted_two = synchronized_permutation(tuple(reversed(pool)), replicate=4)
    by_id_one = {
        item.permanent_id: item.score for item in permuted_one
    }
    by_id_two = {
        item.permanent_id: item.score for item in permuted_two
    }
    assert by_id_one == by_id_two
    assert sorted(by_id_one.values()) == sorted(item.score for item in pool)


def test_fixed_control_tie_hash_collision_fails_closed(monkeypatch):
    pool = tuple(
        Candidate(
            **{
                **item.__dict__,
                "control_values": {
                    "adjusted_return_20": Decimal(1),
                    "adjusted_return_5": Decimal(1),
                    "volume_to_median_20": Decimal(1),
                },
            }
        )
        for item in _pool()
    )
    monkeypatch.setattr(controls_module, "_tie", lambda _candidate: 7)
    with pytest.raises(controls_module.ContractViolation, match="collision"):
        control_rank(pool, control_id="momentum")
