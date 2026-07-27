# ML Restart Exploration — Decision Memo

- **Date:** 2026-07-26 (America/Los_Angeles)
- **Baseline:** `df7c8b8` (`docs: propose ML restart exploration`)
- **Status:** EXPLORATION COMPLETE — USER DECISION PENDING
- **Authority:** memo only; not a preregistration, implementation plan, model selection, or
  authorization to read new evidence

## Technical summary

An ML study is worth planning only if it is framed as **daily opportunity selection relative
to controls**, not as prediction of raw long-equity returns. Phase 3 showed why: all six
evaluated rule cells were absolutely profitable, yet every one lost to its symbol-matched
random-session control on raw h=15 return and mean 2×-cost net profit. An ML study that
optimizes raw return, hit rate, or total profit can reproduce the same false success with more
degrees of freedom.

The most decision-aligned research shape is a date-grouped comparison of eligible
symbol-sessions, evaluated as a fixed-capacity top-k selection problem. A symbol-session,
event, and date-level ranking remain distinct alternatives; none is selected or locked by
this memo. Likewise, no target or model family is declared the winner. A future locked plan
should compare a transparent regularized linear benchmark with one shallow boosted-tree
challenger, and optionally compare pointwise scoring with a date-grouped ranking objective.
Deep learning, unconstrained hyperparameter search, and profit-maximizing bucket search are
not justified for the first study.

The current historical price cache is adequate for feasibility work but not for a credible
ML verdict. Its strongest facts are 235 usable daily OHLCV histories, 767,028 pre-2024 rows,
split/dividend-adjusted prices, causal next-session-open simulation, and tested success
metrics. Its material gaps are a roster assembled in 2026, no point-in-time constituent or
delisting history, no certified point-in-time catalyst coverage, and no data-vintage record
for later revisions. These are **high-severity modeling risks**, especially for
cross-sectional ranking.

The recommended user disposition is therefore: **authorize drafting a separate locked ML
plan only if the first gate is data-feasibility remediation and the final verdict remains
reserved for evidence on or after 2026-07-27**. This is not a recommendation to authorize
implementation now.

## Decision objective and non-goals

### Objective

Determine whether information available at a completed daily bar can rank a bounded number
of long-only, next-session-open swing opportunities whose **incremental** net outcome remains
positive after friction, relative to activity-, symbol-, and date-matched controls, while
preserving the charter's entry geometry and 15-session hold limit.

The study must answer two separate questions:

1. **Selection skill:** does the score choose better opportunities than causal controls at
   the same dates and trade count?
2. **Economic sufficiency:** do selected opportunities also pass the existing absolute
   event-level and later portfolio success contracts?

Selection skill is necessary but does not replace the success-v2 bars.

### Explicit non-goals

- Do not predict prices for their own sake or optimize a leaderboard metric disconnected
  from tradable net outcomes.
- Do not reopen or reinterpret the Phase 3 STOP.
- Do not promote an old H1/H2/H3 result, use Phase 3 cells as ML labels, or treat prior
  profitable backtests as clean validation.
- Do not optimize stop, target, hold, ranking capacity, feature set, model family, and bucket
  threshold in one search.
- Do not use any bar on or after 2024-01-01 for feature, target, model, threshold, or
  hyperparameter selection; evidence on or after 2026-07-27 is reserved for a later locked
  verdict read.
- Do not fit models, construct labels/features, install packages, collect data, or deploy
  from this memo.
- Do not infer causation. The proposed study is predictive selection under causal data
  availability, not a causal-effect estimate.

## What Phase 3 changes

The locked Phase 3 result is not evidence that ML will work. It is evidence that the
evaluation must remove easy sources of apparent edge.

