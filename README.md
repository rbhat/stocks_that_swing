# stocks_that_swing

Systematic 3–21-session swing-trading research and forward-paper engine.

## Current status

[`docs/PLAN.md`](docs/PLAN.md) is the sole governing plan.

The active `swing-ranking-v1` study discovers readable multi-timeframe swing
strategies from a performance-blind, frozen grammar. It will publish:

- gross profit with no assumed trading costs;
- maximum drawdown;
- profit/drawdown ratio; and
- the top five for each metric.

There is no composite weighting, performance kill criterion, or automatic
promotion. The user chooses the forward-test mix.

The current-roster cache is accepted with explicit survivorship and
adjusted-history limitations. `sts.swing_ranking` is the sole research path.
It contains immutable configuration, causal candidate generation, geometry,
the zero-cost event simulator, metrics, independent rankings, fail-closed
preflight, and atomic artifacts.

The chronological development/validation/OOS split, 250 permanent security
IDs, historical and upcoming earnings inputs, and the first 144-member
development bundle are frozen under `configs/swing_ranking_v1/`. The guarded
read-only real-cache preflight passes. The first development run is complete;
see [`docs/DEVELOPMENT_RESULTS.md`](docs/DEVELOPMENT_RESULTS.md). The
validation run is also complete; see
[`docs/VALIDATION_RESULTS.md`](docs/VALIDATION_RESULTS.md). Revision selection
is pending. The cross-window audit found no overlap between the two
nine-strategy top-five unions and low negative rank persistence across all 144
revisions; see the validation results for the decision-support detail. Study
OOS remains closed and forward-paper work has not started.

Start the next session with [`prompt_restart.md`](prompt_restart.md).
