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
- The project report reads the pushed OOS backtest artifacts and the validated
  parquet cache read-only. The dashboard container must be able to see
  `/app/cache/study_frames` so trade charts can draw actual OHLCV candles.
- Missing or corrupt files render empty/degraded states instead of failing a
  page.
- OOS and forward equity are never joined.
- Retired study results never enter the active top five unless evaluated under
  `docs/PLAN.md`.

## Routes

V1 routes remain `/`, `/forward`, `/forward/:cohort`, `/backtests`,
`/backtests/:window`, and `/project-report`. The same report is also served as
standalone HTML at `/project-report.html`.

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

## Report Requirements

The project report is an easy-to-read, collapsible explanation of the active
study. It starts with the project goal, then a short 3-4 line conclusion, then
the supporting sections.

- Provide page-level icon buttons to expand all and collapse all sections.
- Use the same disclosure icon pattern on every collapsible cohort and strategy
  section.
- Include coherent sections for overall OOS evidence, each cohort, each member
  strategy, limitations, and source/integrity context.
- For every cohort, state what the cohort is and show profit/loss, return,
  drawdown, trade count, member count, and positive/negative/flat member
  breadth.
- For every strategy, state what it is, show profit/loss, return, drawdown,
  number of trades, wins/losses/flats, turnover, exposure, and the readable
  rules.
- For every strategy, show two actual OOS backtest trade charts: a winning
  trade if available and a losing trade. If one side does not exist, label the
  fallback clearly.
- Trade charts must be candlestick charts from the actual backtest trade
  symbol/session window, not synthetic examples. Draw entry, exit, target,
  stop, volume, and every plotted price-scale indicator used by that strategy
  when available from the trade inputs.
- Use the dashboard favicon on the standalone report page.

## Rollback

The retained `sts-dashboard-1` image and `~/sts` data are the rollback target.
Restart that container and temporarily restore an `8000` tunnel if rollback is
required. The unified reader never converts or rewrites the legacy ledger.
