# STS Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full-SPA admin dashboard (React + FastAPI) for the forward-paper pipeline: overview/ledgers/backtests/config/jobs, Google OAuth admin + viewer roles, sync-on-demand, Aurora dark-first design.

**Architecture:** FastAPI JSON API (`src/sts/dashboard/`) reads the VM's ledgers/configs/logs defensively and serves the built Vite+React SPA (`dashboard/dist/`). Auth = signed session cookie; Google OAuth or bcrypt password login mapped to roles via `configs/dashboard_users.yaml`. A laptop exporter distills `runs/` into `runs-summary/` JSON shipped by deploy.sh.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, authlib, itsdangerous, bcrypt, pytest / Vite, React 18, TypeScript, Tailwind v4, shadcn/ui, TanStack Query + Table, ECharts, cmdk.

**Spec:** `docs/superpowers/specs/2026-07-13-sts-dashboard-design.md` — read it first; it governs on any ambiguity.

## Global Constraints

- Python ≥3.12; SPA build only in Docker build stage (VM never runs Node).
- Dashboard NEVER writes ledgers. Only mutations: `POST /api/sync` (runs `scripts/forward_sync.py`) and `PUT /api/config/safe` (allowlisted keys only).
- Every route except `/login`, `/auth/*`, `/healthz`, static assets requires a session; mutating methods require role=admin (server-side middleware, not just UI).
- All file reads defensive: missing/corrupt → typed unavailable state, never 500.
- Aurora tokens (exact values in spec §UX): dark bg `#0B0E14`, surface `#131722`, primary `#7C6CFF`, accent `#2DD4BF`, gain `#34D399`, loss `#FB7185`. Both themes WCAG AA. Respect `prefers-reduced-motion`.
- Session cookie: signed, httponly, `Secure` iff env `DASHBOARD_TLS=1`.
- Audit every login, failed login, sync trigger, config edit to `logs/dashboard-audit.log`.
- Commit after every task; run `pytest` (backend) / `npm test` (frontend) before each commit.

## File Structure

```
src/sts/dashboard/__init__.py
src/sts/dashboard/app.py        # create_app(): wiring, middleware, SPA fallback
src/sts/dashboard/auth.py       # sessions, users.yaml, password + google login, roles
src/sts/dashboard/data.py       # read layer: ledger, equity, signals, configs, runs-summary
src/sts/dashboard/jobs.py       # job status from logs + cron spec; sync runner with lock
src/sts/dashboard/audit.py      # append-only audit log
src/sts/dashboard/api.py        # APIRouter: all /api/* endpoints
scripts/dashboard_serve.py      # uvicorn entry
scripts/dashboard_user.py       # CLI: add/update bcrypt password user
scripts/export_runs_summary.py  # laptop: runs/ -> runs-summary/*.json
configs/dashboard_users.yaml
dashboard/                      # Vite app (src/{main.tsx,routes/,components/,lib/,theme.css})
tests/dashboard/test_{data,auth,api,jobs,config_edit}.py
```

---

### Task 1: Backend scaffold + healthz + SPA fallback

**Files:** Create `src/sts/dashboard/{__init__.py,app.py}`, `scripts/dashboard_serve.py`, `tests/dashboard/test_app.py`. Modify `pyproject.toml` (add optional group `dashboard = ["fastapi>=0.111", "uvicorn>=0.30", "authlib>=1.3", "itsdangerous>=2.2", "bcrypt>=4.1", "httpx>=0.27", "python-multipart>=0.0.9"]`; add `httpx` to dev for tests).

**Interfaces:** Produces `create_app(ledger_root: Path = Path("ledger"), repo_root: Path = Path(".")) -> FastAPI`.

- [ ] **Step 1: failing test**

```python
# tests/dashboard/test_app.py
from pathlib import Path
from fastapi.testclient import TestClient
from sts.dashboard.app import create_app

def test_healthz_no_auth(tmp_path):
    client = TestClient(create_app(ledger_root=tmp_path, repo_root=tmp_path))
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}

def test_spa_fallback_when_no_dist(tmp_path):
    client = TestClient(create_app(ledger_root=tmp_path, repo_root=tmp_path))
    assert client.get("/some/route").status_code in (200, 503)  # 503 "SPA not built" JSON when dist missing
```

