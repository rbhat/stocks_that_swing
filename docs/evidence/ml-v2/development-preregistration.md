# ML-v2 Development Preregistration

- **Created:** 2026-07-28 (America/Los_Angeles)
- **Status:** LOCKED FOR PLANNING; EXECUTION NOT AUTHORIZED
- **Governing plan:** `docs/PLAN.md`
- **Setup roster:** `docs/evidence/ml-v2/setup-matrix.md`
- **Contract:** `docs/evidence/ml-v2/research-contract.md`
- **Prospective wall:** deliberately unset

## Decision question

Does any one of the six complete, fixed setups produce deployable portfolio
profit across all accepted trades after doubled costs, while outperforming
valid same-date selection controls and surviving uncertainty, drawdown,
adequacy, leakage, permutation, and deterministic-reproduction gates?

Development can answer only which zero to three setups deserve a future
prospective test. It cannot validate a live edge or change any predecessor
verdict.

## Locked development interval and folds

Eligible signal dates are:

`2004-01-01 <= signal_date < 2026-01-01`.

Earlier rows may be read only as the causal 300-session warmup for the first
eligible signal date and never enter metrics or training labels. Dates from
2026 onward are outside this development study. This boundary is a historical
development cutoff, not a prospective wall.

Use five expanding walk-forward folds:

| Fold | Training signal dates | Validation signal dates |
|---|---|---|
| F1 | 2004-01-01 through 2010-12-31 | 2011-01-01 through 2013-12-31 |
| F2 | 2004-01-01 through 2013-12-31 | 2014-01-01 through 2016-12-31 |
| F3 | 2004-01-01 through 2016-12-31 | 2017-01-01 through 2019-12-31 |
| F4 | 2004-01-01 through 2019-12-31 | 2020-01-01 through 2022-12-31 |
| F5 | 2004-01-01 through 2022-12-31 | 2023-01-01 through 2025-12-31 |

Use exchange sessions. Purge training observations whose 15-session outcome
touches validation. Embargo the first 15 validation sessions. Fit every
imputer, scaler, and model only on the remaining fold-local training set.
Random row splits and global transforms are forbidden.

Each validation fold starts with a fresh `$1,000,000` setup book. Pooled
metrics sum fold trade P&L and committed capital; fold equity is never carried
into the next fold. Training-period simulated profits never enter selection.
Pooled starting equity is therefore `$5,000,000`; pooled ending equity is the
sum of the five fold-ending equities.

## Locked baselines and controls

Every real setup receives controls from its exact same-date signal pool,
execution policy, sizing rules, slot/cash state machine, costs, and validation
folds:

1. **Repeated seeded random ranking:** 200 independent rank orders per fold.
   Report their full distribution. The gate compares the setup with the 95th
   percentile pooled random `NROCC_2x`, not a favorable seed.
2. **Momentum ranking:** 20-session split-adjusted return, descending.
3. **Pullback ranking:** 5-session split-adjusted return, ascending.
4. **Activity ranking:** current volume divided by prior-20-session median
   volume, descending.

All control ties use the setup's permanent-ID hash tie-break. No equal score
is truncated by symbol order. Random order seeds derive from
`sha256(study_id | setup_id | fold_id | signal_date | replicate |
control_id)` and are never selected by outcome.

Also report an **equal-weight eligible-set ownership benchmark**: on the first
session of each calendar month, target 80% of equity equally across every name
satisfying universe items 1–5 in `setup-matrix.md`, without requiring a P/B
signal or applying the earnings-entry embargo. Cap each name at 1% of trailing
20-session median dollar volume; capped residual remains cash and is not
redistributed. Hold until the next rebalance and apply the setup's doubled
friction, delisting, and missing-print rules. This is a market-ownership
context benchmark; because its mandate, turnover, slots, and holding period
differ from a swing setup, it is not a same-date selection gate and cannot
rescue or fail a setup.

## Exact primary and paired measures

For setup `s`:

`NROCC_2x(s) = Σ_i net_pnl_i_2x / Σ_i entry_fill_notional_i`.

For same-date control `c`:

`Delta_s,c = NROCC_2x(s) - NROCC_2x(c)`.

For random controls:

`Delta_s,random95 = NROCC_2x(s) - percentile95_b(NROCC_2x(random_b))`.

All sums include every closed or terminally liquidated validation trade from
all five folds. The denominator is strictly positive or the setup is
inadequate.

The pooled uncertainty lower bound is the fifth percentile of 5,000 seeded
20-exchange-session circular moving-block bootstrap replicates over entry-date
cohorts. A cohort carries each trade's full eventual net P&L and entry
notional. Blocks are sampled within folds and pooled by summing numerators and
denominators. Use the same sampled blocks for paired setup/control
differences. Seeds derive only from
`sha256(study_id | setup_id | statistic_id | replicate)`.

