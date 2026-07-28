# Prereg: ML Restart Development Matrix

- **Date locked:** 2026-07-26 (America/Los_Angeles)
- **Status:** LOCKED — IMPLEMENTATION NOT AUTHORIZED
- **Governing plan:** `docs/superpowers/plans/2026-07-26-ml-restart.md`
- **Evidence lower bound:** 2026-07-27
- **Development wall:** `2010-01-01 <= date < 2024-01-01`

This prereg locks the development comparison before ML dependencies, feature/label code,
model code, or a real-data ML matrix exists. It does not authorize execution and it does not
alter success-v2 Phase 3 STOP.

## Decision question

Can a bounded causal score select the top three daily long-only swing opportunities with
positive incremental 2×-cost `net_r` versus matched controls, while also satisfying the
absolute success-v2 event bars?

## Research tracks

- **A — daily cross-section:** every causally eligible symbol-session, grouped and split by
  signal date.
- **B — fixed rule-event reranker:** deduplicated `(symbol, signal_date)` union emitted by
  the six exact evaluated Phase 3 trend-pullback and volatility-compression cells. Detector
  parameters are immutable. PEAD is excluded because certified catalyst coverage is absent.

Track B target normalization uses Track A's eligible cross-section. Its primary random
control samples the same-date Track B pool; an additional Track A random control reports
the combined detector-plus-ranker result.

## Targets

- **T1 `relative_net_r_2x` (primary):** fixed-policy 2×-cost `net_r` minus the Track A
  same-date median.
- **T2 `spy_residual_h15`:** raw symbol h=15 return minus matching SPY h=15 return.
- **T3 `useful_opportunity`:** 1 only if absolute 2× `net_r > 0`,
  `relative_net_r_2x > 0`, and absolute raw h=15 return is positive.

All target facts use next-session-open entry, causal ATR14 through the signal bar, 2×ATR
stop, 4×ATR target, strict actual-fill geometry, deterministic same-bar semantics, and a
15-session time stop. Base costs are 5 bps/side + $1/order; 2× costs are 10 bps/side +
$2/order.

## Models and fixed configurations

### M1 regularized linear

- T1/T2 scikit-learn ridge `alpha=10`,
  `solver="lsqr"`, `tol=1e-6`.
- T3 scikit-learn L2 logistic `C=0.1`,
  `solver="lbfgs"`, `max_iter=2000`.
- Fold-local median imputation with missing indicators and standardization.

### M2 scikit-learn shallow histogram gradient boosting

- `max_leaf_nodes=15`;
- `learning_rate=0.05`;
- `max_iter=200`;
- `l2_regularization=10`;
- `min_samples_leaf = 100`;
- `early_stopping=False`;
- native missing-value handling.

### M3 optional LightGBM grouped ranker

Track A + T1 only with `LGBMRanker(objective="lambdarank")`. It runs only after a pre-data
deterministic dependency gate. Locked CPU configuration:

- derive integer relevance 0–4 within each training date by sorting
  `(T1 asc, symbol asc)` and assigning
  `min(4, floor(5 * zero_based_rank / group_size))`;
- `num_leaves=15`;
- `max_depth=3`;
- `learning_rate=0.05`;
- `n_estimators=200`;
- `min_child_samples = 100`;
- no early stopping.

Dependency failure maps to `not_run_dependency_failure`; no substitute library is permitted.
Core matrix size is 12 arms. M3 adds at most one arm family and cannot expand to other
tracks/targets. There is no hyperparameter search.

## Feature dictionary

Use only the plan's locked OHLCV and SPY feature dictionary: return horizons, moving-average
distances, realized volatility, ATR state, daily range/close location, gap facts,
volume/dollar-volume ratios, SPY-relative horizons/regime, and exact Phase 3 detector flags.
Warmup is 300 sessions. No catalysts, fundamentals, text, intraday facts, future membership,
future revisions, target-derived features, feature selection, or post-result additions.

## Eligibility

