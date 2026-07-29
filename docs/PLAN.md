# Swing Strategy Discovery and Ranking Plan

- **Study:** `swing-ranking-v1`
- **Status:** ready for implementation
- **Authority:** `docs/VISION.md` defines the scope; this is the sole active
  execution plan

## Objective

Discover daily-data, long-only swing strategies for liquid US stocks and rank
the results by:

1. gross profit;
2. maximum drawdown; and
3. profit/drawdown ratio.

Publish the top five for each ranking with one comparison table containing all
three raw metrics and ranks. Do not combine the metrics with an assumed
weighting. The user decides which strategies and mix, if any, proceed to
forward paper testing.

There is no performance kill criterion, qualification gate, or automatic
promotion.

## Discovery scope

Explore multi-timeframe technical strategies that use higher-timeframe trend
or levels to define where to look and daily triggers to define when to act.

The plan does not preselect:

- strategy families or market behaviors;
- indicators, lookbacks, thresholds, or features;
- entry or exit patterns;
- stop or target formulas;
- ranking models;
- parameter ranges;
- the number of candidates;
- data folds or optimization method; or
- a preferred balance among profit, drawdown, and profit/drawdown.

Signals and execution rules must remain human-readable. ML may rank a
candidate pool but cannot invent signals, change geometry, size positions, or
override risk.

Exploration may iterate. Each tested strategy version must be retained with
its exact rules, parameters, data range, inputs, and results. A strategy may
change during discovery; an old result may not be attributed to a revised
strategy.

Before performance is read, each study run records its research protocol,
candidate grammar, data cutoff, and prospective wall. The historical screen
may use all available backtest data and is labeled screening, never untouched
out-of-sample evidence.

## Charter constraints

Every candidate must follow `docs/VISION.md`:

- daily data and 3–21-session swing trades;
- liquid US common stocks/ETFs from the accepted current-roster cache;
- price at least `$5` and average dollar volume at least `$20M`;
- long only and paper only;
- `$100,000` starting capital;
- 0.75% of equity risked per trade;
- 15% maximum position notional;
- eight concurrent positions and 80% maximum deployment;
- a study-determined hard stop present at entry and no more than 12% below
  entry;
- planned reward/risk greater than 1.5;
- a study-determined target present at entry;
- a hard time stop no later than 21 sessions;
- no stop widening or averaging down; and
- no new entry within two sessions before scheduled earnings.

The plan adds no other strategy, target, or portfolio constraint.

## Data and evidence

The local validated parquet cache is the source of truth. Use one adjustment
basis consistently and exclude incomplete bars. Every artifact states the
current-roster survivorship, symbol-history, delisting, adjustment-vintage,
and historical earnings-calendar limitations.

All features, signals, and decisions must use information available at the
decision time. Data quality, causal ordering, accounting, and reproducibility
are validity requirements, not performance gates.

Each evaluated strategy must produce:

- its complete readable specification;
- its data identity and evaluation range;
- candidate, order, trade, and daily-equity records;
- entry trigger, fill, stop, target, time stop, and exit reason for every
  trade;
- yearly and full-period results;
- trade count, hold-time distribution, exposure, turnover, and order count;
- winner and loser distributions;
- profit per dollar turned over and break-even proportional cost;
- concentration by time and symbol; and
- limitations and reproducibility identity.

## Trading costs

Assume no commission, fee, spread, or slippage. Do not deduct any trading cost
from profit or equity.

Turnover, order count, profit per dollar turned over, and break-even
proportional cost are diagnostics only. They do not affect rankings.

## Ranking definitions

### Profit

`profit = ending_equity - starting_equity`

Use gross realized portfolio P&L with no assumed trading costs. Higher is
better.

### Drawdown

`drawdown = max(1 - equity / running_peak_equity)`

Use maximum peak-to-trough drawdown on the strategy's portfolio equity. Lower
is better.

### Profit/drawdown

`profit_drawdown = gross_portfolio_return / maximum_drawdown`

Higher is better. A positive return with zero drawdown is reported as
`positive_return_no_drawdown` and ranks first. Zero return with zero drawdown
is `undefined` and ranks last.

### Output

Produce three independent leaderboards:

- top five by profit;
- top five by lowest drawdown; and
- top five by profit/drawdown.

Also produce one cross-metric table for every strategy appearing in any top
five. Do not create a composite score or select a single winner. Include
strategy similarity and overlapping trades so the user can judge a useful
forward mix.

No strategy is removed because of profitability, drawdown, sample size,
uncertainty, exposure, stability, controls, or model type. Report those facts
where available and leave the decision to the user.

## Work sequence

1. Define and record the discovery protocol and candidate grammar without
   reading performance.
2. Implement the exploration, portfolio simulation, artifacts, and tests.
3. Explore strategy versions and retain every evaluated specification.
4. Produce the three rankings and top-five comparison.
5. Ask the user to select the forward-paper mix.
6. Version the selected strategies and start a prospective wall only after
   that selection.
7. Compare forward gross return with retrospective screening after at least
   30 closed trades per selected strategy.

The sequence is not a set of performance gates. The user may change direction
or request additional work at any point. Dashboard, alerts, deployment, and
live money are outside scope unless the user explicitly asks.

## Next step

Implement the discovery protocol, candidate grammar, evaluator, and ranking
artifacts described here. Do not preselect strategies or targets while doing
so.
