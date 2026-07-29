# stocks_that_swing

Systematic 3–21-session swing-trading research and forward-paper engine.

## Current status

[`docs/PLAN.md`](docs/PLAN.md) is the sole governing plan.

The active `swing-ranking-v1` study will discover readable multi-timeframe
swing strategies without preselecting strategy families, behaviors,
indicators, targets, models, or parameter ranges. It will publish:

- gross profit with no assumed trading costs;
- maximum drawdown;
- profit/drawdown ratio; and
- the top five for each metric.

There is no composite weighting, performance kill criterion, or automatic
promotion. The user chooses the forward-test mix.

The practical Yahoo/current-roster cache is accepted with explicit
survivorship and adjusted-history limitations. Discovery implementation is in
progress under `sts.swing_ranking`; immutable contracts and causal
multi-timeframe candidate generation plus the zero-cost event-sourced
portfolio simulator are complete.

Start the next session with [`prompt_restart.md`](prompt_restart.md).
