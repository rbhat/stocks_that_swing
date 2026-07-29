from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest

from sts import calendar
from sts.swing_ranking.contracts import ContractViolation
from sts.swing_ranking.split import (
    derive_evaluation_split,
    evaluation_split_document,
)


def test_split_is_frozen_60_20_20_by_xnys_session_with_21_session_purges():
    start = dt.date(2024, 1, 2)
    end = dt.date(2025, 1, 4)
    split = derive_evaluation_split(start, end)
    sessions = tuple(
        session.date()
        for session in calendar.sessions_between(start, end)
        if session.date() < end
    )
    development_boundary = (len(sessions) * 3) // 5
    oos_boundary = (len(sessions) * 4) // 5

    assert split.session_count == len(sessions)
    assert split.development.session_count == development_boundary - 21
    assert split.development_validation_purge.session_count == 21
    assert split.validation.session_count == (
        oos_boundary - development_boundary - 21
    )
    assert split.validation_oos_purge.session_count == 21
    assert split.oos.session_count == len(sessions) - oos_boundary
    assert split.development_validation_purge.end_exclusive == sessions[
        development_boundary
    ]
    assert split.validation_oos_purge.end_exclusive == sessions[oos_boundary]
    assert derive_evaluation_split(start, end) == split
    assert len(split.identity) == 64


def test_split_interchange_is_explicit_and_tamper_evident():
    split = derive_evaluation_split(dt.date(2024, 1, 2), dt.date(2025, 1, 4))
    document = evaluation_split_document(split)

    assert document["development_fraction"] == "0.60"
    assert document["purge_entry_sessions"] == 21
    with pytest.raises(ContractViolation, match="exactly 21"):
        replace(
            split,
            session_count=split.session_count - 1,
            development_validation_purge=replace(
                split.development_validation_purge,
                session_count=20,
            ),
        )


def test_split_rejects_ranges_too_short_for_locked_purge():
    with pytest.raises(ContractViolation, match="too short"):
        derive_evaluation_split(dt.date(2024, 1, 2), dt.date(2024, 3, 1))
