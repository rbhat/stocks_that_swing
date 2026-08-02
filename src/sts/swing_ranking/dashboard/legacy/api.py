"""Namespaced API matching the retired dashboard's decision-relevant payloads."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request

from sts.swing_ranking.dashboard import audit
from sts.swing_ranking.dashboard.legacy import admin, data, jobs, safe_config

_FAMILIES = ("h1", "h2")
_BULK_KEYS = ("trades", "equity_curve")

router = APIRouter(prefix="/api/legacy")


def _runner(request: Request) -> tuple[str | None, str | None]:
    return request.app.state.legacy_admin_url, request.app.state.legacy_admin_token


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    roots = request.app.state.legacy_roots
    return {
        "equity": data.equity_series(roots.ledger),
        "tiles": data.overview_stats(roots.ledger),
        "open_positions": data.open_positions(roots.ledger),
        "recent_signals": data.signals(roots.ledger, limit=50),
    }


@router.get("/forward/{family}")
def forward(family: str, request: Request) -> dict[str, Any]:
    if family not in _FAMILIES:
        raise HTTPException(status_code=404, detail="unknown family")
    roots = request.app.state.legacy_roots
    opened = data.open_positions(roots.ledger)
    return {
        "rows": data.family_rows(roots.ledger, family),
        "open": [row for row in opened if row.get("family") == family],
    }


@router.get("/backtests")
def backtests(request: Request) -> list[dict[str, Any]]:
    summaries = data.runs_summary(request.app.state.legacy_roots.runs_summary)
    return [
        {key: value for key, value in summary.items() if key not in _BULK_KEYS}
        for summary in summaries.values()
    ]


@router.get("/backtests/{family}")
def backtest_detail(family: str, request: Request) -> dict[str, Any]:
    summary = data.runs_summary_family(request.app.state.legacy_roots.runs_summary, family)
    if summary is None:
        raise HTTPException(status_code=404, detail="unknown family")
    return summary


@router.get("/config")
def config(request: Request) -> dict[str, Any]:
    roots = request.app.state.legacy_roots
    return {
        **data.config_view(roots),
        "editable": data.read_settings(roots.configs),
        "schema": {
            key: spec["constraint"] for key, spec in safe_config.SAFE_SCHEMA.items()
        },
    }


@router.get("/jobs")
def job_status(request: Request) -> list[dict[str, str | None]]:
    return jobs.job_status(request.app.state.legacy_roots.logs)


@router.post("/sync")
def sync_now(request: Request) -> dict[str, Any]:
    try:
        result = admin.start_sync(*_runner(request))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="sync already running") from exc
    except admin.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.log(
        "sync",
        request.state.session["email"],
        {"id": result.get("id")},
        root=request.app.state.repo_root,
        scope="legacy",
        target="sync",
    )
    return result


@router.get("/sync/{sync_id}")
def sync_status(sync_id: str, request: Request) -> dict[str, Any]:
    try:
        return admin.sync_state(*_runner(request), sync_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown sync id") from exc
    except admin.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/config/safe")
def config_safe(request: Request, updates: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    errors = safe_config.validate(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    try:
        result = admin.update_config(*_runner(request), updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=exc.args[0]) from exc
    except admin.RunnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    audit.log(
        "config_edit",
        request.state.session["email"],
        {
            "before": result.get("old", {}),
            "after": result.get("new", {}),
            "changed": sorted(updates),
        },
        root=request.app.state.repo_root,
        scope="legacy",
        target="configs/dashboard_settings.yaml",
    )
    return result.get("new", {})
