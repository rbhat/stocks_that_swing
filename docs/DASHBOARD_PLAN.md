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

## Open questions

- **Auth on the new dashboard?** The legacy one required login. The current
  8010 viewer has none, relying on the loopback bind plus IAP. Reusing
  `legacy/dashboard/py/auth.py` is cheap if login is wanted; skipping it is
  defensible while access is IAP-only.
- **Frontend stack** — server-rendered v1 versus Vite + React (task 4).
- **Cohort-level or revision-level default view?** The charter keeps nine
  revisions and three cohorts distinct; the landing page has to pick one as its
  primary axis.
