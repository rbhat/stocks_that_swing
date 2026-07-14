# STS Admin Dashboard — Design Spec

Date: 2026-07-13. Status: approved direction (SPA, Aurora theme), pending user spec review.

## Goal

A full web dashboard for the stocks_that_swing forward-paper pipeline:
admin operations (sync on demand, job status, safe config edits) and
read-only visibility (config, backtest summaries, forward ledgers) for
whitelisted viewers. Modern, lively UX with first-class dark mode — an
explicit step up from the stm server-rendered dashboard.

## Decisions (user-confirmed)

- Runs on the `sts-forward` GCP VM (the live ledger writer), reading its
  local `ledger/`, `configs/`, logs.
- Exposure: IAP SSH tunnel now (stm-style `open_remote.sh`); Cloudflare
  Tunnel + domain later. App is built public-ready from day one (real
  auth, TLS-aware cookies) so going public is config-only.
- Auth: Google OAuth — `rajeevmbhat@gmail.com` = admin; other whitelisted
  Google emails = viewer. Username/password whitelist = viewer only.
- Config: view everything (secrets redacted); admin edits a safe subset
  only (alert toggles, monitor thresholds) with validation + audit log.
  Prereg/strategy parameters are permanently read-only.
- Admin actions: Sync Now + job status dashboard. No manual eod/fill/
  monitor triggers, no log viewer (can add later).
- Backtests: summary cards per family with drill-down (trade lists,
  equity curves), fed by an exported compact summary, not the raw
  `runs/` tree.
- Frontend: full SPA (user explicitly rejected server-rendered pages and
  Streamlit).

## Architecture

```
dashboard/                     # Vite + React + TS SPA (new, repo root)
  src/{app,routes,components,lib,theme}/
src/sts/dashboard/             # FastAPI backend package
  app.py      # create_app(): /api/* + static SPA serving + SPA fallback
  auth.py     # sessions, Google OAuth, password logins, role middleware
  data.py     # defensive read layer: ledgers, configs, runs-summary, jobs
  audit.py    # append-only audit log for logins + mutations
scripts/export_runs_summary.py # laptop: runs/ -> runs-summary/*.json
configs/dashboard_users.yaml   # role map: google emails + bcrypt users
```

- **Frontend stack:** Vite, React 18+, TypeScript, Tailwind v4 (token-based
  theme), shadcn/ui (Radix primitives), TanStack Query (fetch/poll/cache),
  TanStack Table (ledger tables), ECharts (equity/drawdown charts),
  cmdk command palette (⌘K).
- **Backend:** FastAPI serves JSON under `/api/*` and the built SPA
  (`dashboard/dist/` copied into the image). Non-`/api` routes fall back
  to `index.html` (client routing). uvicorn via `make serve` and a
  `dashboard` service in `deploy/docker-compose.yml`, bound to
  `localhost:8000` on the VM.
- **Build:** multi-stage Dockerfile — node stage builds the SPA, python
  stage copies `dist/`. The e2-micro never runs Node.
- **Single-writer policy respected:** the dashboard only reads ledgers;
  its one mutation into pipeline state is triggering the existing
  merge-only `forward_sync` (same code path as cron step 6).

## Auth & roles

- Signed httponly session cookie; `Secure` flag driven by env
  (`DASHBOARD_TLS`), same pattern as stm.
- Login page offers Google OAuth (authlib) and username/password.
- `configs/dashboard_users.yaml`:
  ```yaml
  google:
    rajeevmbhat@gmail.com: admin
    friend@example.com: viewer
  password_users:
    guest: {hash: <bcrypt>, role: viewer}
  ```
  Unlisted Google users rejected. Password users are always viewer.
  `make dashboard-user` CLI creates/updates bcrypt entries.
- Middleware enforces: every route except `/login`, `/auth/*`,
  `/healthz` requires a session; any mutating method requires admin.
  Viewers see read-only lock states in the UI, but enforcement is
  server-side.
- Audit log `logs/dashboard-audit.log`: logins, failed logins, sync
  triggers, config edits (who/when/what).

## API surface (v1)

- `GET /api/me` — role, email, theme prefs.
- `GET /api/overview` — equity series, stat tiles, open positions,
  latest signals.
- `GET /api/forward/{family}` — positions, fills, signals, alerts
  (paged/filterable).