## Locked profitability and credibility gates

A setup clears development only when every gate is true:

1. **Portfolio profit:** total doubled-friction net P&L is strictly positive,
   pooled ending equity exceeds `$5,000,000`, and `NROCC_2x > 0`.
2. **Valid same-date increment:** `Delta` is strictly positive versus each
   fixed momentum, pullback, and activity control and
   `Delta_s,random95 > 0`.
3. **Positive pooled uncertainty:** the bootstrap 95% lower bound of
   `NROCC_2x` is strictly positive.
4. **Drawdown:** maximum peak-to-trough drawdown on each fold's
   doubled-friction daily marked equity is at most 25%, and pooled worst-fold
   drawdown is therefore at most 25%.
5. **Adequacy:** at least 300 closed validation trades, at least 150 unique
   entry dates, and at least four folds with both 30 closed trades and 20
   unique entry dates.
6. **Short-period treatment:** no per-year positivity, CAGR, or
   profit-concentration threshold is imposed. Profits earned in short
   episodes are allowed; they do not bypass pooled profit, uncertainty,
   drawdown, date, fold, or permutation gates. Year and episode concentration
   remain mandatory diagnostics.
7. **Local permutation falsification:** none of 999 local synchronized
   permutations equals or exceeds the observed setup's joint profitability
   statistic; exact local `p = 1/1000`.
8. **Family multiplicity:** the preregistered single-step Westfall–Young maxT
   adjusted p-value is at most 0.05 across the six setups.
9. **Integrity:** every wall, point-in-time, security-master, delisting,
   corporate-action, earnings-embargo, leakage, fold-local transform,
   purging, embargo, capital, slot, capacity, fill, and doubled-friction check
   passes.
10. **Determinism:** two clean executions have byte-identical input manifests,
    eligible rows, folds, transforms, fitted artifacts, scores, order
    identities, fills, rejections, trades, daily equity, controls,
    permutations, metrics, and root identity hash.

Base-cost profitability, fold signs, annual signs, CAGR, Calmar, profit
factor, win rate, average/median R, exposure, turnover, holding time,
concurrency, and result concentration cannot compensate for a failed gate.

## Local permutations and family rule

Use 999 synchronized replicates. Within every setup/fold/date:

- D setups permute the deterministic scores among that setup's same-date
  signal candidates;
- R/H setups permute fixed-policy training targets within training dates,
  refit the complete fold-local pipeline, and independently permute validation
  score assignments within validation dates.

Candidate events, outcomes, dates, signal counts, missingness, and simulator
rules remain fixed. Each replicate reruns the actual slot/capital simulator.

For setup `s`, define the joint statistic:

`T_s = min(NROCC_2x(s), Delta_s,momentum, Delta_s,pullback,
           Delta_s,activity, Delta_s,random95)`.

A local permutation is credible when `T_s,b >= T_s,observed`. The local gate
requires zero credible replicates. For the family:

`p_FWER(s) = (1 + count_b(max_k T_k,b >= T_s,observed)) / 1000`.

The six setups use the same replicate numbers and seed derivation, preserving
their dependence. This maxT rule controls family-wise error without treating
an unexplained clear anywhere in hundreds of unrelated controls as a veto on
every setup. It is locked before execution and cannot be changed after seeing
results.

## Deterministic top-three selection

Rank only setups that clear all ten gates:

1. bootstrap 95% lower bound of `NROCC_2x`, descending;
2. observed `NROCC_2x`, descending;
3. minimum fixed/random incremental margin, descending;
4. worst-fold maximum drawdown, ascending;
5. ranking simplicity D, then R, then H;
6. setup ID ascending.

Take the first three or all clearing setups when fewer than three clear. If
none clear, record STOP. Do not promote a failed setup, fill a quota, or use
the equal-weight benchmark to change the order.

## Freeze and separation

For every selected setup, refit R/H once on all eligible development rows
using the unchanged pipeline; D has no artifact fit. Freeze the exact code,
configuration, data manifest, source hashes, feature schema, fitted artifact,
simulator, report, and root identity described in `research-contract.md`.

After freeze:

- no substitution, retuning, threshold change, refit, ensemble, or candidate
  replacement;
- no development row may be written into a forward namespace;
- no forward row may be used to revise development;
- a prospective wall remains unset until a later separately authorized gate
  completes the forward preregistration and independent hash review.

## Verdicts

- **FREEZE 1–3:** only the exact clearing setups selected by the ranking rule.
- **STOP:** zero setups clear, any global STOP fires, or required evidence is
  invalid.
- **NOT RUN / STOP_INPUT:** critical point-in-time inputs or adequacy are
  unavailable. Missing evidence is never interpreted as zero profit or a
  failed signal.

There is no PARK-to-promotion or manual override path in development.
