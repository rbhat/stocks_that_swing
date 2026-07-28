# ML-v2 Prospective Forward-Test Preregistration Template

> Template only. It is not active, no setup is selected, no wall is set, and
> no forward read, collection, or deployment is authorized.

## Lock record

- Template version: `ml-v2-forward-template-v1`
- Instantiated prereg path: `[UNSET]`
- Planning commit: `[UNSET]`
- Authorization record hash: `[UNSET]`
- Independent reviewer/date: `[UNSET]`
- Lock commit: `[UNSET]`
- Prospective wall (first eligible exchange session): `[UNSET]`
- Frozen setup count, 1–3: `[UNSET]`
- Maximum observation end: `[UNSET: wall + 18 calendar months]`

This document may be instantiated only after development freezes one to three
setups. All bracketed fields must be resolved, reviewed, hashed, and committed
before the wall. A placeholder, hash mismatch, or observed on/after-wall row
fails closed.

## Frozen roster

For each setup:

| Setup ID | Config hash | Code hash | Data-manifest hash | Model hash or `none` | Simulator hash | Development root identity |
|---|---|---|---|---|---|---|
| `[UNSET]` | `[UNSET]` | `[UNSET]` | `[UNSET]` | `[UNSET]` | `[UNSET]` | `[UNSET]` |

Only rows in this table may run. No substitution, retuning, refit, threshold
change, feature change, candidate replacement, or fallback is permitted
during the forward test. A stopped or inactive setup leaves an empty place;
another setup cannot take it.

## Prospective process

- The committed scheduled process is the first reader and writer of evidence
  with session `>= prospective_wall`.
- Do not pre-read, peek, rehearse on, or backfill any on/after-wall session.
- Use the exact point-in-time eligibility, signals, scores, trading policy,
  sizing, capacity, doubled-friction model, gaps, delistings, rejection rules,
  controls, and identities frozen in development.
- R/H use the single development freeze artifact; no online learning or
  periodic refit. D remains deterministic.
- Score every eligible opportunity and persist every order, rejection, fill,
  position event, exit, daily cash/equity state, data-quality state, and
  control identity append-only.
- Simulate each frozen setup and its controls in independent books. Setups do
  not share capital with each other.
- Never retrospectively create a missed signal or fill. A missed scheduled
  session is a durable `coverage_failure`.
- Development and forward evidence use disjoint roots, ledgers, object-store
  prefixes, and identity domains.

## Observation rule

The first locked read occurs when every frozen setup has:

- at least 100 closed forward trades;
- at least 60 unique entry dates; and
- at least six elapsed calendar months from the wall.

Continue without intermediate performance reads until all frozen setups reach
the floors or 18 calendar months elapse. A setup with an integrity failure
stops but remains in the frozen family and is not replaced. At 18 months, a
setup below either count floor is `STOP_INADEQUATE`. Operational health may be
monitored without aggregating or exposing profitability.

Open positions at the common analysis cutoff are conservatively liquidated at
that session's close under the frozen doubled-friction rule. The outcome read
is single-use. Any later descriptive monitoring is clearly post-verdict and
cannot change it.

## Forward measures and controls

Use the development formulas without alteration:

- primary `NROCC_2x`;
- total doubled-friction net P&L and net portfolio return;
- same-date momentum, pullback, activity, and 200 seeded random-ranking
  portfolios through the identical simulator;
- equal-weight eligible-set ownership as context only;
- 5,000 paired 20-session moving-block bootstrap replicates;
- 999 synchronized within-date score permutations per setup, each rerunning
  the slot/capital simulator without refitting a frozen model;
- maximum drawdown and all secondary diagnostics.

The setup's one-sided p-value tests the paired joint statistic

`T = min(NROCC_2x, Delta_momentum, Delta_pullback,
         Delta_activity, Delta_random95)`.

The exact local permutation p-value is
`(1 + count(T_permuted >= T_observed)) / 1000`. A credible local permutation
is one with `T_permuted >= T_observed`.

Across the frozen roster, apply Holm's step-down correction at family
`alpha=0.05`, ordering exact p-values ascending and comparing
`p_(i) <= 0.05/(m-i+1)`. Here `m` is the number frozen at the wall, not the
number that later remains adequate. The rule and denominator cannot change
after lock.

## Forward PROCEED gates

A frozen setup receives **PROCEED** only if all are true:

1. total doubled-friction net P&L and net portfolio return are strictly
   positive;
2. `NROCC_2x > 0`;
3. paired increment is strictly positive versus every fixed same-date control
   and the 95th percentile random-ranking control;
4. 95% bootstrap lower bound of `NROCC_2x` is strictly positive;
5. Holm-adjusted family test rejects at 0.05;
6. no credible local permutation exists;
7. maximum drawdown is at most 25%;
8. observation floors are met;
9. all data, wall, leakage, coverage, execution, cost, capacity, rejection,
   accounting, retry, and identity checks pass;
10. an independent reproduction matches the frozen root identity and forward
   report hashes.

Annual profits, CAGR, Calmar, profit factor, win rate, R statistics, exposure,
turnover, holding time, concurrency, and concentration are mandatory
diagnostics, not rescue criteria. No per-year positivity gate applies.

## Forward verdicts

- **PROCEED:** all ten gates pass for that exact frozen setup.
- **STOP:** any economic, control, uncertainty, drawdown, integrity, wall,
  coverage, identity, or family test fails.
- **STOP_INADEQUATE:** the setup misses a count floor at 18 months.

There is no PARK-to-promotion, override, substitution, retune, or second-look
path. PROCEED authorizes only a decision discussion. Live trading, production
deployment, or capital allocation requires a separate plan, risk review, and
explicit authorization.

## Required forward artifacts

Write only beneath the locked forward namespace:

`runs/ml-v2/forward/<forward_identity>/`.

Required files mirror the development order/fill/trade/equity/control
artifacts and add:

- instantiated preregistration and lock record;
- wall proof and first-reader proof;
- daily source/coverage manifests;
- append-only completion markers;
- no-backfill audit;
- frozen-artifact verification on every run;
- single-use analysis authorization;
- independent reproduction and final verdict.

## Append-only deviations and operations log

`[EMPTY UNTIL A LATER AUTHORIZED INSTANTIATION]`

Any deviation is recorded before profitability is read and normally maps to
STOP. It never silently edits the frozen setup or this rubric.
