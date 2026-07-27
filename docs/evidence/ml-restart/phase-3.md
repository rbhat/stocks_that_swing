# ML restart Phase 3 — bounded ML evaluation harness

- Completed: 2026-07-27 (America/Los_Angeles)
- Starting Task 4 commit:
  `15eea78` (`feat: build walled ML development matrices`)
- Implementation authorization: Tasks 3 and 4; this evidence covers Task 4 only
- Task 5 authorization: not granted

## Locked arms and fold-local models

`src/sts/ml/models.py` defines exactly the 12 core arms and the dependency-gated
Track A + T1 M3 challenger. It implements:

- M1 Ridge and logistic configurations exactly as locked;
- fold-local median imputation with missing indicators and standardization for
  M1;
- M2 shallow histogram gradient boosting with the fixed depth/capacity,
  regularization, sample, iteration, and early-stopping settings;
- M3 deterministic CPU LambdaRank with exact within-date 0–4 relevance grades
  sorted by `(T1 asc, symbol asc)`;
- the locked feature identity plus the exact per-arm deterministic noise
  canary;
- deterministic scoring and fitted-model serialization.

There is no hyperparameter search, threshold search, feature selection,
ensemble, alternate model family, or result-dependent setting.

## Folds, controls, and economics

`src/sts/ml/evaluation.py` and `src/sts/ml/controls.py` implement:

- the four exact expanding walk-forward folds;
- purge by the complete h=15 label end;
- a required caller-supplied, strictly ordered exchange-session calendar for
  the 15-session validation embargo;
- deterministic `(score desc, symbol asc)` top 3 selection plus locked top 1
  and top 5 sensitivities;
- 100 same-date random top-k replicates seeded from
  `sha256(config_hash | fold | date | replicate | control_id)`;
- both the Track B same-event-pool control and the additional matched-date
  Track A comparator;
- the Phase-3-compatible symbol-matched random-session control;
- 20-session momentum, five-session pullback, activity, and constant/equal
  score baselines;
- exactly 20 within-date label-permutation replicates;
- date-level incremental 2× net R and a seeded 2,000-replicate, 20-session
  circular blocked-bootstrap 90% interval;
- the complete development credibility bars and exact arm ordering;
- at most three selected candidates and at most one per model family.

The promotion control contract fails closed when a future-feature or post-wall
canary is accepted, a transform is not fold-local, a permutation arm clears,
candidate identity is nondeterministic, or data integrity fails.

## Synthetic and hand-checked evidence

Tests cover:

- exact M1/M2 estimator settings and the legal M3 arm boundary;
- regression and classification fits for M1/M2 and the M3 ranker;
- M3 relevance grading with a target/symbol tie;
- deterministic noise, scores, selected identities, model bytes, and pickle
  round trips;
- single-class classification refusal;
- session-based fold purge and embargo;
- deterministic top-k tie breaks and 100-replicate controls;
- Track B and Track A matched-date controls;
- symbol-matched random-session identity;
- within-date permutation membership/identity preservation;
- all four fixed baselines;
- a constant blocked-bootstrap case whose mean/lower90/upper90 are all exactly
  0.25;
- a two-date economic evaluator case with hand-checkable positive incremental
  selection;
- leakage and permutation canaries blocking promotion;
- exact candidate ranking and the one-candidate-per-family cap.

Each model family was fit twice on seeded synthetic data. Scores and serialized
model bytes were identical, and serialization round trips preserved scores.
No model in this phase was fitted on a development matrix or other market data.

## Verification

- Focused Task 3/4 synthetic suite: `21 passed in 10.47s`.
- Full frozen-lock suite: `447 passed in 21.99s`.
- Task-scoped Ruff 0.16.0: passed.
- `git diff --check`: passed.

## Phase gate

Gate: **PASS**. Synthetic and hand-calculated evaluation passes, required
controls and canaries fail closed, and arm/model/config/score/selection
identities are deterministic. No real model fitting, development run, arm
verdict, candidate selection, refit, candidate prereg, post-2023 read,
collection, or deployment occurred.

Task 5 remains unauthorized and has not started.
