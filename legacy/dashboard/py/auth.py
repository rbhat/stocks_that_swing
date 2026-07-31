"""Sessions, users.yaml role map, password login, auth middleware.

- Signed httponly session cookie (`sts_session`, itsdangerous
  URLSafeTimedSerializer); `Secure` iff env DASHBOARD_TLS=1.
- `configs/dashboard_users.yaml`: `google: {email: role}` +
  `password_users: {user: {hash: <bcrypt>, role: viewer}}`. Password
  users are ALWAYS viewer regardless of yaml content.
- Middleware: every route except /healthz, /login, /auth/*, /assets/*
  requires a session; unauthenticated /api/* -> 401 JSON, others ->
  redirect /login; mutating methods (POST/PUT/PATCH/DELETE) require
  role=admin -> else 403.
- Secret from env DASHBOARD_SECRET; a dev default is permitted only
  when DASHBOARD_DEV=1.
"""

from __future__ import annotations

import os
import posixpath
from pathlib import Path

import bcrypt
import yaml
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from sts.dashboard import audit

SESSION_COOKIE = "sts_session"
_SALT = "sts-dashboard-session"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_OPEN_PREFIXES = ("/auth/", "/assets/")
_OPEN_PATHS = {"/healthz", "/login"}


def get_secret() -> str:
    secret = os.environ.get("DASHBOARD_SECRET")
    if secret:
        return secret
    if os.environ.get("DASHBOARD_DEV") == "1":
        return "dev-insecure-secret"
    raise RuntimeError("DASHBOARD_SECRET env var is required (or set DASHBOARD_DEV=1)")


# ---------------------------------------------------------------------------
# users.yaml
# ---------------------------------------------------------------------------


class Users:
    def __init__(self, google: dict[str, str], password_users: dict[str, dict]):
        self._google = google
        self._password_users = password_users

    def role_for_google(self, email: str) -> str | None:
        return self._google.get(email)

    def check_password(self, user: str, pw: str) -> str | None:
        """Return role on success, None otherwise. Password users are
        ALWAYS viewer regardless of yaml content."""
        rec = self._password_users.get(user)
        if not rec or not rec.get("hash"):
            return None
        try:
            ok = bcrypt.checkpw(pw.encode(), rec["hash"].encode())
        except ValueError:
            return None
        return "viewer" if ok else None


def load_users(path: Path) -> Users:
    path = Path(path)
    raw: dict = {}
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            raw = {}
    return Users(raw.get("google") or {}, raw.get("password_users") or {})


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def make_session(email: str, role: str, secret: str) -> str:
    return _serializer(secret).dumps({"email": email, "role": role})


def read_session(cookie: str, secret: str, max_age: int = 86400 * 7) -> dict | None:
    try:
        data = _serializer(secret).loads(cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or "email" not in data or "role" not in data:
        return None
    return data


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("DASHBOARD_TLS") == "1",
        max_age=86400 * 7,
    )


# ---------------------------------------------------------------------------
# middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret

    async def dispatch(self, request: Request, call_next):
        path = posixpath.normpath(request.url.path)
        if path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES):
            return await call_next(request)

        cookie = request.cookies.get(SESSION_COOKIE)
        session = read_session(cookie, self._secret) if cookie else None
        if session is None:
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"error": "unauthenticated"})
            return RedirectResponse(url="/login", status_code=303)

        if request.method in _MUTATING and session["role"] != "admin":
            return JSONResponse(status_code=403, content={"error": "forbidden"})

        request.state.session = session
        return await call_next(request)


# ---------------------------------------------------------------------------
# login routes (installed by app.create_app)
# ---------------------------------------------------------------------------


def _google_client(app):
    """Return the OAuth client: a test-injected `app.state.oauth_google`,
    else a real authlib client built lazily from env GOOGLE_CLIENT_ID /
    GOOGLE_CLIENT_SECRET. None if unconfigured.

    Redirect URI to register on the Google credential:
    `http://localhost:8000/auth/google/callback` for IAP-tunnel use, plus
    the future public host when going public.
    """
    client = getattr(app.state, "oauth_google", None)
    if client is not None:
        return client
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    app.state.oauth_google = oauth.google
    return oauth.google


def install_auth_routes(app, repo_root: Path, secret: str) -> None:
    from fastapi import Form

    users_path = Path(repo_root) / "configs" / "dashboard_users.yaml"

    @app.post("/auth/password")
    def password_login(username: str = Form(...), password: str = Form(...)):
        users = load_users(users_path)
        role = users.check_password(username, password)
        if role is None:
            audit.log("login_failed", username, {"method": "password"}, root=repo_root)
            return JSONResponse(status_code=401, content={"error": "bad_credentials"})
        audit.log("login", username, {"method": "password", "role": role}, root=repo_root)
        resp = JSONResponse(content={"ok": True, "role": role})
        set_session_cookie(resp, make_session(username, role, secret))
        return resp

    @app.get("/auth/google")
    async def google_login(request: Request):
        client = _google_client(app)
        if client is None:
            return JSONResponse(status_code=503, content={"error": "google_oauth_not_configured"})
        redirect_uri = str(request.url_for("google_callback"))
        return await client.authorize_redirect(request, redirect_uri)

    @app.get("/auth/google/callback")
    async def google_callback(request: Request):
        client = _google_client(app)
        if client is None:
            return JSONResponse(status_code=503, content={"error": "google_oauth_not_configured"})
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo") or {}
        email = userinfo.get("email")
        role = load_users(users_path).role_for_google(email) if email else None
        if role is None:
            audit.log(
                "login_rejected", email or "<no-email>", {"method": "google"}, root=repo_root
            )
            return JSONResponse(
                status_code=403,
                content={"error": "not_authorized", "detail": "This account is not on the access list."},
            )
        audit.log("login", email, {"method": "google", "role": role}, root=repo_root)
        resp = RedirectResponse(url="/", status_code=303)
        set_session_cookie(resp, make_session(email, role, secret))
        return resp

    @app.post("/auth/logout")
    def logout(request: Request):
        session = getattr(request.state, "session", None)
        if session:
            audit.log("logout", session["email"], {}, root=repo_root)
        resp = JSONResponse(content={"ok": True})
        resp.delete_cookie(SESSION_COOKIE)
        return resp
