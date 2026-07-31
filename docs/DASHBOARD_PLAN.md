# Swing ranking dashboard plan

## Goal

Replace the placeholder viewer with a real dashboard for `swing-ranking-v1`.
Today the `viewer` compose service is `python -m http.server --directory
/app/runs`, which serves a bare Apache-style directory listing of the forward
run. There is no dashboard.

By default the dashboard shows the new forward ledger and the backtest
evidence. It also carries a link that loads the previous (legacy) dashboard.
This is a v1; it is expected to be improved afterwards.

## Prior art

The legacy `stocks-that-move` dashboard was recovered on 2026-07-31 from the
running VM container into `legacy/dashboard/` — it had never been committed to
any repository, so the container was the only copy. Read
`legacy/dashboard/README.md` first: it records what carries forward
(`auth.py` nearly unchanged, the middleware ordering constraint, and `data.py`'s
read-only/tolerant discipline) and what does not (every schema-bound reader and
route). Its SPA source is unrecoverable; only the minified bundle survives, so
the frontend is a rewrite.

## What the dashboard reads

Forward ledger, `runs/swing-ranking-v1-forward-01/` — already on the VM and
mounted into the container:

- `charter.json`, `state.json`, `manifest.json`;
- `candidates|orders|trades|equity|events.jsonl` (append-only projections);
- `sessions/YYYY-MM-DD/{source,next_state,manifest}.json` + `records/*.jsonl`.

Backtest evidence, `runs/swing-ranking-v1/` — `development-v1`,
`validation-v1`, `oos-v1`, `oos-cohort-comparison-v1`, `oos-seal-v1`.

Charter rules the dashboard must not violate: never join OOS and forward
equity; preserve the nine revision identities and the VF9/MC5/FO4 cohort
memberships; ten- and twenty-trade forward views are descriptive only, and
decision-ready evidence requires at least 30 closed trades per revision.

### Blocker: backtests are not on the VM

`runs/swing-ranking-v1/` is 992 MB and exists **only on the local machine**.
`deploy.sh` excludes `runs/` from the build context and seeds just the empty
forward run, so the VM has no backtest artifacts at all. "Backtests show up by
default" cannot work until they are shipped.

The bulk is per-revision raw detail — `candidates.jsonl` alone is 381 MB, plus
`events.jsonl` 205 MB and `orders.jsonl` 97 MB — none of which a dashboard
needs. A curated subset (`manifest`, `protocol`, `ranking`, `metrics`, `equity`,
`trades`, `report.md`, and all of `oos-cohort-comparison-v1` / `oos-seal-v1`)
is **54.3 MB across 32 files**, which ships comfortably.

Legacy solved exactly this problem with `export_runs_summary.py` writing
compact `runs-summary/*.json` that the dashboard read instead of raw runs. For
v1, prefer the simpler version of that idea: an `rsync` of the curated subset
(rsync is available in WSL), driven by a new `deploy/push_backtests.sh`, into
`~/sts-swing-ranking-v1/runs/swing-ranking-v1/` mounted read-only. Add a real
summary exporter later only if 54 MB becomes awkward.

## Architecture

- FastAPI + uvicorn inside the existing `sts-swing-ranking-v1` image. Add
  `fastapi` and `uvicorn` to `pyproject.toml`; add `authlib`, `bcrypt`,
  `itsdangerous`, `pyyaml` only if auth is wanted (see open questions).
- New read layer `src/sts/swing_ranking/dashboard/`. It is read-only and
  tolerant of missing/corrupt files, and it must never import `forward.py` or
  otherwise touch the writing engine — the same firewall `legacy/dashboard/py/
  data.py` maintained against the writing ledger.
- Verify manifest content hashes on read. A mismatch surfaces as a visible
  banner, not an exception — the dashboard must still render a degraded run.
- Replace the `viewer` service in `deploy/docker-compose.yml` with a
  `dashboard` service on the same `127.0.0.1:8010` binding, mounting `runs/`
  and `configs/` read-only. Keep the loopback bind: no public ingress, IAP
  tunnel only.
- The `scheduler` remains the single writer. The dashboard never writes to the
  run directory.

## Legacy link: two tunnels, not a reverse proxy

I initially suggested reverse-proxying `/legacy` → `127.0.0.1:8000` from the
new app. On inspecting the recovered code, don't: the legacy app does Google
OAuth through authlib, sets signed cookies at `/`, and 303-redirects
unauthenticated requests. Hosting that under a subpath breaks cookie paths and
OAuth redirect URIs, which is a lot of fragility for a link.

Container-to-container proxying is technically available — `dashboard_serve.py`
binds `0.0.0.0:8000` inside the container, so joining the legacy compose
network and addressing `sts-dashboard-1:8000` would reach it — but it does not
avoid the OAuth-under-subpath problem.