| Phase 3 fact | ML implication |
|---|---|
| Six rule cells passed absolute event bars | Absolute profitability is an insufficient selection metric |
| All six lost to symbol-matched random sessions | Market drift and symbol activity must be controlled explicitly |
| Event counts ranged from 2,476 to 22,225 | Large row counts do not establish independent information |
| Results share symbols and overlapping dates | Uncertainty must be clustered/blocked by date, not treated as iid trades |
| PEAD was not run because catalyst input was missing | Missing input remains `not_run`; it cannot become a zero or imputed non-event |
| The roster was assembled in 2026 | Historical cross-sectional ranks have survivorship and membership-selection bias |

## Goal alternatives

| Goal | Strength | Main failure mode | Disposition for a future plan |
|---|---|---|---|
| Predict raw h=15 return | Simple and exit-independent | Rewards broad equity drift; repeats Phase 3's false-positive pattern | Negative-control benchmark only |
| Predict absolute net R under fixed geometry | Aligned with trade economics | Can reward active/bull periods and a favorable exit rule | Viable secondary objective |
| Predict control-relative net R | Directly asks whether timing adds value | Control construction can be noisy or encode hidden choices | Strong primary candidate |
| Rank same-date opportunities for fixed top-k capacity | Aligns with the eventual daily queue and slot scarcity | Needs point-in-time universe integrity and grouped evaluation | Strong primary study shape |
| Predict target-before-stop probability | Interpretable classification | Discards payoff magnitude and depends heavily on fixed geometry | Diagnostic only |
| Predict downside-aware value | Incorporates MAE/tail risk | A loss-aversion weight adds another optimizable parameter | Sensitivity, not first primary |

No single row is selected here. A locked plan should name one primary goal and at most one
secondary target before label code exists.

## Research-unit alternatives

| Unit | What one row means | Advantages | Material risks |
|---|---|---|---|
| Symbol-session | Every eligible symbol at one completed session | Broad coverage; supports daily ranking; does not depend on a failed rule detector | Severe overlap, class imbalance, row-count illusion, and roster survivorship |
| Mechanism event | A causal event emitted by a fixed detector | Interpretable; lower overlap; maps cleanly to event simulation | Makes ML conditional on a hand rule and can inherit Phase 3's weak event definitions |
| Date-level cross-section | One group of all eligible symbol-sessions on a date | Naturally aligns with top-k capacity and same-date controls | Independent sample size is closer to number of dates; requires trustworthy historical membership |
| Non-overlapping symbol episode | First eligible session until its 15-session outcome resolves | Reduces overlapping labels and repeated bets | Episode-start rule becomes a selectable detector and suppresses legitimate alternatives |

**Design implication:** a date-grouped symbol-session study is the clearest way to test
selection, but the cross-section—not the individual row—must govern splitting, uncertainty,
and capacity. A future plan could retain symbol-session rows while treating each date as the
grouping unit. That is a proposed architecture, not a locked choice.

## Target alternatives

Every target below must use one fixed, preregistered geometry/cost policy and labels may use
future outcomes only after the causal feature snapshot has been sealed.

| Target | Definition sketch | What it measures | Guardrail |
|---|---|---|---|
| Raw residual h=15 return | Symbol h=15 return minus a same-date benchmark return | Exit-independent relative direction | Also report absolute raw return and regime slices |
| Control-relative net R | Fixed-policy 2×-cost net R minus a matched control's net R | Incremental trade economics | Predeclare control hierarchy and matching tolerance |
| Absolute fixed-policy net R | Net P&L divided by immutable initial risk | Economic magnitude across symbols | Never select on total profit; compare at fixed count |
| Within-date rank/quantile | Rank of a continuous net or residual outcome among eligible names | Cross-sectional ordering skill | Preserve ties, small daily groups, and missing names honestly |
| Binary useful-opportunity label | Positive 2×-cost net R and/or beat-control indicator | Probability of a usable event | Report calibration and continuous economics; do not rely on accuracy |
| Multi-output return/MAE | Predict forward return and adverse excursion separately | Separates upside from path risk | Added complexity must be justified before use |

A robust first plan should not collapse return, net R, MAE, and hit probability into a
hand-weighted composite. It should declare one continuous primary target, keep raw h=15 as an
exit-artifact guardrail, and evaluate top-k realized economics separately.

