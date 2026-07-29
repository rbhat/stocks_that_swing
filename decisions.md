# Decisions

## 2026-07-29 — Open swing discovery and user-selected forward mix

`swing-ranking-v1` discovers readable multi-timeframe swing strategies without
preselecting strategy families, behaviors, indicators, targets, models,
parameter ranges, folds, or a composite metric.

Historical screening uses the accepted current-roster cache and is reported
with its limitations. Trading costs are zero. Results are ranked independently
by gross profit, maximum drawdown, and profit/drawdown. The top five for each
metric are presented with raw values and diagnostics.

There is no performance kill, qualification gate, automatic promotion, or
automatic winner. The user chooses the strategies and mix for forward paper
testing.

`docs/PLAN.md` is the sole active plan. Discovery implementation is complete;
no real-cache preflight or screening run has started.
