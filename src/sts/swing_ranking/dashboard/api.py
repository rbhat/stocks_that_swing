"""Read-only JSON API over the forward ledger and the sealed backtests.

Route shapes follow the legacy dashboard's (`/api/me`, `/api/overview`,
`/api/forward/{...}`, `/api/backtests/{...}`); the payloads do not, because the
legacy family split `h1`/`h2` maps onto nothing here. The axis is the charter's:
cohorts VF9, MC5, and FO4 over nine revision identities.

Nothing in this module writes. Every handler reads through
`sts.swing_ranking.dashboard.data`, which degrades rather than raising, so a
missing or hash-divergent run still renders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sts.swing_ranking.dashboard import data

router = APIRouter(prefix="/api")


def _runs_root(request: Request) -> Path:
    return Path(request.app.state.runs_root)


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    session = getattr(request.state, "session", None) or {}
    return {"email": session.get("email"), "role": session.get("role")}


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    """The landing payload: forward run first, then the backtest evidence."""
    payload = data.overview(_runs_root(request))
    payload["legacy_dashboard_url"] = request.app.state.legacy_dashboard_url
    return payload


@router.get("/forward")
def forward(request: Request) -> dict[str, Any]:
    return data.forward_overview(_runs_root(request))


@router.get("/forward/open-positions")
def forward_open_positions(request: Request) -> dict[str, Any]:
    return {"positions": data.forward_open_positions(_runs_root(request))}


@router.get("/forward/sessions")
def forward_sessions(request: Request) -> dict[str, Any]:
    return {"sessions": data.forward_sessions(_runs_root(request))}


@router.get("/forward/{cohort}")
def forward_cohort(cohort: str, request: Request):
    """One cohort. FO4 is diagnostic-only; the payload says so, per charter."""
    payload = data.forward_cohort(_runs_root(request), cohort)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "unknown_cohort"})
    return payload


@router.get("/backtests")
def backtests(request: Request) -> dict[str, Any]:
    runs_root = _runs_root(request)
    return {
        "windows": data.backtest_windows(runs_root),
        "seal": data.seal(runs_root),
    }


@router.get("/backtests/cohorts")
def backtest_cohorts(request: Request) -> dict[str, Any]:
    """The sealed OOS cohort analysis.

    Declared before `/backtests/{window}` so the literal path wins. Its equity
    is OOS equity and is returned on its own; the charter forbids joining it to
    the forward curve, so no endpoint offers the two concatenated.
    """
    return data.cohort_comparison(_runs_root(request))


@router.get("/backtests/{window}")
def backtest_window(window: str, request: Request):
    payload = data.backtest_window(_runs_root(request), window)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "unknown_window"})
    return payload