## Model options

| Model option | Why include it | Interpretability/control | Compute/dependency risk |
|---|---|---|---|
| Regularized linear/logistic model | Hard-to-beat low-variance benchmark; exposes whether additive effects suffice | Coefficient signs, standardized effects, stability by fold | Requires an ML library not currently installed; CPU cost low |
| Shallow histogram/gradient-boosted trees | Captures nonlinear thresholds and a small number of interactions | Depth/leaf limits, feature ablation, fold-stable importance, partial-response checks | Library choice and Python/NumPy/pandas compatibility require an authorized smoke test |
| Date-grouped learning-to-rank challenger | Directly matches within-date ordering | Grouped metrics and top-k behavior are clear; score scale is less interpretable | More specialized objective and higher implementation/audit burden |
| Generalized additive/shape-constrained model | Nonlinear but human-readable univariate shapes | Strong auditability if feature count stays small | Additional dependency and shape-choice degrees of freedom |
| Random forest / extremely randomized trees | Useful nonlinear reference | Weak extrapolation and less compact explanation | Larger memory/runtime; redundant if a boosted challenger exists |
| Neural network | Can learn complex interactions | Weak auditability for this evidence size and decision | Not justified; GPU availability does not create a research need |

No fitted comparison exists, so naming a winning model would be unsupported. The smallest
credible challenger set is one transparent regularized benchmark plus one constrained
boosted-tree family. A ranking objective should be a preregistered alternative, not a late
rescue after pointwise results disappoint.

## Usable data and data-quality walls

### Usable without claiming freshness

- Pre-2024 daily OHLCV: 235 frames and 767,028 rows from 2010-01-04 through 2023-12-29.
- Split/dividend-adjusted price basis and tested OHLCV quality checks.
- SPY/QQQ anchors for market and regime context.
- Existing causal truncation, next-session-open fill, fixed-geometry event simulation,
  both-side friction, MAE, hold, and success-v2 metric contracts.
- Immutable content hashes for the Phase 3 filtered inputs and deterministic study artifacts.

### High-severity gaps before a verdict

1. **Historical universe membership and delistings.** The roster was assembled in 2026 from
   current constituents. It cannot establish which names were knowable/eligible on each
   historical date and omits failed/delisted names.
2. **Point-in-time catalyst facts.** The Phase 3 local earnings cache was absent. A production
   cache existed during Phase 0, but coverage, announcement timing, revisions, and historical
   availability were not certified for ML use.
3. **Data vintages.** Current adjusted histories can be revised for corporate actions. The
   repository validates the current series but does not preserve what a historical run would
   have seen on each date.
4. **Eligibility history.** Price and dollar-volume rules can be reconstructed from bars, but
   index membership, security type, IPO availability, suspensions, and delisting outcomes
   cannot be recovered from the current roster alone.
5. **Dependence and overlap.** A 15-session label creates heavy overlap within symbols and
   across same-date market moves. Row-level random splits and iid confidence intervals are
   invalid.

### Lower-priority limits

- Daily bars cannot resolve intraday ordering when stop and target are both touched.
- No fundamentals, analyst revisions, news text, shares outstanding, borrow, or intraday
  liquidity are present.
- Volume is available, but capacity/slippage beyond the fixed friction model is not directly
  measured.

**Data-quality assessment:** the available evidence is adequate to design a study and build
negative controls, but **needs remediation before an ML result could be treated as a clean
cross-sectional or catalyst verdict**.

## Data-wall options

### Option A — Pre-2024 development plus one fresh forward reveal

- Use only pre-2024 data for nested/rolling development.
- Quarantine 2024-01-01 through 2026-07-26 as consumed historical evidence.
- Lock features, target, folds, model set, search budget, score-to-trade rule, and code before
  any read of evidence on or after 2026-07-27.
- Reveal the fresh event-level window once, then create a later independent portfolio wall
  only for an event-level survivor.

