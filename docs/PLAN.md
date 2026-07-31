# Swing Strategy Discovery and Ranking Plan

- **Study:** `swing-ranking-v1`
- **Status:** development, validation, approved VF9/MC5 one-time OOS, sealing,
  and unchanged no-backfill forward initialization complete; forward paper is
  active from the 2026-08-03 signal session
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
- optimization method; or
- a preferred balance among profit, drawdown, and profit/drawdown.

Signals and execution rules must remain human-readable. ML may rank a
candidate pool but cannot invent signals, change geometry, size positions, or
override risk.

Exploration may iterate. Each tested strategy version is retained with its
exact rules, parameters, data range, inputs, and results. Every revision gets
its own immutable result identity.

Before performance is read, each study run records its research protocol,
candidate grammar, data cutoff, and split dates.

## Evaluation split

Sort the frozen evaluation range by XNYS session and divide it
chronologically:

- oldest 60%: development;
- next 20%: validation;
- newest 20%: unseen study OOS.

Purge 21 entry sessions between windows so no trade outcome crosses a
boundary. Explore revisions on development, choose frozen revisions using
validation, and open OOS once for the final independent rankings.

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
basis consistently and exclude incomplete bars. Historical earnings report
sessions/results come from archived, hashed Investing.com custom-date calendar
queries; upcoming schedules use append-only daily snapshots. Every artifact
states the current-roster survivorship, symbol-history, delisting,
adjustment-vintage, and historical schedule-knowledge limitations.

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

1. Freeze source identities and chronological split dates.
2. Define the candidate grammar without reading performance.
3. Explore strategy versions on development.
4. Freeze revisions using validation.
5. Open OOS once and produce the three rankings and top-five comparison.
6. Ask the user to select the forward-paper mix.
7. Compare forward gross return with OOS after at least 30 closed trades per
   selected strategy.

The sequence is not a set of performance gates. The user may change direction
or request additional work at any point. Dashboard, alerts, deployment, and
live money are outside scope unless the user explicitly asks.

## Current evidence state

The development and validation artifacts reconcile to their manifests and
contain the same 144 immutable strategy revisions. The cross-window comparison
in `VALIDATION_RESULTS.md` recomputes all three rankings from the metric
records. The top-five unions do not overlap, no metric has a common top-10
revision, and the three full-field rank correlations are low and negative.
Validation contains 39 entry sessions versus 159 in development, so sample and
window sensitivity remain material. The user subsequently selected the exact
nine-revision VF9 frontier, its five-member MC5 subset, and diagnostic FO4
complement. The study's one-time OOS opening is complete and sealed. VF9
returned -0.9379%, MC5 returned -1.4682%, and FO4 returned -0.2750%; these
results do not change the pre-OOS selection or forward eligibility. See
`OOS_RESULTS.md`.

## Next step

Process forward data from the 2026-08-03 signal session onward without
backfill. Keep VF9, MC5, FO4, all nine revision identities, member weights,
parameters, execution rules, aggregation, and metrics unchanged. Report 10-
and 20-closed-trade checkpoints per revision as descriptive only. Treat
forward evidence as decision-ready only after every revision has at least 30
closed trades.
