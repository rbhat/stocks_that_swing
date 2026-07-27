# ML Restart — Locked Implementation Plan

- **Locked:** 2026-07-26 (America/Los_Angeles)
- **Authority:** planning only; implementation requires a later explicit user authorization
- **Baseline:** `df7c8b8` plus the decision memo and governance updates committed with this plan
- **Development prereg:** `docs/preregs/2026-07-26_ml-restart-development.md`
- **Clean evidence lower bound:** 2026-07-27
- **Status:** LOCKED — PAUSED BEFORE TASK 1

## Goal

Test whether causal daily information can rank a fixed number of long-only,
next-session-open swing opportunities that produce positive incremental and absolute net
economics after friction, without relabeling broad equity drift as timing skill.

This plan creates a new ML research line. It does not reopen success-v2 Phase 3, authorize
Phase 4, grandfather any rule candidate, or modify any historical prereg, artifact, verdict,
ledger, or namespace.

## Authorization boundary

The planning commit authorizes no execution task in this file.

Do not install or lock dependencies, open a price parquet or catalyst cache, construct a
feature or label, fit a transform or model, read a bar on or after 2024-01-01, collect a new
event, deploy a collector, or create a portfolio expression until the user explicitly
authorizes implementation.

After implementation authorization, execute tasks in order. Every task ends with tests,
evidence, and one focused commit. Stop at every named review gate.

## Locked decisions

### Research tracks

The development matrix has two tracks.

1. **Track A — daily cross-section.** One row per eligible `(symbol, signal_session)`.
   Rows are evaluated as date groups. The model ranks the eligible symbols for each date;
   row count is never treated as independent sample size.
2. **Track B — fixed rule-event reranker.** Use the deduplicated union of the six exact
   pre-2024 trend-pullback and volatility-compression event streams from
   `configs/success_v2_phase3.yaml`. Do not retune a detector or add PEAD. This asks whether
   ML can select within the rule screens that failed as unconditional candidates; it does
   not reverse or weaken their Phase 3 STOP.

Track B uses Track A's same-date eligible cross-section for target normalization. Its
primary random control samples from the same-date Track B event pool to isolate reranking
skill; a second Track A random control reports the combined detector-plus-ranker result. A
Track B result may advance only under the same absolute and control-relative gates as
Track A.

### Targets

Each track/model combination evaluates three preregistered targets:

- **T1 — `relative_net_r_2x` (primary):** fixed-policy event `net_r` at 2× friction minus
  the median fixed-policy 2× `net_r` of all Track A eligible rows on the signal date.
- **T2 — `spy_residual_h15`:** symbol raw h=15 return from actual next-session open minus
  SPY raw h=15 return over matching entry/exit sessions.
- **T3 — `useful_opportunity`:** binary 1 only when absolute fixed-policy 2× `net_r > 0`,
  `relative_net_r_2x > 0`, and the symbol's absolute raw h=15 return is positive; otherwise
  0.

T1 and T2 are continuous regression targets. T3 is a classification target. All models are
selected by the same downstream economic metric; regression loss, classification loss,
accuracy, AUC, or ranking loss can diagnose a fit but cannot promote it.

### Fixed label policy

Targets use the Phase 3 fixed policy as a measurement instrument, not as a promoted
candidate:

- causal facts end at the completed `signal_session`;
- fill at the actual next exchange session open;
- ATR14 calculated only through the signal bar;
- 2×ATR initial stop and 4×ATR initial target;
- strict actual-fill `planned_r > 1.5`;
- strict actual-fill charter risk below 12% and success risk below 25%;
- hard 15-session time stop;
- existing deterministic same-bar stop/target semantics;
- base friction 5 bps/side + $1/order;
- 2× friction 10 bps/side + $2/order.

Do not tune geometry, costs, entry time, ambiguous-bar ordering, or hold length in this ML
line. A later geometry study requires a new plan and future wall.

### Model families and fixed configurations

The 12-arm core matrix is:

`2 tracks × 3 targets × 2 model families`.

- **M1 — regularized linear benchmark**
  - T1/T2: scikit-learn ridge regression with
    `alpha=10`, `solver="lsqr"`, and `tol=1e-6`.
  - T3: scikit-learn L2 logistic regression with
    `C=0.1`, `solver="lbfgs"`, and `max_iter=2000`.
  - Numeric features are median-imputed with missing indicators and standardized inside
    each training fold.
- **M2 — scikit-learn shallow histogram gradient boosting**
  - `max_leaf_nodes=15`;
  - `learning_rate=0.05`;
  - `max_iter=200`;
  - `l2_regularization=10`;
  - `min_samples_leaf = 100`;
  - `early_stopping=False`;
  - native missing-value handling and no result-driven threshold search.

