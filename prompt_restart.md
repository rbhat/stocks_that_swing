Resume `swing-ranking-v1`. Read the user-owned `docs/VISION.md`, then
`docs/PLAN.md`, `decisions.md`, `coding_rules.md`, `docs/RUN_REFERENCE.md`,
`docs/DEVELOPMENT_RESULTS.md`, and `docs/VALIDATION_RESULTS.md`.

Do not preselect strategy families, behaviors, indicators, targets, models,
parameter ranges, or composite weights. Use the frozen chronological 60/20/20
development/validation/OOS split with a 21-session purge. Use zero assumed trading costs.
Rank the top five independently by gross profit, maximum drawdown, and
profit/drawdown. Diagnostics never exclude a strategy. The user alone chooses
the forward mix.

The sole research implementation is `sts.swing_ranking` and includes
strict configuration, causal candidate generation, declared geometry, the
zero-cost event simulator, metrics, independent rankings, fail-closed
preflight, and atomic artifacts. All synthetic and repository tests pass.

The split, permanent IDs, earnings inputs, source facts, and 144-member
development bundle are frozen under `configs/swing_ranking_v1/`. Historical
earnings come from archived Investing.com custom-date calendar queries;
upcoming schedules use append-only daily snapshots. The guarded real-cache
dry-run preflight passes for all 250 securities. The development and
validation runs are complete and recorded in `docs/DEVELOPMENT_RESULTS.md`
and `docs/VALIDATION_RESULTS.md`; their immutable local artifacts are under
`runs/swing-ranking-v1/`. Their artifact audits and both authorized real-cache
dry runs pass. The cross-window comparison covers all 144 revisions: the
top-five unions do not overlap, no metric has a shared top-10 revision, and
all three rank correlations are low and negative.

The user approved the exact VF9/MC5/FO4 selection on 2026-07-31. The one-time
study OOS opening, cohort analysis, and cross-artifact seal are complete and
recorded in `docs/OOS_RESULTS.md`. Forward run
`runs/swing-ranking-v1-forward-01` is active without backfill and first admits
signals on 2026-08-03.

## 2026-07-31 cohort proposal handoff

The user and agent developed a proposed two-cohort OOS-then-forward design.
Read
`reports/revision_selection_options/OOS_FORWARD_COHORT_PROPOSAL.md` before
continuing. It records the proposed VF9, MC5, and FO4 names, the exact nine
revision identities, the single-opening OOS sequence, unchanged forward
replication, raw and normalized measurement model, concentration diagnostics,
and the clean chart-led dashboard drilldown.

The proposal was approved exactly as written. Preserve its nine identities,
VF9/MC5/FO4 memberships, aggregation, charter, metrics, and no-backfill rule.
Do not alter cohorts or join OOS and forward equity. Ten- and twenty-trade
forward views are descriptive; decision-ready evidence requires at least 30
closed trades per revision.

The forward daily operator is implemented in
`scripts/fetch_swing_forward_prices.py` and
`scripts/advance_swing_forward.py`; its guarded command sequence is in
`docs/RUN_REFERENCE.md`. It creates immutable per-session input and execution
artifacts, carries open positions through the sole event simulator, and fails
closed on skipped sessions or backfill. At 2026-07-31 07:26 PDT, 2026-07-30
was the latest completed XNYS session, so the active book remains a verified
no-op awaiting its first eligible 2026-08-03 signal close.

## 2026-07-31 deployment and dashboard handoff

The forward deployment is live on GCP VM `sts-forward`
(`stocks-that-move` / `us-west1-b`), isolated from the legacy `~/sts` app.
`deploy/` holds `deploy.sh`, `deploy_local.sh`, `docker-compose.yml`, and
`open_remote.sh`; `docs/DEPLOYMENT.md` is the runbook. The remote root
`~/sts-swing-ranking-v1` is staged with the image, configs, credentials, and
the seeded empty forward run. **The `viewer` service is running on
`127.0.0.1:8010`; the `scheduler` — the single writer — is deliberately NOT
started and awaits the user's go-ahead.**

## 2026-07-31 dashboard handoff

The v1 dashboard is built and deployed. Read `docs/DASHBOARD_PLAN.md` (its
open questions are now a resolved-questions section) and `docs/DEPLOYMENT.md`.

The legacy dashboard was recovered from the running VM container into
`legacy/dashboard/`; it had never been committed anywhere, so that container
was its only copy, and its `dist/` was still untracked because `.gitignore`
matched `dist/`. That is fixed by a negation, so the only surviving legacy
bundle is now in git. Its SPA source remains unrecoverable.

All three open decisions were answered "retain what was in legacy": login is
required (`auth.py` and `audit.py` ported nearly as-is), the frontend is Vite +
React + TypeScript reusing the legacy design tokens and Geist fonts recovered
from that bundle, and the default axis is cohort-level (VF9/MC5/FO4), the
analogue of legacy's `h1`/`h2` family split.

`src/sts/swing_ranking/dashboard/` is read-only, tolerant of missing and
corrupt files, verifies manifest content hashes into a banner rather than an
exception, and never imports the writing engine — asserted on the import graph
in `tests/test_swing_ranking_dashboard.py`. The SPA lives in `frontend/` and is
built by a node stage in the `Dockerfile`, not committed.

The `viewer` compose service is replaced by `dashboard` on the same
`127.0.0.1:8010` loopback bind. `deploy/open_remote.sh` now carries two `-L`
forwards in one ssh invocation — 8010 required, 8000 best-effort — so one
command opens both dashboards and `--stop` reaps both. The legacy dashboard is
linked, never reverse-proxied: it sets cookies at `/` and owns its OAuth
redirect URI.

The curated 54 MB backtest subset is pushed by `deploy/push_backtests.sh`
(rsync; it installs rsync on the VM if absent) into
`~/sts-swing-ranking-v1/runs/swing-ranking-v1/`, mounted read-only. The 992 MB
of raw per-revision detail stays local. Because `strategies/` is not shipped,
`scripts/export_strategy_names.py` writes a compact `strategy_names.json`
beside each window so identities still resolve to names.

`configs/dashboard_users.yaml` is uncommitted (password hashes);
`configs/dashboard_users.example.yaml` is the template. `DASHBOARD_SECRET`
lives only on the VM and `deploy.sh` preserves it across deploys.

**The `scheduler` — the single writer — was started on the user's go-ahead.**