Signal-date close at least $5; trailing 20-session average dollar volume at least $20M; 300
causal bars; valid next-session open and fixed geometry; complete label path. Dates with
fewer than 20 Track A names are not run. Historical roster status is
`survivor_only_development` unless independently certified otherwise.

## Walk-forward folds

| Fold | Training | Validation |
|---|---|---|
| F1 | 2010–2015 | 2016–2017 |
| F2 | 2010–2017 | 2018–2019 |
| F3 | 2010–2019 | 2020–2021 |
| F4 | 2010–2021 | 2022–2023 |

Purge overlapping training outcomes and embargo the first 15 validation sessions. Fit every
transform/model inside its fold. Random row splits are forbidden.

## Capacity and controls

Primary capacity is deterministic top 3 per date; top 1 and top 5 are sensitivities only.
Tie-break is `(score desc, symbol asc)`.
Track B's primary top-3 comparison requires at least four same-date events. Dates with one
to three are reported but not judged for selection skill; top-1 requires two and top-5
requires six.

Required controls:

- 100 same-date random top-k replicates from the exact track pool at matched dates/count;
- for Track B, an additional 100-replicate Track A same-date comparator;
- symbol-matched random sessions;
- fixed 20-session return descending, 5-session return ascending, and current dollar volume
  divided by its trailing 20-session median descending;
- constant/equal score;
- 20 within-date label permutations per fold;
- future-feature/post-wall rejection canaries;
- one noise feature included in every arm:
  `u = int(sha256(config_hash | row_id).hexdigest()[:16], 16) / 2^64`,
  `noise = 2*u - 1`;
- byte-identical reruns.

## Primary metric

For each date:

`mean(selected top-3 2× net_r) - mean(100 same-date random top-3 2× net_r)`.

Aggregate date-level differences by mean. Report a 90% interval from 2,000 seeded
20-session circular blocked-bootstrap replicates. Model loss, accuracy, AUC, or total profit
cannot replace this metric.

## Development bars

An arm clears only if:

- incremental mean is positive in at least 3 of 4 folds;
- pooled blocked-bootstrap 90% lower bound is strictly positive;
- pooled selected net profit is positive at base and 2× costs;
- pooled selected raw h=15 mean is positive;
- every selected event has valid geometry and hold at most 15 sessions;
- pooled n is at least 100 across at least 60 unique signal dates;
- primary incremental mean beats every fixed simple baseline;
- wall, leakage, permutation, determinism, identity, and data-integrity controls pass.

## Selection

Rank only clearing arms by median fold primary incremental mean, pooled lower90, median fold
absolute 2× mean `net_r`, model simplicity M1→M2→M3, track A→B, target T1→T2→T3, then
canonical config id. Select at most three and at most one per model family.

If no arm clears all bars, verdict STOP. Do not force through a candidate, choose a
profit-maximizing score bucket, tune top-k, add a feature/model/target, or reread a holdout.

## Fresh evidence

No date from 2024-01-01 through 2026-07-26 may be read by this ML line. The actual fresh
event wall must be a future exchange session set only after selected candidate artifacts,
score/collector code, dependencies, configs, and hashes pass independent review. It must be
on or after 2026-07-27. Never backfill the gap.

Fresh event PROCEED additionally requires at least 100 selected closed events, 60 unique
signal dates, positive control-relative mean with a strictly positive 90% lower bound, and
every existing success-v2 absolute event bar. A later portfolio uses another untouched wall.

## Reporting

Report every arm and attempt, including not-run and rejected states. Required slices:
fold/year, SPY regime, liquidity, score bucket, track, target, model, exit reason, MAE,
net-R, friction, unique dates/symbols, and concentration. Missing source facts remain
missing, never zero.

## Deviations log

Append-only. Any change to a target, unit, feature, label policy, geometry, cost, fold,
capacity, control, model family, fixed configuration, selection bar, tie-break, or wall
requires a new dated
prereg and future wall. It cannot amend this development read after results exist.

## Sign-off

- User authorized plan drafting: 2026-07-26
- Planning lock committed: pending this document's first commit
- Implementation authorization: **NOT GRANTED**
- Independent pre-implementation review: pending
