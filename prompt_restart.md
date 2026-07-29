Resume `swing-ranking-v1`. Read the user-owned `docs/VISION.md`, then
`docs/PLAN.md` and `decisions.md`.

Do not preselect strategy families, behaviors, indicators, targets, models,
parameter ranges, folds, or composite weights. Use zero assumed trading costs.
Rank the top five independently by gross profit, maximum drawdown, and
profit/drawdown. Diagnostics never exclude a strategy. The user alone chooses
the forward mix.

Discovery implementation is isolated under `sts.swing_ranking` and includes
strict configuration, causal candidate generation, declared geometry, the
zero-cost event simulator, metrics, independent rankings, fail-closed
preflight, and atomic artifacts. All synthetic and repository tests pass.

No real-cache preflight or screening run has started. Ask the user to approve
the candidate grammar/study bundle and resolve the documented cache blockers
before running the guarded preflight. Pause again before `--execute`. Do not
create a dashboard, alerts, deployment, forward writer, or live-money path
unless the user explicitly asks.
