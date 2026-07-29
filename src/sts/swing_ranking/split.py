"""Deterministic XNYS-session split derivation for ``swing-ranking-v1``."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sts import calendar
from sts.swing_ranking.contracts import (
    SPLIT_VERSION,
    ContractViolation,
    EvaluationSplit,
    SplitWindow,
)
from sts.swing_ranking.identity import identity_hash

_SESSION_DOMAIN = "swing-ranking-v1/evaluation-sessions/v1"
_WINDOW_DOMAIN = "swing-ranking-v1/evaluation-window-sessions/v1"
_PURGE_SESSIONS = 21


def _evaluation_sessions(
    start: dt.date,
    end_exclusive: dt.date,
) -> tuple[dt.date, ...]:
    if (
        isinstance(start, dt.datetime)
        or not isinstance(start, dt.date)
        or isinstance(end_exclusive, dt.datetime)
        or not isinstance(end_exclusive, dt.date)
        or start >= end_exclusive
    ):
        raise ContractViolation("split range must contain valid ordered dates")
    return tuple(
        session.date()
        for session in calendar.sessions_between(start, end_exclusive)
        if session.date() < end_exclusive
    )


def _window(
    *,
    kind: str,
    sessions: tuple[dt.date, ...],
    full_sessions: tuple[dt.date, ...],
    stop_index: int,
    evaluation_end_exclusive: dt.date,
) -> SplitWindow:
    if not sessions:
        raise ContractViolation(f"{kind} split window would be empty")
    end = (
        full_sessions[stop_index]
        if stop_index < len(full_sessions)
        else evaluation_end_exclusive
    )
    return SplitWindow(
        kind=kind,
        start=sessions[0],
        end_exclusive=end,
        session_count=len(sessions),
        sessions_identity=identity_hash(
            _WINDOW_DOMAIN,
            {"kind": kind, "sessions": sessions},
        ),
    )


def derive_evaluation_split(
    evaluation_start: dt.date,
    evaluation_end_exclusive: dt.date,
) -> EvaluationSplit:
    """Derive the sole chronological split without reading performance.

    The 60% and 80% boundaries use integer floor indices into the frozen XNYS
    session sequence. The final 21 raw development sessions and final 21 raw
    validation sessions are purge windows, so a 21-session outcome cannot
    cross into the following evidence window.
    """
    sessions = _evaluation_sessions(evaluation_start, evaluation_end_exclusive)
    count = len(sessions)
    development_boundary = (count * 3) // 5
    oos_boundary = (count * 4) // 5
    development_stop = development_boundary - _PURGE_SESSIONS
    validation_stop = oos_boundary - _PURGE_SESSIONS
    if development_stop < 1 or validation_stop <= development_boundary:
        raise ContractViolation(
            "evaluation range is too short for non-empty 60/20/20 windows "
            "and two 21-session purges"
        )
    windows = (
        _window(
            kind="development",
            sessions=sessions[:development_stop],
            full_sessions=sessions,
            stop_index=development_stop,
            evaluation_end_exclusive=evaluation_end_exclusive,
        ),
        _window(
            kind="development_validation_purge",
            sessions=sessions[development_stop:development_boundary],
            full_sessions=sessions,
            stop_index=development_boundary,
            evaluation_end_exclusive=evaluation_end_exclusive,
        ),
        _window(
            kind="validation",
            sessions=sessions[development_boundary:validation_stop],
            full_sessions=sessions,
            stop_index=validation_stop,
            evaluation_end_exclusive=evaluation_end_exclusive,
        ),
        _window(
            kind="validation_oos_purge",
            sessions=sessions[validation_stop:oos_boundary],
            full_sessions=sessions,
            stop_index=oos_boundary,
            evaluation_end_exclusive=evaluation_end_exclusive,
        ),
        _window(
            kind="oos",
            sessions=sessions[oos_boundary:],
            full_sessions=sessions,
            stop_index=count,
            evaluation_end_exclusive=evaluation_end_exclusive,
        ),
    )
    return EvaluationSplit(
        version=SPLIT_VERSION,
        evaluation_start=evaluation_start,
        evaluation_end_exclusive=evaluation_end_exclusive,
        development_fraction=Decimal("0.60"),
        validation_fraction=Decimal("0.20"),
        oos_fraction=Decimal("0.20"),
        purge_entry_sessions=_PURGE_SESSIONS,
        session_count=count,
        sessions_identity=identity_hash(_SESSION_DOMAIN, sessions),
        development=windows[0],
        development_validation_purge=windows[1],
        validation=windows[2],
        validation_oos_purge=windows[3],
        oos=windows[4],
    )


def evaluation_split_document(split: EvaluationSplit) -> dict[str, object]:
    """Return the strict JSON interchange form used by study bundles."""
    if not isinstance(split, EvaluationSplit):
        raise ContractViolation("split must be an EvaluationSplit")

    def window(value: SplitWindow) -> dict[str, object]:
        return {
            "start": value.start.isoformat(),
            "end_exclusive": value.end_exclusive.isoformat(),
            "session_count": value.session_count,
            "sessions_identity": value.sessions_identity,
        }

    return {
        "version": split.version,
        "evaluation_start": split.evaluation_start.isoformat(),
        "evaluation_end_exclusive": split.evaluation_end_exclusive.isoformat(),
        "development_fraction": str(split.development_fraction),
        "validation_fraction": str(split.validation_fraction),
        "oos_fraction": str(split.oos_fraction),
        "purge_entry_sessions": split.purge_entry_sessions,
        "session_count": split.session_count,
        "sessions_identity": split.sessions_identity,
        "development": window(split.development),
        "development_validation_purge": window(
            split.development_validation_purge
        ),
        "validation": window(split.validation),
        "validation_oos_purge": window(split.validation_oos_purge),
        "oos": window(split.oos),
    }


__all__ = ["derive_evaluation_split", "evaluation_split_document"]
