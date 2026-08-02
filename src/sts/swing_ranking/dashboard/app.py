"""FastAPI app wiring: auth middleware + routes, healthz, API, SPA fallback.

`create_app` is the sole entry point, used by the tests, by
`scripts/run_swing_dashboard.py`, and by the `dashboard` compose service.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from sts.swing_ranking.dashboard.api import router as api_router
from sts.swing_ranking.dashboard.auth import (
    AuthMiddleware,
    get_secret,
    install_auth_routes,
)
from sts.swing_ranking.dashboard.legacy import LegacyRoots
from sts.swing_ranking.dashboard.legacy.api import router as legacy_api_router


def create_app(
    runs_root: Path = Path("runs"),
    repo_root: Path = Path("."),
    *,
    dist_dir: Path | None = None,
    legacy_roots: LegacyRoots | None = None,
    legacy_admin_url: str | None = None,
    legacy_admin_token: str | None = None,
) -> FastAPI:
    runs_root = Path(runs_root)
    repo_root = Path(repo_root)
    secret = get_secret()

    app = FastAPI(title="Swing ranking v1 dashboard")
    app.state.runs_root = runs_root
    app.state.repo_root = repo_root
    app.state.legacy_roots = legacy_roots or LegacyRoots.under(repo_root / "legacy")
    app.state.legacy_admin_url = legacy_admin_url
    app.state.legacy_admin_token = legacy_admin_token

    app.add_middleware(AuthMiddleware, secret=secret)
    # Outermost: authlib's Google flow stores OAuth state in request.session.
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax")

    dist = Path(dist_dir) if dist_dir is not None else repo_root / "frontend" / "dist"
    assets_dir = dist / "assets"

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    install_auth_routes(app, repo_root=repo_root, secret=secret)
    app.include_router(api_router)
    app.include_router(legacy_api_router)

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/favicon.svg")
    def favicon():
        icon = dist / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon)
        return JSONResponse(status_code=404, content={"error": "not_found"})

    @app.get("/project-report.html")
    def standalone_project_report():
        report = dist / "project-report.html"
        if report.is_file():
            return FileResponse(report)
        return JSONResponse(status_code=404, content={"error": "not_found"})

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        index_path = dist / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return JSONResponse(status_code=503, content={"error": "spa_not_built"})

    return app