One optional thirteenth arm is permitted:

- **M3 — LightGBM grouped ranking challenger:** Track A + T1 only,
  `LGBMRanker(objective="lambdarank")`, CPU deterministic ranking grouped by signal date.
  Convert each training date's T1 values to relevance grades 0–4 by sorting
  `(T1 asc, symbol asc)` and assigning
  `min(4, floor(5 * zero_based_rank / group_size))`; higher grades are better.
  Use `num_leaves=15`, `max_depth=3`, `learning_rate=0.05`,
  `n_estimators=200`, and `min_child_samples=100`; no early stopping.

M3 runs only if the dependency gate certifies a deterministic Python 3.12-compatible
ranking library before any real-data feature or label build. If that gate fails, record
`not_run_dependency_failure`; do not substitute another library or widen the core matrix.

There is no hyperparameter search. No neural network, random forest, generalized additive
model, SHAP package, Optuna search, Bayesian optimization, GPU training, target ensemble,
model ensemble, or post-result feature selection is allowed in this plan.

### Features

The initial feature dictionary is OHLCV-only and causal:

- split/dividend-adjusted return horizons: 1, 2, 5, 10, 20, 60, 126, and 252 sessions;
- close distance from 10, 20, 50, 100, and 200-session moving averages;
- realized close-to-close volatility over 5, 10, 20, and 60 sessions;
- ATR14 as a fraction of close and its trailing 60-session percentile;
- current range as a fraction of close, close position within the daily range, and
  next-to-prior gap facts available at the signal close;
- volume divided by trailing 5, 20, and 60-session medians;
- dollar volume divided by its trailing 20 and 60-session medians;
- SPY-relative returns at 5, 20, 60, 126, and 252 sessions;
- SPY close above/below its causal 200-session moving average;
- exact Phase 3 detector flags, only as binary features on Track A and as provenance on
  Track B.

Warmup is 300 completed sessions. Infinite values become missing; missingness is explicit
and fold-local imputation is required. No target-derived feature, future membership fact,
future catalyst fact, contemporaneously unavailable earnings time, sector inferred from
future membership, model-derived feature, or feature added after seeing a result is allowed.

Catalyst features are excluded from the locked matrix because certified point-in-time
coverage is absent. Passing a later catalyst data gate does not add them here; it permits a
separate future prereg.

### Eligibility and capacity

Track A eligibility on each signal date requires:

- a security in the frozen development roster;
- at least 300 completed causal bars;
- signal-date adjusted close at least $5;
- trailing 20-session average dollar volume at least $20M;
- a valid next-session open, valid fixed geometry, and complete 15-session label path.

This historical roster is known survivor-biased. The development artifact and every result
must say so. The fresh collector freezes the then-eligible live roster before its wall, so
future membership is never used for the fresh verdict.

Scores use deterministic tie-break `(score desc, symbol asc)`. The primary capacity is top
3 per signal date. Top 1 and top 5 are locked sensitivities only; they cannot select a model.
Dates with fewer than 20 eligible Track A symbols are `not_run_inadequate_cross_section`.
Track B's primary top-3 comparison requires at least four same-date fixed-rule events; dates
with one to three events are reported but `not_run_inadequate_track_cross_section` for
selection skill. Its top-1 sensitivity requires two events and top-5 sensitivity requires
six.
Event simulation is independent; portfolio slots do not suppress development or fresh
event-level rows.

### Internal walk-forward folds

Only dates before 2024-01-01 may enter development. Use four expanding folds:

| Fold | Training dates | Validation dates |
|---|---|---|
| F1 | 2010-01-01 through 2015-12-31 | 2016-01-01 through 2017-12-31 |
| F2 | 2010-01-01 through 2017-12-31 | 2018-01-01 through 2019-12-31 |
| F3 | 2010-01-01 through 2019-12-31 | 2020-01-01 through 2021-12-31 |
| F4 | 2010-01-01 through 2021-12-31 | 2022-01-01 through 2023-12-31 |

Use exchange sessions, not calendar-day arithmetic. Purge training rows whose h=15 or
fixed-policy outcome overlaps validation, and embargo the first 15 validation sessions.
All imputers, scalers, and model state fit only on that fold's remaining training rows.
No random row split is permitted.

After the development candidate list is frozen, refit each selected candidate once on all
eligible pre-2024 rows. That refit cannot change features, target, fixed configuration, score
direction, top-k, or candidate count.

### Selection metric and rubric

