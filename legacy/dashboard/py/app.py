"""FastAPI app wiring: auth middleware + routes, healthz, SPA fallback.

`create_app` is the sole entry point used by tests, `scripts/dashboard_serve.py`,
and (later) the docker image. Additional routers are wired in here by later
tasks (api).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from sts.dashboard.api import router as api_router
from sts.dashboard.auth import AuthMiddleware, get_secret, install_auth_routes


def create_app(ledger_root: Path = Path("ledger"), repo_root: Path = Path(".")) -> FastAPI:
    ledger_root = Path(ledger_root)
    repo_root = Path(repo_root)
    secret = get_secret()

    app = FastAPI()
    app.state.ledger_root = ledger_root
    app.state.repo_root = repo_root

    app.add_middleware(AuthMiddleware, secret=secret)
    # Outermost: authlib's Google flow stores OAuth state in request.session.
    app.add_middleware(SessionMiddleware, secret_key=secret, same_site="lax")

    dist_dir = repo_root / "dashboard" / "dist"
    assets_dir = dist_dir / "assets"

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    install_auth_routes(app, repo_root=repo_root, secret=secret)
    app.include_router(api_router)

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        index_path = dist_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return JSONResponse(status_code=503, content={"error": "spa_not_built"})

    return app
