# Unified dashboard

The maintained dashboard is served at `http://127.0.0.1:8010` through one IAP
tunnel. Swing Ranking v1 remains the landing page. Retired H1/H2 views live in
the same React shell under `/legacy` and use the same OAuth callback, signed
session cookie, roles, logout action, and audit log.

## Data boundaries

- V1 reads `~/sts-swing-ranking-v1/runs` and never imports the forward writer.
- Legacy reads `~/sts/{ledger,runs,runs-summary,logs,configs}` through explicit
  `/app/legacy/*` mounts. Ledger, run, summary, log, and config mounts are
  read-only in the dashboard container.
- Missing or corrupt files render empty/degraded states instead of failing a
  page.
- OOS and forward equity are never joined.
- Retired study results never enter the active top five unless evaluated under
  `docs/PLAN.md`.

## Routes

V1 routes remain `/`, `/forward`, `/forward/:cohort`, `/backtests`, and
`/backtests/:window`.

Legacy routes are `/legacy`, `/legacy/forward/:family`, `/legacy/backtests`,
`/legacy/backtests/:family`, `/legacy/config`, and `/legacy/jobs`. Their API is
namespaced under `/api/legacy`.

## Bounded administration

Viewer mutations are rejected by the shared auth middleware. Admin config and
sync requests are validated and audited by the unified app, then sent over the
private Compose network to `legacy-admin`. That sidecar:

- runs in the retained legacy image;
- exposes no host port;
- accepts a shared-token header;
- supports only allowlisted settings updates and the fixed
  `/app/scripts/forward_sync.py` command;
- has no Docker socket and cannot invoke the v1 scheduler.

Configuration writes use a lock, temporary file, fsync, atomic replace, and
directory fsync. Sync uses a stale-bounded exclusive lock and durable status
records. Both actions append target, before/after, actor, and `legacy` scope to
the unified audit log.

## Presentation

Legacy pages carry a visible `Legacy` marker and keep H1/H2 terminology. They
reuse the v1 typography, responsive shell, tables, tiles, chart conventions,
and loading/error states. The surviving legacy bundle remains reference-only;
it is neither imported nor served.

## Rollback

The retained `sts-dashboard-1` image and `~/sts` data are the rollback target.
Restart that container and temporarily restore an `8000` tunnel if rollback is
required. The unified reader never converts or rewrites the legacy ledger.
