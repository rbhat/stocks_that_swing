Resume `swing-ranking-v1`. Read the user-owned `docs/VISION.md`, then
`docs/PLAN.md` and `decisions.md`.

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
`runs/swing-ranking-v1/`. Revision selection is pending. Study OOS remains
closed and no forward-paper work has started. Review both results and pause
before any next run unless the user explicitly authorizes it.
