"""Deterministic ML-v2 ranking controls over the identical candidate pool."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

from sts.ml_v2.contracts import STUDY_ID, Candidate, ContractViolation
from sts.ml_v2.identity import (
    candidate_identity,
    control_seed,
    tie_breaker,
)

FIXED_CONTROL_IDS = ("momentum", "pullback", "activity")
RANDOM_CONTROL_ID = "random"


def _tie(candidate: Candidate) -> int:
    return tie_breaker(
        candidate.setup_id,
        candidate.signal_session,
        candidate.permanent_id,
    )


def _reject_sort_key_collisions(
    keyed_candidates: tuple[tuple[object, Candidate], ...],
) -> None:
    seen: dict[object, str] = {}
    for key, candidate in keyed_candidates:
        prior = seen.get(key)
        if prior is not None and prior != candidate.permanent_id:
            raise ContractViolation(
                "ranking key collision between permanent IDs"
            )
        seen[key] = candidate.permanent_id


def rank_candidates(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """Rank a frozen same-date pool by score then the locked ID hash."""
    _reject_sort_key_collisions(
        tuple(
            ((-candidate.score, _tie(candidate)), candidate)
            for candidate in candidates
        )
    )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (-candidate.score, _tie(candidate)),
        )
    )


def control_rank(
    candidates: tuple[Candidate, ...],
    *,
    control_id: str,
    replicate: int = 0,
) -> tuple[Candidate, ...]:
    """Replace only ranking scores; all execution facts remain identical."""
    if not candidates:
        return ()
    setup_ids = {candidate.setup_id for candidate in candidates}
    fold_ids = {candidate.fold_id for candidate in candidates}
    sessions = {candidate.signal_session for candidate in candidates}
    if len(setup_ids) != 1 or len(fold_ids) != 1 or len(sessions) != 1:
        raise ContractViolation("a control rank requires one setup/fold/date pool")
    if replicate < 0:
        raise ContractViolation("control replicate must be non-negative")

    if control_id in FIXED_CONTROL_IDS:
        field, descending = {
            "momentum": ("adjusted_return_20", True),
            "pullback": ("adjusted_return_5", False),
            "activity": ("volume_to_median_20", True),
        }[control_id]
        missing = [
            candidate.permanent_id
            for candidate in candidates
            if field not in candidate.control_values
        ]
        if missing:
            raise ContractViolation(
                f"{control_id} control lacks {field} for permanent IDs {missing}"
            )
        _reject_sort_key_collisions(
            tuple(
                (
                    (
                        (
                            -candidate.control_values[field]
                            if descending
                            else candidate.control_values[field]
                        ),
                        _tie(candidate),
                    ),
                    candidate,
                )
                for candidate in candidates
            )
        )
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                (
                    -candidate.control_values[field]
                    if descending
                    else candidate.control_values[field]
                ),
                _tie(candidate),
            ),
        )
    elif control_id == RANDOM_CONTROL_ID:
        setup_id = next(iter(setup_ids))
        fold_id = next(iter(fold_ids))
        signal_session = next(iter(sessions))
        seed = control_seed(
            STUDY_ID,
            setup_id,
            fold_id,
            signal_session,
            replicate,
            control_id,
        )

        def random_key(candidate: Candidate) -> tuple[str, int]:
            digest = hashlib.sha256(
                f"{seed}|{candidate_identity(candidate)}".encode()
            ).hexdigest()
            return digest, _tie(candidate)

        _reject_sort_key_collisions(
            tuple((random_key(candidate), candidate) for candidate in candidates)
        )
        ordered = sorted(candidates, key=random_key)
    else:
        raise ContractViolation(
            f"control_id must be one of {FIXED_CONTROL_IDS + (RANDOM_CONTROL_ID,)}"
        )

    total = len(ordered)
    return tuple(
        replace(candidate, score=Decimal(total - index))
        for index, candidate in enumerate(ordered)
    )


def rank_all_dates(
    candidates: tuple[Candidate, ...],
    *,
    control_id: str,
    replicate: int = 0,
) -> tuple[Candidate, ...]:
    pools: dict[tuple[str, str, object], list[Candidate]] = {}
    for candidate in candidates:
        key = (
            candidate.setup_id,
            candidate.fold_id,
            candidate.signal_session,
        )
        pools.setdefault(key, []).append(candidate)
    ranked: list[Candidate] = []
    for key in sorted(pools, key=lambda item: (item[2], item[0], item[1])):
        ranked.extend(
            control_rank(
                tuple(pools[key]),
                control_id=control_id,
                replicate=replicate,
            )
        )
    return tuple(ranked)


def synchronized_permutation(
    candidates: tuple[Candidate, ...],
    *,
    replicate: int,
) -> tuple[Candidate, ...]:
    """Gate-1 score-assignment permutation; model refits remain Gate 4."""
    if replicate < 0 or replicate >= 999:
        raise ContractViolation("permutation replicate must be in [0, 999)")
    pools: dict[tuple[str, str, object], list[Candidate]] = {}
    for candidate in candidates:
        key = (
            candidate.setup_id,
            candidate.fold_id,
            candidate.signal_session,
        )
        pools.setdefault(key, []).append(candidate)
    result: list[Candidate] = []
    for key in sorted(pools, key=lambda item: (item[2], item[0], item[1])):
        pool = pools[key]
        scores = sorted(
            (candidate.score for candidate in pool),
            reverse=True,
        )
        seed = control_seed(
            STUDY_ID,
            key[0],
            key[1],
            key[2],
            replicate,
            "local_permutation",
        )
        def permutation_key(
            candidate: Candidate,
            _seed: int = seed,
        ) -> tuple[str, int]:
            digest = hashlib.sha256(
                f"{_seed}|{candidate_identity(candidate)}".encode()
            ).hexdigest()
            return digest, _tie(candidate)

        _reject_sort_key_collisions(
            tuple((permutation_key(candidate), candidate) for candidate in pool)
        )
        permuted = sorted(pool, key=permutation_key)
        result.extend(
            replace(candidate, score=score)
            for candidate, score in zip(permuted, scores, strict=True)
        )
    return tuple(result)