This best preserves the existing clean wall, but requires patience for adequate fresh events.

### Option B — Use 2024–2026 as a non-gating rehearsal

- Complete all selection on pre-2024 data.
- After locking, read the consumed 2024–2026 window once only to test pipeline behavior and
  failure modes.
- Label every result diagnostic/non-promotional; it cannot select or rescue the study.
- Preserve post-2026-07-27 evidence as the first verdict window.

This can find engineering errors sooner but adds analyst exposure without adding clean
evidence. It should be omitted unless a future plan states exactly what it can invalidate and
forbids it from changing the model.

### Option C — Treat 2024–2026 as model validation

Reject for selection. Prior studies already consumed this period, so using it to choose
features, targets, models, or thresholds would rebrand historical exposure as validation.

### Required internal walk-forward behavior

Regardless of option, pre-2024 development must use chronological, purged walk-forward folds:

- split by date, never random rows;
- purge outcome overlap at fold boundaries and embargo at least the 15-session label horizon;
- fit all transforms inside each training fold;
- group evaluation and uncertainty by date, with symbol-level sensitivity;
- keep the final post-wall reader fail-closed until hashes and an independent checklist match.

Exact internal fold dates belong in a later locked plan, not this exploration memo.

## Controls and evaluation

### Required negative and reference controls

1. Same-date random top-k from the exact eligible cross-section, repeated with fixed seeds.
2. Symbol-matched random-session control retained for comparability with Phase 3.
3. Simple causal baselines: market/sector-relative momentum, volatility, and activity-only
   ranks, each fixed before the ML run.
4. Label permutation within date blocks to preserve cross-sectional shape while destroying
   feature relation.
5. Noise-feature canaries and feature-availability assertions; any post-outcome canary that
   survives the causal boundary is a hard STOP.
6. Constant-score/equal-score behavior to prove tie handling and capacity are deterministic.

### Primary evaluation principles

- Compare every model and control at the **same eligible dates and selected count**.
- Judge mean incremental 2×-cost net R and its date-blocked uncertainty, not realized total
  profit alone.
- Also report absolute base/2× net profit, raw h=15 return, n, unique dates, effective date
  concentration, MAE, hold, profit factor, and win/loss distributions.
- Report top-k lift curves only at preregistered capacities; never choose k from the best
  realized profit.
- Slice by year, SPY regime, liquidity, score bucket, model version, and data-coverage state.
- Show whether results depend on a few dates, symbols, sectors, or high-volatility episodes.
- Require fold-to-fold sign/stability and feature-direction stability; a pooled win cannot
  hide repeated fold losses.
- Preserve the existing absolute success-v2 event gate. Incremental lift does not excuse
  invalid geometry, negative 2×-cost profit, excessive hold, or non-positive raw h=15 return.

### Search and multiplicity controls

- Predeclare a small feature dictionary tied to economic mechanisms and availability times.
- Cap the number of model families, hyperparameter configurations, targets, and top-k values.
- Use nested walk-forward selection; never report inner-fold scores as final evidence.
- Record every attempted configuration and failure append-only.
- Select on a normalized incremental metric with adequacy floors, not total dollars or trade
  count.
- Permit one final holdout reveal. Any post-reveal change creates a new version and new future
  wall; it cannot reread the same holdout as clean.

## Compute and dependency options

The current workstation exposes 20 logical CPUs, 23 GiB RAM, and an RTX 5070 Ti with 16 GiB
VRAM. The repository uses Python 3.12 and currently has NumPy 2.5.1, pandas 3.0.5, and
pyarrow 25.0.0. SciPy, scikit-learn, XGBoost, LightGBM, CatBoost, SHAP, and Optuna are not
installed, and the repository has no dependency lockfile.