For each validation date, compare the model's top 3 with the mean of 100 same-date random
top-3 controls from the exact track-eligible pool. For Track B, also report a 100-replicate
Track A random top-3 comparator. Seeds derive deterministically from
`sha256(config_hash | fold | date | replicate | control_id)`; no seed may be chosen by
outcome.

The primary metric is:

`mean(selected 2× net_r) - mean(same-date random-control 2× net_r)`.

Uncertainty uses a seeded 20-session circular blocked bootstrap over date-level differences,
2,000 replicates, and a 90% interval. Report unique dates and symbols alongside row/event
counts.

An arm is development-credible only if:

1. primary incremental mean is positive in at least 3 of 4 folds;
2. pooled date-blocked 90% lower bound is strictly positive;
3. pooled selected absolute net profit is positive at base and 2× friction;
4. pooled selected raw h=15 mean is positive;
5. every selected event has valid actual-fill geometry and hold at most 15 sessions;
6. pooled selected n is at least 100 and includes at least 60 unique signal dates;
7. it beats the fixed activity, momentum, and constant/equal-score baselines on the primary
   incremental mean;
8. all leakage, permutation, wall, determinism, and data-integrity controls pass.

Rank eligible arms by:

1. median fold primary incremental mean, descending;
2. pooled 90% lower bound, descending;
3. median fold absolute 2× mean `net_r`, descending;
4. model simplicity `M1`, then `M2`, then `M3`;
5. track `A`, then `B`;
6. target `T1`, then `T2`, then `T3`;
7. canonical config id ascending.

Select at most three exact candidates and at most one candidate per model family. If no arm
clears every bar, record STOP. Do not promote the least-bad arm.

## Required controls

Every development and fresh report includes:

1. same-date random top-k from the exact track pool at matched dates and count, plus the
   additional Track A comparator for Track B;
2. the Phase 3-compatible symbol-matched random-session control;
3. fixed simple ranks:
   - 20-session return descending;
   - 5-session return ascending;
   - current dollar volume divided by its trailing 20-session median, descending;
4. constant/equal-score deterministic symbol ordering;
5. 20 within-date label-permutation replicates per fold;
6. synthetic future-feature and post-wall canaries that the builder must reject;
7. one noise feature included in every arm:
   `u = int(sha256(config_hash | row_id).hexdigest()[:16], 16) / 2^64`,
   `noise = 2*u - 1`; report its
   coefficient/importance, but never use it to remove or add a feature;
8. byte-identical rerun checks for manifests, matrices, folds, models, scores, and reports.

Any future-feature canary accepted, post-wall row observed, transform fit outside its
training fold, permutation arm clearing the real selection gate, or nondeterministic
candidate identity is an immediate STOP.

## Data walls

The wall contract has four layers:

1. **Development:** `2010-01-01 <= date < 2024-01-01`.
2. **Quarantine:** `2024-01-01 <= date < 2026-07-27`. The period is historically consumed
   and must not be read by this ML line, even as a rehearsal.
3. **Clean lower bound:** no ML verdict row may predate 2026-07-27.
4. **Actual ML event wall:** set to the first future exchange session after model, config,
   dependency, feature, label, score-to-event, and collector code hashes are locked and
   independently reviewed. Never backfill the gap between 2026-07-27 and this actual wall.

The holdout reader refuses to run before the actual wall is recorded in a locked candidate
prereg and refuses mismatched hashes. The scheduled collector is the first writer of event
evidence. A later portfolio wall is set only after an event-level PROCEED; no event-verdict
row counts toward that portfolio holdout.

## Data-feasibility dispositions

Before real-data construction, classify each source:

- `point_in_time_certified`;
- `survivor_only_development`;
- `not_run_input_failure`;
- `rejected_leakage_risk`.

The current OHLCV roster starts as `survivor_only_development`. It may support development,
but no pre-2024 result is clean OOS evidence. Missing point-in-time constituent/delisting
history must remain visible. The prospective fresh roster and collector are the arbiter.

Catalyst data starts as `not_run_input_failure` for this plan and is excluded. Missing
sources are never encoded as zero. Adjusted-history vintage limitations, delistings,
membership, security type, gaps, missing sessions, and source revisions must be recorded in
the data manifest.

## Implementation sequence

### Task 1 — Baseline, optional dependencies, and lockfile

**Files:**

- Modify: `pyproject.toml`
- Create: `uv.lock`
- Create: `docs/evidence/ml-restart/phase-0.md`

After explicit implementation authorization:

- [ ] Record planning commit SHA and clean `git status --short`.
- [ ] Add an `ml` optional dependency group with scikit-learn for M1/M2.
- [ ] Add LightGBM only if its isolated M3 compatibility probe passes; otherwise record
      `not_run_dependency_failure`.
