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

No real-cache preflight or study run has started. Add the split contract,
derive the candidate grammar/study bundle, and resolve the documented cache
blockers before running the guarded preflight. Historical earnings come from
archived Investing.com custom-date calendar queries; upcoming schedules use
append-only daily snapshots. Pause again before `--execute`.
