# Swing strategy discovery index

## Read order

1. `VISION.md` — user-owned swing-trading scope and charter.
2. `PLAN.md` — sole active discovery and ranking plan.
3. `../decisions.md` — active decision record.
4. `RUN_REFERENCE.md` — guarded implementation boundary and required inputs.
5. `DEVELOPMENT_RESULTS.md` — first frozen development run.

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
bundle. The first development run is complete. Validation and study OOS remain
closed; final rankings, user selection, and forward paper testing remain
incomplete. No live-money trading is authorized.