- [ ] Run `uv lock`; no unpinned ad-hoc install or global environment mutation.
- [ ] Verify imports, deterministic CPU fitting, serialization round-trip, Python 3.12,
      NumPy, pandas, and pyarrow compatibility on synthetic data only.
- [ ] Run full tests, `ruff check --fix`, and `git diff --check`.
- [ ] Commit: `build: lock bounded ML research dependencies`.

**Gate:** dependency set and lockfile are deterministic; no real data was read and no model
was fitted on market data.

### Task 2 — Wall, unit, target, and feature contracts

**Files:**

- Create: `src/sts/ml/contracts.py`
- Create: `src/sts/ml/walls.py`
- Create: `src/sts/ml/units.py`
- Create: `src/sts/ml/features.py`
- Create: `src/sts/ml/labels.py`
- Create: matching `tests/test_ml_*.py`
- Create: `docs/evidence/ml-restart/phase-1.md`

- [ ] Write failing synthetic tests for strict walls, session arithmetic, eligibility,
      warmup, missing facts, Track A grouping, Track B deduplication, all three targets,
      geometry, costs, ambiguous bars, and feature availability.
- [ ] Prove post-wall and future-feature canaries fail closed.
- [ ] Implement pure modules with no network or implicit filesystem fallback.
- [ ] Produce canonical config hashes and deterministic row identities.
- [ ] Run focused/full tests, `ruff check --fix`, and `git diff --check`.
- [ ] Commit: `feat: add causal ML research contracts`.

**Gate:** synthetic contracts pass; no real price/catalyst data was read.

### Task 3 — Data manifest and pre-2024 matrix builder

**Files:**

- Create: `src/sts/ml/data.py`
- Create: `scripts/build_ml_development_data.py`
- Create: `tests/test_ml_data.py`
- Create: `docs/evidence/ml-restart/phase-2.md`
- Create: versioned artifacts under `runs/ml-restart/development/`

- [ ] Inventory only allowed source metadata and record all data-feasibility dispositions.
- [ ] Predicate-filter parquet reads to the development wall before materialization.
- [ ] Refuse any returned row outside the development range.
- [ ] Build Track A and Track B matrices, labels, coverage states, and content hashes.
- [ ] Record row counts by date/symbol/track and missingness; never dump raw values into docs.
- [ ] Run duplicate-key, join-cardinality, completeness, vintage, and survivorship checks.
- [ ] Run twice and require byte-identical manifests/artifacts.
- [ ] Run focused/full tests, `ruff check --fix`, and `git diff --check`.
- [ ] Commit: `feat: build walled ML development matrices`.

**Gate:** zero rows on or after 2024-01-01 were observed; source limitations are explicit;
matrices are deterministic and no model was fitted.

### Task 4 — Models, folds, controls, and economic evaluator

**Files:**

- Create: `src/sts/ml/models.py`
- Create: `src/sts/ml/evaluation.py`
- Create: `src/sts/ml/controls.py`
- Create: matching tests
- Create: `docs/evidence/ml-restart/phase-3.md`

- [ ] Implement the exact fold-local pipelines and fixed model configurations.
- [ ] Implement top-k selection and every required control.
- [ ] Implement date-level incremental metrics and blocked uncertainty.
- [ ] Hand-check tiny regression, classification, top-k, and bootstrap cases.
- [ ] Prove permutation and leakage canaries cannot promote.
- [ ] Prove reruns serialize identical configs, scores, and selected identities.
- [ ] Run focused/full tests, `ruff check --fix`, and `git diff --check`.
- [ ] Commit: `feat: add bounded ML evaluation harness`.

**Gate:** synthetic and hand-calculated evaluation passes; no real model fitting yet.

### Task 5 — Pre-2024 development run and candidate freeze

**Files:**

- Create: `scripts/run_ml_development.py`
- Create: `runs/ml-restart/development/report.json`
- Create: `docs/evidence/ml-restart/phase-4.md`
- Create, only for selected candidates:
  `docs/preregs/<date>_ml-event-<candidate-id>.md`

- [ ] Fit exactly the locked matrix on the pre-2024 matrices.
- [ ] Record every attempted arm and fold result append-only.
- [ ] Apply the locked selection rubric without manual rescue.
- [ ] Select zero to three candidates, at most one per model family.
- [ ] If zero qualify, record STOP in `decisions.md` and end the plan.
- [ ] If candidates qualify, refit on all eligible pre-2024 rows and freeze artifacts.
- [ ] Write exact candidate preregs with feature/config/model/data hashes and a future event
      wall placeholder; do not read or set the wall yet.