Instead, forward both ports in one ssh invocation. `open_remote.sh` already
runs the tunnel in its own process group; extend its single `gcloud compute
ssh` call with a second `-L`:

```
-L 8010:127.0.0.1:8010 -L 8000:127.0.0.1:8000
```

One command opens both, `--stop` still reaps both, and the new dashboard links
to `http://127.0.0.1:8000` as plain markup that just works. Readiness polling
should treat 8010 as required and 8000 as best-effort, so a stopped legacy
dashboard does not fail the new one.

## Tasks

1. Dependencies: `fastapi`, `uvicorn` in `pyproject.toml`; rebuild the image.
2. `src/sts/swing_ranking/dashboard/data.py` — forward-ledger and backtest
   readers, with tests covering missing, empty, and hash-mismatched runs.
3. API routes: `/api/overview`, `/api/forward`, `/api/forward/{cohort}`,
   `/api/backtests`, `/api/backtests/{window}`, `/healthz`.
4. Frontend rewrite. Given "improve later", server-rendered HTML with a small
   chart layer is a legitimate v1 and avoids standing up a Node toolchain; a
   Vite + React SPA is the closer match to what was there.
5. `deploy/push_backtests.sh` — rsync the curated 54 MB subset to the VM.
6. Compose: swap `viewer` for `dashboard`; Dockerfile copies any built assets.
7. `open_remote.sh` — second `-L`, best-effort readiness on 8000.
8. Update `docs/DEPLOYMENT.md`: the 8010 service is a dashboard, not a file
   listing, and record the backtest push step.

## Resolved questions

All three were settled the same way on 2026-07-31: **retain what was in
legacy.**

- **Auth.** Login is required. `auth.py` and `audit.py` are ported nearly
  as-is into `src/sts/swing_ranking/dashboard/`: signed httponly session
  cookies, Google OAuth via authlib, bcrypt password users that are always
  `viewer`, and `SessionMiddleware` added last so it wraps outermost. Two
  deliberate changes: the users file moved to `configs/dashboard_users.yaml`
  (uncommitted, with a committed `.example.yaml`), and the OAuth redirect URI
  is overridable through `DASHBOARD_OAUTH_REDIRECT_URI` because the new
  dashboard answers on 8010 while the legacy one still owns 8000.
- **Frontend stack.** Vite + React + TypeScript, as before. The legacy design
  tokens were recovered from the surviving `dist/assets/index-DXkp7QVQ.css` —
  both palettes, the type scale, the `0.625rem` radius — and the Geist woff2
  files were copied out of that bundle, so the rewrite matches the original
  look without a CDN. The one departure: legacy applied those tokens through a
  Tailwind v4 utility layer whose source is unrecoverable, so this uses the
  same token values in hand-written CSS rather than reconstructing a utility
  layer against a design nobody can see.
- **Default view axis.** Cohort-level. Legacy's primary axis was its `h1`/`h2`
  family split, and VF9/MC5/FO4 is its analogue. The landing page leads with
  three cohort cards; the nine revision identities stay one click away under
  each cohort and in the forward book table, so neither level is lost.

## What shipped

- `src/sts/swing_ranking/dashboard/{data,api,app,auth,audit}.py`, plus
  `scripts/run_swing_dashboard.py`, `scripts/dashboard_user.py`, and
  `scripts/export_strategy_names.py`.
- `frontend/` — the SPA, built by a node stage in the Dockerfile rather than
  committed.
- `tests/test_swing_ranking_dashboard.py` — missing, empty, corrupt, and
  hash-mismatched runs; charter order, eligibility and evidence tiers; route
  shapes and auth gating; and an import-graph assertion that the read layer
  cannot reach the writing engine.
- `deploy/push_backtests.sh`, the `dashboard` compose service, the second `-L`
  in `open_remote.sh`, and the node build stage in the `Dockerfile`.

Charts are hand-rolled SVG — a multi-series line and a signed-profit bar — so
there is no charting dependency. Cohort series colours are a fixed,
never-cycled categorical set validated for colourblind separation and contrast
against both the light and dark surfaces, with a legend and end-of-line direct
labels so identity never rests on colour alone.

### Still open for v2

- `metrics.jsonl` is pushed (20 MB of the 54) but nothing reads it yet; the
  obvious next view is the all-144 per-revision metrics table.
- No view of the per-session immutable packages beyond a count; `/api/forward/sessions`
  already returns them.
- The forward ledger had processed zero sessions when this was built, so every
  forward view was exercised against its empty state and against synthetic
  fixtures, not against real filled trades.
