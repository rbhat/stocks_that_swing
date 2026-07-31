# Recovered legacy dashboard (reference only)

This is the `stocks-that-move` admin dashboard, recovered on 2026-07-31 from the
running `sts-dashboard-1` container on the `sts-forward` VM. It was **never
committed** to this repository — commit `07644f1` ("reset repository to swing
ranking", 215 files / 175,757 lines deleted) did not remove it, because it was
never here. The container was the only copy.

Nothing here is imported or executed by `sts.swing_ranking`. It exists so the
new dashboard can be rebuilt without re-deriving the old design.

## Contents

| Path | State |
|---|---|
| `py/` | Full backend, 861 lines, recovered intact |
| `dashboard_serve.py` | uvicorn entry point (`0.0.0.0:8000` inside the container) |
| `dashboard_user.py` | bcrypt user management CLI |
| `dist/` | The **only** surviving build of the SPA |

The React/TypeScript source is unrecoverable. It was never committed and the
image contains only the built bundle, so `dist/assets/index-CONMRDY2.js` is
minified with no sourcemap. The frontend was rewritten from scratch in
`frontend/`.

`dist/` was itself still untracked after recovery, because `.gitignore`
matched `dist/` — the only surviving copy was sitting in the working tree.
`.gitignore` now carries a negation for this path, so it is in git.

What the rewrite took from the bundle: the design tokens in
`dist/assets/index-DXkp7QVQ.css` — both light and dark palettes, the type
scale, the `0.625rem` radius — and the Geist woff2 files, which are copied
into `frontend/src/fonts/`. What it could not take: the Tailwind v4 utility
layer those tokens were applied through, so the rewrite uses the same values
in hand-written CSS.

The backend is additionally preserved in Artifact Registry as
`us-central1-docker.pkg.dev/stocks-that-move/sts/sts:latest` (2026-07-17).

## What carried forward

Ported nearly as-is into `src/sts/swing_ranking/dashboard/`:

- `auth.py` — signed session cookies, Google OAuth via authlib, bcrypt
  `password_users` from `users.yaml`, auth middleware.
- `audit.py`, `safe_config.py` — audit trail and the allowlisted-write pattern.
- `app.py` — middleware ordering matters: `SessionMiddleware` must be added
  last so it wraps outermost, because authlib stores OAuth state in
  `request.session`.
- `data.py`'s *discipline*, not its schema: every reader is read-only and
  tolerant, missing or corrupt files yield empty results rather than raising,
  and it deliberately never instantiates the writing ledger.

Two deliberate changes on the way over: the users file moved to
`configs/dashboard_users.yaml`, and the OAuth redirect URI became overridable
through `DASHBOARD_OAUTH_REDIRECT_URI`, because the new dashboard answers on
8010 while this one still owns 8000.

Not reusable — schema-bound to the legacy model:

- `data.py` reads `h1.jsonl`/`h2.jsonl` with `entry_id`/`seq`/`status`/
  `pnl_usd` and replays latest-row-per-`entry_id`. The swing ranking forward
  ledger shares none of this.
- `api.py`'s `/api/forward/{family}` family split (`h1`, `h2`) does not map to
  cohorts VF9/MC5/FO4 over nine revision identities.
- `jobs.py` hardcodes the legacy cron spec (eod 17:30, fill 06:31, monitor
  hourly :35 PT) and infers status from log-tail string markers.

## Running it

It is still live on the VM, reached through an IAP tunnel to
`127.0.0.1:8000`. `/healthz` returns `{"ok": true}`; `/` 303-redirects to
login and `/api/*` returns 401 unauthenticated.