- [ ] **Step 2:** `pip install -e ".[dashboard,dev]"` then `pytest tests/dashboard/test_app.py -v` → FAIL (module missing).
- [ ] **Step 3: implement** `app.py`: `create_app()` builds FastAPI, mounts `/healthz`, and a catch-all GET that serves `dashboard/dist/index.html` if present (assets via `StaticFiles` at `/assets`), else JSON 503 `{"error":"spa_not_built"}`. Keep `create_app` the sole entry; `scripts/dashboard_serve.py` runs `uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("DASHBOARD_PORT", 8000)))`.
- [ ] **Step 4:** `pytest tests/dashboard -v` → PASS.
- [ ] **Step 5:** `git add -A && git commit -m "feat(dashboard): FastAPI scaffold with healthz + SPA fallback"`

### Task 2: data.py read layer

**Files:** Create `src/sts/dashboard/data.py`, `tests/dashboard/test_data.py`.

**Interfaces:** Produces (all return plain dicts/lists, never raise on missing/corrupt files):
- `read_jsonl(path: Path) -> list[dict]` (skips corrupt lines)
- `equity_series(root: Path) -> list[dict]` (from `equity.jsonl`, sorted by date, per `book`)
- `family_rows(root: Path, family: str) -> list[dict]` (family in {"h1","h2"}, from `{family}.jsonl`)
- `open_positions(root: Path) -> list[dict]` (reuse `sts.forward.ledger.Ledger.open_rows` semantics — replay rows, keep entries without a matching exit; read-only reimplementation, do NOT instantiate the writing `Ledger`)
- `signals(root: Path, limit: int = 200) -> list[dict]`
- `config_view(repo_root: Path) -> dict` — `universe.yaml`, `configs/study_roster.yaml` parsed; `.env` keys with values redacted except non-secret allowlist `{"TZ","DASHBOARD_PORT"}`
- `runs_summary(repo_root: Path) -> dict` / `runs_summary_family(repo_root: Path, family: str) -> dict | None` (reads `runs-summary/*.json`)

- [ ] **Step 1: failing tests** — cover: missing dir → empty results; corrupt jsonl line skipped; open_positions pairs entry/exit rows correctly (write 3 rows: two entries, one exit → one open); `.env` values redacted (`FOO=secret` appears as `FOO` with value `"•••"`).

```python
def test_read_jsonl_skips_corrupt(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nnot json\n{"a":2}\n')
    assert data.read_jsonl(p) == [{"a": 1}, {"a": 2}]

def test_open_positions(tmp_path):
    h1 = tmp_path / "h1.jsonl"
    rows = [
        {"kind": "entry", "entry_id": "e1", "family": "h1", "symbol": "AAA"},
        {"kind": "entry", "entry_id": "e2", "family": "h1", "symbol": "BBB"},
        {"kind": "exit", "entry_id": "e1", "family": "h1", "symbol": "AAA"},
    ]
    h1.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    open_ = data.open_positions(tmp_path)
    assert [r["entry_id"] for r in open_] == ["e2"]
```

Before implementing, read `src/sts/forward/ledger.py` for the real row schema (`kind`, `entry_id`, `book`, `family`, …) and mirror its open/closed pairing rules exactly.

- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(dashboard): defensive data read layer`.

### Task 3: auth.py — sessions, password login, roles, middleware

**Files:** Create `src/sts/dashboard/auth.py`, `src/sts/dashboard/audit.py`, `configs/dashboard_users.yaml` (with `google: {rajeevmbhat@gmail.com: admin}`, empty `password_users: {}`), `scripts/dashboard_user.py`, `tests/dashboard/test_auth.py`. Modify `app.py` to install middleware + login routes. Add Makefile target `dashboard-user`.

**Interfaces:** Produces:
- `load_users(path: Path) -> Users` (`Users.role_for_google(email) -> str | None`, `Users.check_password(user, pw) -> str | None` returning role)
- `make_session(email: str, role: str, secret: str) -> str` / `read_session(cookie: str, secret: str, max_age: int = 86400*7) -> dict | None` (itsdangerous `URLSafeTimedSerializer`)
- `AuthMiddleware` — skips `/healthz`, `/login`, `/auth/`, `/assets/`; 401 JSON for unauthenticated `/api/*`, redirect to `/login` otherwise; 403 for non-admin on POST/PUT/PATCH/DELETE
- `audit.log(event: str, who: str, detail: dict, root: Path)` → appends JSON line to `logs/dashboard-audit.log`
- Routes: `POST /auth/password` (form user/password → sets cookie `sts_session`), `POST /auth/logout`
- Secret from env `DASHBOARD_SECRET` (required in prod; test default allowed only when `DASHBOARD_DEV=1`)

- [ ] **Step 1: failing tests** — role matrix:

```python
def test_viewer_cannot_post(client_viewer):   # fixture logs in as password viewer
    assert client_viewer.post("/api/sync").status_code == 403

def test_unauthenticated_api_401(client):
    assert client.get("/api/me").status_code == 401

def test_password_login_sets_cookie_and_role(client):
    r = client.post("/auth/password", data={"username": "guest", "password": "pw"})
    assert r.status_code == 200
    assert client.get("/api/me").json()["role"] == "viewer"

def test_bad_password_audited(client, tmp_path):
    client.post("/auth/password", data={"username": "guest", "password": "wrong"})
    log = (tmp_path / "logs/dashboard-audit.log").read_text()
    assert "login_failed" in log
```

Fixtures build a users.yaml in tmp_path with a bcrypt hash for `guest`. Password users are ALWAYS viewer regardless of yaml content.

- [ ] **Steps 2–4:** fail → implement → pass. `scripts/dashboard_user.py` prompts for username/password, writes bcrypt hash into the yaml. **Step 5:** commit `feat(dashboard): session auth, password viewers, role middleware, audit log`.

### Task 4: Google OAuth login

**Files:** Modify `auth.py`, `app.py`; create `tests/dashboard/test_google_oauth.py`.

**Interfaces:** `GET /auth/google` → authlib redirect; `GET /auth/google/callback` → fetch userinfo email, `role_for_google(email)`; unlisted → 403 page + `login_rejected` audit; listed → session cookie + redirect `/`. Env: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (document redirect URI `http://localhost:8000/auth/google/callback` for tunnel use; note in README the credential must also list the future public host).

- [ ] **Step 1: failing tests** — mock authlib client (`app.state.oauth_google`) so callback returns a fake email; assert admin email → role admin; unlisted email → 403 and no cookie.
- [ ] **Steps 2–4:** fail → implement → pass. **Step 5:** commit `feat(dashboard): google oauth login with email role map`.

### Task 5: Core read API

**Files:** Create `src/sts/dashboard/api.py`, `tests/dashboard/test_api.py`. Modify `app.py` to include router.

**Interfaces (all GET, session required):**
- `/api/me` → `{"email","role"}`
- `/api/overview` → `{"equity": [...], "tiles": {"total_pnl","open_count","usd_deployed","win_rate"}, "open_positions": [...], "recent_signals": [...]}` (tiles computed in `data.py` helper `overview_stats(root)`; win_rate = wins/closed from exit rows, `None` when no closed trades)
- `/api/forward/{family}` → 404 unless family in {"h1","h2"}; `{"rows": [...], "open": [...]}`
- `/api/config` → `config_view()` output plus `{"editable": current safe-subset values}`

- [ ] **Step 1: failing tests** using an authed admin client fixture against a tmp ledger seeded with a few rows; assert shapes above, and `/api/forward/h9` → 404, empty ledger → 200 with empty lists (never 500).
- [ ] **Steps 2–4** fail → implement → pass. **Step 5:** commit `feat(dashboard): read API (me/overview/forward/config)`.

### Task 6: Safe config edit

**Files:** Create `src/sts/dashboard/safe_config.py`, `tests/dashboard/test_config_edit.py`. Modify `api.py`.

**Interfaces:**
- Safe subset lives in `configs/dashboard_settings.yaml` (created on first write), NOT in strategy configs. Allowlist schema (hardcoded dict `SAFE_SCHEMA`): `discord_alerts: bool`, `monitor_gap_alert_pct: float 0<x<=0.5`, `monitor_dd_alert_pct: float 0<x<=0.5`.
- `PUT /api/config/safe` body `{"key": value, ...}` — admin only; unknown key → 422; type/range violation → 422; atomic write (tmp+rename); audit entry with old/new values; response = full new settings.
- Pipeline consumption of these settings is OUT OF SCOPE here (separate change); the file format is the contract.

- [ ] **Step 1: failing tests:** unknown key 422; bad range 422; viewer 403; valid edit persists + audited.
- [ ] **Steps 2–4** fail → implement → pass. **Step 5:** commit `feat(dashboard): allowlisted safe config editing with audit`.

### Task 7: Jobs status + sync-on-demand

**Files:** Create `src/sts/dashboard/jobs.py`, `tests/dashboard/test_jobs.py`. Modify `api.py`.

**Interfaces:**
- `job_status(repo_root: Path) -> list[dict]` — for eod/fill/monitor/sync: parse tail of `logs/forward/{name}.log` (fallback `logs/{name}.log`, matching VM layout) for last run timestamp + success/failure marker; compute `next_run` from hardcoded cron spec table (mirrors FORWARD_OPS schedule, PT). Missing log → `{"status":"unknown"}`.
- `start_sync(repo_root: Path) -> str` — admin; refuses (409) if lockfile `logs/dashboard-sync.lock` held (use `os.O_CREAT|os.O_EXCL`, stale after 30 min); runs `sys.executable scripts/forward_sync.py` via `subprocess.Popen`, captures output to `logs/dashboard-sync-{id}.log`, records state json `logs/dashboard-sync-{id}.json` (`running|ok|failed`, updated by a background thread on process exit; lock released there too).
- Routes: `GET /api/jobs`, `POST /api/sync` → `{"id"}`, `GET /api/sync/{id}` → state json.

- [ ] **Step 1: failing tests:** second sync while lock held → 409; completed fake process (monkeypatch Popen with instant-exit stub) → state `ok`; `job_status` parses a seeded fake log line and reports unknown for missing logs.
- [ ] **Steps 2–4** fail → implement → pass. **Step 5:** commit `feat(dashboard): job status + locked sync-on-demand`.

### Task 8: Backtest exporter + API

**Files:** Create `scripts/export_runs_summary.py`, `tests/dashboard/test_runs_summary.py`. Modify `api.py`, `deploy/deploy.sh` (ship `runs-summary/` to VM like configs).

**Interfaces:**
- Exporter CLI: `python scripts/export_runs_summary.py --runs runs --out runs-summary`. For each family dir found (h1,h2,h3,h4,h4b and nested `{phase}/{family}` report.json files), emit `runs-summary/{family}.json`: `{"family", "generated_at", "source_paths": [...], "verdict": <from docs/decisions.md if greppable, else null>, "metrics": <report.json minus bulky keys>, "equity_curve": <downsampled to ≤500 points if an equity artifact exists, else null>, "trades": <trade list if artifact exists, else null>}`. Inspect actual `runs/` artifacts while implementing; missing artifacts → nulls, never crash. Idempotent, fast, re-runnable.
- Routes: `GET /api/backtests` → list of summaries sans trades/curve; `GET /api/backtests/{family}` → full file or 404.

- [ ] **Step 1: failing tests:** exporter over a tmp fake runs tree (one report.json) produces valid summary json; API returns list + 404 for unknown family.
- [ ] **Steps 2–4** fail → implement → pass; also run the exporter for real: `python scripts/export_runs_summary.py` and eyeball output. **Step 5:** commit `feat(dashboard): runs-summary exporter + backtests API`.

### Task 9: SPA scaffold — Vite, Tailwind v4, Aurora tokens, router, auth guard, login page

**Files:** Create `dashboard/` via `npm create vite@latest dashboard -- --template react-ts`; add `tailwindcss @tailwindcss/vite`, `@tanstack/react-query`, `react-router-dom`, `echarts`, `echarts-for-react`, `@tanstack/react-table`, `cmdk`, shadcn/ui init (`npx shadcn@latest init`, components: button, card, tabs, table, dialog, toast/sonner, badge, input, dropdown-menu). Create `dashboard/src/theme.css`, `src/lib/api.ts`, `src/lib/auth.tsx`, `src/routes/Login.tsx`, `src/App.tsx` router skeleton with all five routes stubbed.

**Interfaces:** Produces for later tasks:
- `api<T>(path: string, init?: RequestInit): Promise<T>` — fetch with `credentials: "include"`, throws `ApiError(status)`; 401 → redirect `/login`.
- `useMe()` — query of `/api/me`; `RequireAuth` wrapper component; `isAdmin` boolean.
- Theme: `theme.css` defines Aurora tokens as CSS vars under `:root[data-theme=dark]` and `[data-theme=light]` (exact hexes from Global Constraints/spec); `useTheme()` hook (localStorage `sts-theme`, default `prefers-color-scheme`); Tailwind v4 `@theme` maps vars to utility colors (`bg-surface`, `text-gain`, …).
- Vite dev proxy: `/api`, `/auth`, `/healthz` → `http://127.0.0.1:8000`.

- [ ] **Step 1:** scaffold + install; `npm run dev` renders stub. **Step 2:** write `theme.css` tokens + toggle; verify both themes by flipping. **Step 3:** Vitest + Testing Library setup; failing test: `Login` posts form to `/auth/password` (msw or fetch mock) and navigates on 200; `RequireAuth` redirects unauthenticated. **Step 4:** implement Login (two cards: "Sign in with Google" → `location.href="/auth/google"`, and username/password form), auth lib. Tests pass. **Step 5:** `npm run build` succeeds; commit `feat(dashboard-ui): SPA scaffold, aurora theme, auth guard, login`.

### Task 10: App shell + Overview page

**Files:** Create `dashboard/src/components/{Shell.tsx,StatTile.tsx,JobCard.tsx,EquityChart.tsx,SyncButton.tsx,CommandPalette.tsx}`, `src/routes/Overview.tsx`, tests alongside.

**Interfaces:** Consumes `/api/overview`, `/api/jobs`, `/api/sync`. Shell: icon sidebar (Overview/Forward/Backtests/Config/Jobs, lucide icons), top bar (title, sync pill, theme toggle, avatar + role badge "Admin"/"Read-only"), ⌘K palette (navigate pages + type a ticker → Forward filtered). Overview: EquityChart (ECharts area, violet→teal `linearGradient` fill, crosshair tooltip, downsample ok), 4 StatTiles (count-up via `requestAnimationFrame`, disabled under `prefers-reduced-motion`), open-positions strip, JobCards (pulsing dot while sync running — poll `/api/sync/{id}` every 2s during a run), SyncButton admin-only (viewers render a lock icon + tooltip "Read-only").

- [ ] **Step 1: failing component tests:** SyncButton hidden→lock for viewer role; JobCard shows red state for `failed`; StatTile renders formatted P&L with sign and gain/loss class.
- [ ] **Steps 2–4** implement → tests pass → visual check against local backend (`make serve` + scratch ledger). **Step 5:** commit `feat(dashboard-ui): app shell + overview`.

### Task 11: Forward ledger page

**Files:** `src/routes/Forward.tsx`, `src/components/LedgerTable.tsx` + tests.

**Interfaces:** Consumes `/api/forward/{family}`. h1/h2 tabs (shadcn Tabs); sections Positions (open), Fills, Signals, Alerts (filter rows by `kind`); TanStack Table with column filters + sort; tabular-nums right-aligned; P&L chips (`+x.x%` gain / loss colors, sign always shown); expandable row → raw JSON detail; URL state `?family=h1&f=<ticker>` so ⌘K deep-links work.

- [ ] Steps: failing tests (chip formatting, kind filtering, tab switch fetches other family) → implement → pass → commit `feat(dashboard-ui): forward ledger tables`.

### Task 12: Backtests, Config, Jobs pages

**Files:** `src/routes/{Backtests.tsx,BacktestDetail.tsx,Config.tsx,Jobs.tsx}` + tests.

**Interfaces:**
- Backtests: summary cards (family, verdict Badge — PROCEED gain-green / PARK amber / null gray, headline metrics) → `/backtests/:family` detail: equity curve (EquityChart reused) + trades table (LedgerTable reused) with null-artifact empty states.
- Config: read-only grouped viewers (universe, roster, redacted env — monospace blocks) + "Operational settings" card from `/api/config` `editable`; admin edit inline with validation mirroring SAFE_SCHEMA, save → `PUT /api/config/safe` + typed confirmation dialog ("type SAVE"); viewers see lock icons.
- Jobs: schedule table (from `/api/jobs`), per-job last-run status + next-run.

- [ ] Steps: failing tests (verdict badge mapping, viewer lock on settings, unknown-family 404 state) → implement → pass → commit `feat(dashboard-ui): backtests, config, jobs pages`.

### Task 13: Docker, compose, Makefile, tunnel script

**Files:** Modify `Dockerfile` (multi-stage: `node:22-slim` builds `dashboard/dist`, copy into python stage at `/app/dashboard/dist`; pip install `.[dashboard]`), `deploy/docker-compose.yml` (add `dashboard` service: `command: ["python","scripts/dashboard_serve.py"]`, `ports: ["127.0.0.1:8000:8000"]`, same volumes anchor + `restart: unless-stopped` — this one service IS long-running, note the comment update), `Makefile` (`serve: $(PY) scripts/dashboard_serve.py`), `deploy/deploy.sh` (ship `configs/dashboard_users.yaml`, `runs-summary/`, set `DASHBOARD_SECRET` in VM `.env` if absent, `docker compose up -d dashboard`). Create `deploy/open_remote.sh` ported from stm (`gcloud compute ssh sts-forward --zone us-west1-b --tunnel-through-iap -- -L <freeport>:localhost:8000`, wait `/healthz`, open browser, `--stop` support).

- [ ] Steps: build image locally (`docker build .`) → run container against scratch ledger → curl `/healthz` and `/` (SPA served) → commit `feat(deploy): dashboard service, multi-stage SPA build, open_remote tunnel`.

### Task 14: Docs + end-to-end verification

**Files:** Modify `docs/FORWARD_OPS.md` (dashboard section: URL-via-tunnel, roles, users.yaml management, sync-on-demand semantics vs single-writer policy, Google OAuth credential setup incl. redirect URIs), `README.md` (one paragraph + link).

- [ ] **Step 1:** full local e2e: backend `make serve` with real-ish scratch ledger + exported runs-summary; login via password user; verify every page in BOTH themes; viewer account sees locks; admin sync-now runs against scratch (use `--ledger-root` env to avoid touching prod Drive — set `STS_LEDGER_ROOT` respected by serve script).
- [ ] **Step 2:** `pytest` + `npm test` + `npm run build` all green.
- [ ] **Step 3:** commit docs `docs: dashboard operations guide`. Deploy to VM is a separate user-approved step (deploy.sh), not part of this plan's automation.

---

## Self-review notes

- Spec coverage: architecture (T1,13), auth/roles (T3,4), API (T5–8), exporter (T8), UX pages + Aurora (T9–12), testing (every task), docs (T14). Cloudflare Tunnel explicitly out of scope per spec.
- Deferred per spec: Playwright smoke marked optional — dropped (YAGNI); manual e2e in T14 covers it.
- Type consistency: `create_app(ledger_root, repo_root)` used by all test fixtures; `api()` / `useMe()` / `EquityChart` / `LedgerTable` reused across T10–12.
