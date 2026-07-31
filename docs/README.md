# Swing strategy discovery index

## Read order

1. `VISION.md` — user-owned swing-trading scope and charter.
2. `PLAN.md` — sole active discovery and ranking plan.
3. `../decisions.md` — active decision record.
4. `RUN_REFERENCE.md` — guarded implementation boundary and required inputs.
5. `DEVELOPMENT_RESULTS.md` — first frozen development run.
6. `VALIDATION_RESULTS.md` — frozen validation run.
7. `OOS_RESULTS.md` — sealed one-time OOS result and cohort comparison.
8. `DEPLOYMENT.md` — GCP/local deployment and forward ledger operations.

## Current authority

Planning is active for open discovery within the Vision's explicit charter.
The plan did not preselect a strategy family, behavior, indicator, target
method, model, parameter range, or composite weighting. The first
performance-blind candidate grammar and chronological 60/20/20
development/validation/OOS split are now frozen in the checked bundle.

The isolated `sts.swing_ranking` implementation includes strict configuration,
causal daily/weekly/monthly candidates, declared entry geometry, the
Decimal-only zero-cost event simulator, metrics, independent leaderboards,
fail-closed preflight, and atomic artifacts. See `RUN_REFERENCE.md`.

The guarded read-only real-cache preflight passes for the local source
inventory, permanent IDs, earnings inputs, split contract, and development
bundle. The development and validation runs and their artifact audits are
complete. The cross-window audit shows no shared top-five-union member, no
shared top-10 revision for any metric, and low negative rank persistence
across all 144 revisions. The approved VF9/MC5 cohort was evaluated in the
study's one-time OOS opening, sealed, and reported in `OOS_RESULTS.md`.
Forward paper is active without backfill from the 2026-08-03 signal session.
No live-money trading is authorized.