| Option | Expected cost on the current evidence scale | Risk |
|---|---|---|
| CPU regularized baseline | Low; expected minutes per bounded walk-forward study | Library installation/version pinning still required later |
| CPU shallow boosted trees | Low to moderate; expected minutes to low hours for a tightly capped fold/config set | Thread oversubscription and library/ABI compatibility |
| GPU boosting | Unnecessary for the first study | Adds CUDA/platform variability without solving a statistical constraint |
| Neural/GPU stack | High complexity relative to likely value | Reproducibility, dependency size, and auditability |
| Point-in-time data acquisition | Potentially the dominant time and monetary cost | Vendor coverage/licensing and historical membership quality are unknown |

These are order-of-magnitude planning estimates, not benchmarks. No runtime was measured and
no dependency compatibility was tested in this session. A later authorized plan should
isolate ML dependencies, pin them, add a lockfile, and run a minimal import/serialization
compatibility gate before any label or feature work.

## Robustness and independent review gates

A future locked plan should require review before each irreversible evidence step:

1. **Data review:** point-in-time membership, adjustment basis, catalyst timing, delistings,
   missingness, and coverage states.
2. **Causality review:** each feature's source, availability timestamp, lookback, and
   transform-fitting scope.
3. **Label review:** entry timing, geometry, ambiguous-bar handling, costs, overlap, and raw
   h=15 companion.
4. **Split review:** chronological grouping, purge/embargo, transforms, effective sample
   size, and fold hashes.
5. **Search review:** finite model/target/config budget and append-only attempt registry.
6. **Pre-reveal review:** code/config/data hashes, controls, adequacy floors, and fail-closed
   holdout reader.
7. **Post-reveal review:** independent reproduction and a rubric-mapped
   PROCEED/PARK/STOP decision before any portfolio expression.

## Recommendation and decision required

ML is not ruled out by Phase 3, but a naive classifier or return regressor would be more
likely to rediscover the same drift than to establish selection skill. The credible path is
to make **control-relative, fixed-capacity daily selection** the organizing question, keep
the model set deliberately small, remediate point-in-time data risks first, and reserve
post-2026-07-27 evidence for a one-time event-level verdict.

Choose one disposition:

- **AUTHORIZE PLAN DRAFTING:** create a separate locked, append-only ML implementation plan
  with data feasibility as its first gate. This authorizes planning only unless the new plan
  separately states and receives implementation authorization.
- **REVISE:** specify which objective, unit, target, data source, wall, or control should
  change; update this exploration history without rewriting prior entries.
- **PARK:** retain this memo as historical exploration and do no ML planning.
- **REJECT:** record that the project will not pursue the ML restart.

Until the user explicitly selects a disposition, Phase 3 remains **STOP**, Phase 4 remains
unauthorized, and no ML plan or implementation may be created.

## Sources and limitations

Primary repository sources:

- [Restart plan](../../PLAN.md)
- [Phase 3 evidence](phase-3.md)
- [Phase 3 discovery artifact](../../../runs/success-v2/phase3/discovery.json)
- [Phase 3 screen config](../../../configs/success_v2_phase3.yaml)
- [Success contract](../../SUCCESS_GATE.md)
- [Project charter](../../VISION.md)
- [Dependency declaration](../../../pyproject.toml)

The user-referenced report **“Rule Screens and ML Study Options”** was not present in the
repository, accessible upload paths, or a connected document session during this work. No
claim in this memo is attributed to that unavailable report. Its absence is a source
limitation; if supplied later, it should be reconciled with this memo before a locked plan is
drafted.

No price parquet, catalyst cache, post-Phase-3 market data, fitted model, generated feature,
constructed label, package installer, or network data source was opened or run in this
session.

## Disposition record (append-only)

- 2026-07-26 — User selected **AUTHORIZE PLAN DRAFTING**.
- Locked plan: `docs/superpowers/plans/2026-07-26-ml-restart.md`.
- Locked development prereg:
  `docs/preregs/2026-07-26_ml-restart-development.md`.
- Planning authorization does not authorize implementation. Phase 3 remains
  STOP and Phase 4 remains unauthorized.
