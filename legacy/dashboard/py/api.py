"""All /api/* endpoints (session enforced by AuthMiddleware in app.py)."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from sts.dashboard import audit, data, jobs, safe_config

_FAMILIES = ("h1", "h2")

router = APIRouter(prefix="/api")


@router.get("/me")
def me(request: Request) -> dict:
    session = request.state.session
    return {"email": session["email"], "role": session["role"]}


@router.get("/overview")
def overview(request: Request) -> dict:
    root = request.app.state.ledger_root
    return {
        "equity": data.equity_series(root),
        "tiles": data.overview_stats(root),
        "open_positions": data.open_positions(root),
        "recent_signals": data.signals(root, limit=50),
    }


@router.get("/forward/{family}")
def forward(family: str, request: Request) -> dict:
    if family not in _FAMILIES:
        raise HTTPException(status_code=404, detail="unknown family")
    root = request.app.state.ledger_root
    rows = data.family_rows(root, family)
    open_ = [r for r in data.open_positions(root) if r.get("family") == family]
    return {"rows": rows, "open": open_}


@router.get("/config")
def config(request: Request) -> dict:
    repo_root = request.app.state.repo_root
    body = data.config_view(repo_root)
    body["editable"] = safe_config.read_settings(repo_root)
    return body


_BULK_KEYS = ("trades", "equity_curve")


@router.get("/backtests")
def backtests(request: Request) -> list[dict]:
    summaries = data.runs_summary(request.app.state.repo_root)
    return [
        {k: v for k, v in s.items() if k not in _BULK_KEYS} for s in summaries.values()
    ]


@router.get("/backtests/{family}")
def backtest_detail(family: str, request: Request) -> dict:
    s = data.runs_summary_family(request.app.state.repo_root, family)
    if s is None:
        raise HTTPException(status_code=404, detail="unknown family")
    return s


@router.get("/jobs")
def jobs_status(request: Request) -> list[dict]:
    return jobs.job_status(request.app.state.repo_root)


@router.post("/sync")
def sync_now(request: Request) -> dict:
    repo_root = request.app.state.repo_root
    try:
        sync_id = jobs.start_sync(repo_root)
    except jobs.SyncInProgress:
        raise HTTPException(status_code=409, detail="sync already running")
    audit.log("sync", request.state.session["email"], {"id": sync_id}, root=repo_root)
    return {"id": sync_id}


@router.get("/sync/{sync_id}")
def sync_status(sync_id: str, request: Request) -> dict:
    state = jobs.sync_state(request.app.state.repo_root, sync_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown sync id")
    return state


@router.put("/config/safe")
def config_safe(request: Request, updates: dict = Body(...)) -> dict:
    # AuthMiddleware already enforces admin on mutating methods.
    repo_root = request.app.state.repo_root
    errors = safe_config.validate(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    old, new = safe_config.apply_updates(repo_root, updates)
    audit.log(
        "config_edit",
        request.state.session["email"],
        {"old": old, "new": new, "changed": sorted(updates)},
        root=repo_root,
    )
    return new