- `GET /api/backtests` / `GET /api/backtests/{family}` — summary cards;
  drill-down trades + equity curve from runs-summary.
- `GET /api/config` — universe, roster, redacted env, editable-subset
  values with schema.
- `PUT /api/config/safe` — admin-only, validated against an explicit
  allowlist schema; writes atomically; audit entry.
- `GET /api/jobs` — per job (eod/fill/monitor/sync): last run time,
  exit status (parsed from logs), next scheduled run (from cron spec).
- `POST /api/sync` — admin-only; runs forward_sync; returns run id;
  `GET /api/sync/{id}` polled by the UI. Concurrent sync requests are
  rejected while one is running (lockfile).

All reads defensive: missing/corrupt files → typed "unavailable" states,
never 500s.

## Data: backtest summaries

`scripts/export_runs_summary.py` (laptop) distills `runs/h*/` into
`runs-summary/{family}.json`: verdict, headline metrics, equity curve
points (downsampled), trade list. `deploy/deploy.sh` ships the directory
to the VM alongside configs. Resumable/irrelevant — it's a fast pure
transform; re-run any time.

## UX design

### App shell
Slim icon sidebar: Overview, Forward, Backtests, Config, Jobs. Top bar:
page title, sync-status pill (idle/running/failed), theme toggle, avatar
with role badge ("Admin" / "Read-only"). ⌘K command palette for
navigation and jump-to-ticker.

### Pages
- **Overview:** hero equity area chart (violet→teal gradient fill,
  crosshair tooltip), stat tiles with sparklines and count-up animation
  (total P&L, open exposure, win rate, per-family equity), open-positions
  strip, job-status cards (pulsing dot while running, red on failure),
  Sync Now button (admin).
- **Forward:** per-family tabs (h1, h2); tables for positions / fills /
  signals / alert journal — tabular numerals, right-aligned numbers,
  green/red P&L chips, expandable rows, column filters.
- **Backtests:** family summary cards (verdict badge, key metrics) →
  drill-down route with equity curve + trade table.
- **Config:** grouped read-only viewers (universe, roster, env-redacted)
  + "Operational settings" card with the editable safe subset; inline
  validation; save requires typed confirmation; viewers see lock icons.
- **Jobs:** schedule table + last-N run history per job.

### Design system — "Aurora" (dark-first)
Tokens as CSS custom properties consumed by Tailwind; `data-theme` on
`<html>`, persisted in localStorage, defaults to `prefers-color-scheme`.

- Dark: bg `#0B0E14`, surface `#131722`, raised `#1A2030`,
  border `#232B3D`, text `#E6EAF2` / muted `#8B94A8`.
- Light: bg `#FAFAFC`, surface `#FFFFFF`, text `#141824`.
- Primary electric violet `#7C6CFF`; accent aurora teal `#2DD4BF`;
  gain `#34D399`; loss `#FB7185`; warn `#FBBF24`.
- Charts: violet→teal gradient area fills, soft glow on hover/active.
- Type: Inter var (UI) + JetBrains Mono or Inter tabular-nums for
  figures. 4px spacing grid, rounded-xl cards, subtle borders over
  heavy shadows.
- Motion: 150–250ms ease-out; skeleton loaders; count-up on tiles;
  toast confirmations. Respect `prefers-reduced-motion`.
- Accessibility: WCAG AA contrast in both themes (validate token pairs),
  full keyboard nav (Radix), visible focus rings (violet), color never
  the sole P&L signal (± sign + chip shape).

## Testing

- Backend: pytest — data.py (missing/corrupt/partial files), auth role
  matrix (viewer POST → 403, unlisted Google email rejected, bcrypt
  login), config-edit allowlist (non-allowlisted key rejected), sync
  endpoint lock behavior (mocked runner).
- Frontend: Vitest + Testing Library for lib/logic and key components
  (role-gated buttons, table formatting); Playwright smoke (login →
  overview renders → viewer cannot see Sync Now) if cheap, else defer.
- Manual gate: `make serve` locally against a scratch ledger before VM
  deploy.

## Out of scope (explicit)

- Manual eod/fill/monitor triggers from the UI, log tailing.
- Editing prereg/strategy parameters.
- Cloudflare Tunnel setup (later phase; app is ready for it).
- Mobile-native apps (the SPA is responsive; that's it).
