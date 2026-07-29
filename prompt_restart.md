Resume `swing-ranking-v1`. Read the user-owned `docs/VISION.md`, then
`docs/PLAN.md` and `decisions.md`.

Do not preselect strategy families, behaviors, indicators, targets, models,
parameter ranges, folds, or composite weights. Use zero assumed trading costs.
Rank the top five independently by gross profit, maximum drawdown, and
profit/drawdown. Diagnostics never exclude a strategy. The user alone chooses
the forward mix.

Discovery implementation is isolated under `sts.swing_ranking`. Protocol,
identity, strategy-revision, candidate, and entry-geometry contracts are
complete. Continue with causal multi-timeframe candidate generation. Do not
create a dashboard, alerts, deployment, forward writer, or live-money path
unless the user explicitly asks.
