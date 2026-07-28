# Swing-v1 Retrospective Screening Preregistration

- **Status:** LOCKED; EXECUTION NOT AUTHORIZED
- **Setup roster:** `setup-contract.md`
- **Data contract:** `data-contract.md`
- **Prospective wall:** unset

## Question

Does either fixed deterministic setup produce a sufficiently active,
profitable, cash/slot-constrained swing portfolio after doubled friction to
justify testing exactly one unchanged setup in a genuinely prospective paper
book?

The screen may answer only `FORWARD_PAPER_ELIGIBLE` or `STOP`. It cannot
validate an edge or authorize live money.

## Evaluation periods

The complete fixed screen covers 2010–2025 and reports three non-overlapping
eras:

| Era | Signal dates |
|---|---|
| E1 | 2010-01-01 through 2015-12-31 |
| E2 | 2016-01-01 through 2020-12-31 |
| E3 | 2021-01-01 through 2025-12-31 |

Each era starts a fresh `$100,000` book. Pooled metrics sum P&L and committed
capital across the three books; equity curves are never concatenated into a
fictitious CAGR.

No setup parameter is trained. The eras expose stability and recency, not
clean OOS status.

## Control

For each setup and era, run 200 deterministic same-date random-ranking
replicates over the identical candidate pool and identical simulator. Seeds
derive from:

`sha256(study_id | setup_id | era_id | signal_date | replicate)`.

The real setup must beat the 95th percentile pooled random-ranking `NROCC_2x`.
This tests whether its ranking adds value when slots/cash bind. It does not
remove survivor bias or prove that the signal timing itself is causal.

## Metrics

Primary:

`NROCC_2x = sum(closed_trade_net_pnl_2x)
             / sum(entry_fill_notional)`.

Also report:

- starting/ending equity and total net P&L;
- net portfolio return and maximum drawdown;
- closed trades and independent entry dates;
- mean exposure and percent of sessions with exposure;
- turnover and friction share of gross P&L;
- profit factor, win rate, average/median net R;
- holding-time and concurrency distributions;
- cash/slot/gross/liquidity/geometry/gap rejection counts;
- P&L concentration by date, month, year, and symbol;
- era and calendar-year tables; and
- the base-friction result as a fragility diagnostic.

Compute a seeded 95% lower bound for pooled `NROCC_2x` with 5,000
20-session circular moving-block bootstrap replicates within eras. Entry-date
cohorts carry each trade's complete eventual P&L and notional.

## Screening gates

A setup is forward-paper eligible only if every condition is true:

1. doubled-friction pooled net P&L is positive and `NROCC_2x > 0`;
2. the bootstrap 95% lower bound of `NROCC_2x` is strictly positive;
3. real `NROCC_2x` exceeds the 95th percentile random-ranking control;
4. at least 100 trades close on at least 60 independent entry dates;
5. each era has at least 20 closed trades and 12 entry dates;
6. at least two of three eras have positive doubled-friction net P&L;
7. maximum drawdown in every era is at most the charter's 40%;
8. mean gross exposure is at least the charter's 10% in at least two eras;
9. all source, wall, leakage, accounting, capital, slot, cost, and
   determinism checks pass; and
10. two clean executions reproduce all artifact hashes.

Annual positivity, win rate, profit factor, base-cost performance, or a strong
single era cannot rescue a failed gate.

## Selection

If neither setup clears, record `STOP`.

If exactly one clears, freeze it as `FORWARD_PAPER_ELIGIBLE`.

If both clear, choose exactly one by:

1. bootstrap lower bound of `NROCC_2x`, descending;
2. observed `NROCC_2x`, descending;
3. margin over random 95th percentile, descending;
4. worst-era drawdown, ascending;
5. setup ID, ascending.

The other clearing setup remains reported but is not a replacement roster.
No manual override, blend, or least-bad promotion is allowed.

## Required artifacts

Each deterministic run includes:

- authorization and environment records;
- source and setup manifests;
- eligible candidates;
- orders, fills/rejections, trades, and daily equity;
- all 200 controls per setup/era;
- metrics, uncertainty, gates, selection, and limitations;
- independent review; and
- one root identity over every preceding artifact.

Every reader-facing report must state that the current-roster adjusted Yahoo
screen is survivor-biased and that prospective paper evidence is the arbiter.