- [ ] Independent methodology and causality review.
- [ ] Commit: `research: freeze ML event candidates or record STOP`.

**Gate:** exact candidate list or honest STOP. Dates on or after 2024-01-01 remain unread.

### Task 6 — Prospective wall lock and local full-flow rehearsal

**Files:**

- Create: `src/sts/ml/scoring.py`
- Create: `src/sts/ml/collector.py`
- Create: `scripts/run_ml_event_collection.py`
- Create: focused tests
- Append only: selected candidate preregs
- Create: `docs/evidence/ml-restart/phase-5.md`

- [ ] Implement scoring with final-bar truncation and deterministic identities.
- [ ] Revalidate actual-open geometry and durable rejection.
- [ ] Rehearse with synthetic and pre-2024 truncated frames only.
- [ ] Inject crashes at each durable stage and require byte-identical resumed state.
- [ ] Independent review model/config/data/code hashes.
- [ ] Set the actual event wall to the first future exchange session after the reviewed lock.
- [ ] Append the wall and hashes to each candidate prereg and commit before any wall row is
      read.
- [ ] Commit: `chore: lock prospective ML event wall`.

**Gate:** collector and hashes are locked before the actual wall; no post-wall data was read
and no collection was enabled.

### Task 7 — Untouched event collection

- [ ] Deploy only the reviewed event collector under a fresh versioned namespace.
- [ ] Keep legacy upkeep isolated; never enable success-v2 Phase 4.
- [ ] Scheduled job is the first writer; never backfill missed sessions or the lower-bound
      gap.
- [ ] Journal coverage, scores, selected/control events, geometry rejects, outcomes,
      completion markers, and sync append-only.
- [ ] Simulate candidate and controls independently; portfolio slots do not suppress events.
- [ ] Reconcile the first scheduled EOD/fill/upkeep cycle and require independent review.
- [ ] Commit deployment evidence only: `ops: start walled ML event collection`.

**Gate:** first cycle reconciles with no duplicate, future-data, legacy, or namespace
collision.

### Task 8 — Fresh event verdict

After each candidate reaches at least 100 closed selected events and 60 unique signal dates:

- [ ] Produce the locked candidate/control report at base and 2× costs.
- [ ] Apply the existing success-v2 bars plus the fresh incremental-selection bars.
- [ ] Report year, regime, liquidity, score, target, exit, MAE, net-R, friction, date,
      symbol, sector-if-certified, and concentration slices.
- [ ] Independently reproduce the report and inspect all source hashes.
- [ ] Append PROCEED/PARK/STOP to `decisions.md`; do not override the rubric silently.
- [ ] Commit: `research: record ML event verdict`.

**Gate:** at least one exact candidate PROCEEDs or the ML restart records STOP.

### Task 9 — Later portfolio expression

Only event-level survivors receive a new portfolio prereg. Set a second future wall after
the event verdict, use a fresh ledger/namespace, and preserve the existing requirements of
at least 30 closed trades and three calendar months. Require positive net return inside the
matched event-OOS band, drawdown at most 40%, deployment at least 10%, valid geometry at
every fill, controls, and independent review.

Phase 6/7 event rows never count toward this portfolio holdout. Portfolio implementation and
deployment require another explicit user authorization after the event verdict.

## Stop conditions

Stop immediately and record the reason if:

- implementation begins without explicit post-plan authorization;
- any ML path reads a bar on or after 2024-01-01 before the prospective event collector is
  locked and authorized;
- quarantine dates are used as rehearsal, validation, or model selection;
- a feature or transform uses information unavailable at the signal close;
- historical membership or missing catalyst facts are silently treated as point-in-time;
- geometry, costs, hold, features, targets, top-k, folds, models, or fixed configurations
  change after lock;
- a non-preregistered arm, library, threshold, feature, target, or ensemble is added;
- total profit, accuracy, AUC, or best bucket replaces the primary selection metric;
- a permutation/control arm passes and the issue is not resolved before evidence access;
- a failed bar is bypassed, a holdout is reread after a change, or evidence is backfilled,
  rewritten, omitted, or written into a legacy namespace.

## Definition of done

The ML restart succeeds only when one locked model/target/track candidate passes at least 100
untouched selected events and 60 unique fresh signal dates under both the incremental and
absolute event gates, then a later independently walled portfolio passes the existing
30-trade/three-month promotion gate.

Dependency installation, deterministic fitting, a high cross-validation score, a profitable
survivor-biased development run, or successful deployment is not success by itself.

## Locked pause

This document and its development prereg are the final outputs currently authorized. Commit
the planning package, then stop. Task 1 begins only after a new explicit user authorization.
