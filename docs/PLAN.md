# ML-v2 Profitability-First Research Plan

- **Created:** 2026-07-28 (America/Los_Angeles)
- **Status:** GATE 1 COMPLETE; GATE 2 NOT AUTHORIZED
- **Study identity:** `ml-v2`
- **Planning package:** `docs/evidence/ml-v2/`
- **Archived predecessor plans:** `docs/archive/pre-ml-v2-2026-07-28/`

This is a new, independent study. It does not continue the stopped
`ml-restart` line, reopen Success-v2 Phase 3, amend the locked ML Task 5
**STOP**, promote A-T1-M3, or authorize Task 6. Prior results are design
evidence only.

## Objective and success unit

The objective is realizable long-only portfolio profitability after
conservative doubled friction. Development evaluates complete executable
setups through one cash-, slot-, and capacity-constrained simulator. It may
freeze zero to three setups for a later genuinely prospective forward test.

A setup is indivisible: point-in-time universe, signal, score, entry, stop,
target, time and exit rules, sizing, allocation, concurrency, daily throttle,
liquidity, capacity, costs, gaps, and rejected fills all share one canonical
identity. A score or model without the rest of that specification cannot be
selected.

The primary measure is `NROCC_2x`, net return on committed capital at doubled
friction:

`NROCC_2x = sum(closed_trade_net_pnl_2x) / sum(entry_fill_notional)`.

The numerator includes every accepted trade in the simulated portfolio,
including forced terminal liquidations and conservative delisting treatment.
The denominator is the sum of executed entry notional (`shares × entry fill`)
for those trades; rejected or unfilled orders contribute zero to both. Capital
may be reused only after it is released by the simulator.

Exact setup cells, metrics, gates, controls, inputs, and simulator behavior are
locked in:

- `docs/evidence/ml-v2/setup-matrix.md`;
- `docs/evidence/ml-v2/development-preregistration.md`;
- `docs/evidence/ml-v2/research-contract.md`.

## Authorization model

Only the current gate may be authorized. Passing a gate does not authorize the
next gate. Every gate ends with evidence, deterministic hashes, review, and an
append-only entry below.

### Gate 0 — Planning and preregistration

Authorized by the 2026-07-28 request:

- archive the predecessor governing plan, ML implementation plan, and ML
  development preregistration;
- create the independent `ml-v2` package;
- lock the six-cell candidate matrix, metrics, controls, gates, input
  contract, simulator contract, artifact contract, estimates, forward
  template, and STOP conditions;
- review documentation only.

**Prohibited:** reading any new market or source data, collecting data,
implementing research code, fitting a transform or model, executing a
development simulation, setting a prospective wall, starting a forward test,
deploying, or changing any earlier verdict.

**Gate:** the documents are internally consistent and reviewable. End and ask
for explicit Gate 1 authorization.

### Gate 1 — Pure contracts and synthetic simulator

Authorized by the 2026-07-28 user request and completed:

- implement canonical setup/config identities;
- implement the cash/slot/capacity simulator and exact metric/control
  contracts against hand-calculated and synthetic fixtures only;
- implement fail-closed interfaces for point-in-time inputs without opening
  market datasets;
- implement leakage, capital-reuse, tie, gap, delisting, rejected-fill,
  crash/retry, and doubled-friction tests;
- prove byte-identical synthetic reruns.

**Gate:** all hand calculations, property tests, synthetic canaries, focused
tests, full tests, lint, and diff checks pass. No market or vendor dataset was
opened.

Evidence: `docs/evidence/ml-v2/gate-1.md`.

### Gate 2 — Source acquisition and point-in-time certification

Requires separate explicit authorization because it permits source discovery,
procurement, and data reads. Build a manifest for the required point-in-time
security master, membership, security type, symbol mapping, delistings,
corporate actions, OHLCV, earnings schedule, benchmark, and exchange calendar.
Run only the locked fail-closed quality checks.

**Gate:** every critical source is certified, content-addressed, and adequate,
or record `STOP_INPUT`. A survivor-only substitute cannot pass.

### Gate 3 — Walled development dataset

Requires separate authorization. Materialize only the preregistered
development interval and folds, using the Gate 2 manifest. Build causal
features, fixed outcomes, event pools, controls, and deterministic row
identities. Do not fit models.

**Gate:** wall, as-of, membership, delisting, coverage, leakage, join,
missingness, and deterministic rebuild checks pass, or STOP.

### Gate 4 — Bounded development execution

Requires separate authorization. Fit and evaluate exactly the six locked
setups, their fixed same-date baselines, 200 random-ranking controls per fold,
and 999 synchronized local permutations. Run the slot/capital simulator for
every real and control arm. No cell, feature, threshold, model, fold, or
simulator rule may be added or changed.

**Gate:** apply all preregistered gates mechanically. Produce the full
development record and an independent methodology review.

### Gate 5 — Deterministic top-three freeze

This is part of Gate 4 only if at least one setup clears every gate. Rank only
clearing setups by the locked rule and freeze at most three. If none clear,
record STOP. If fewer than three clear, freeze only those. Never promote a
least-bad setup.

For each selected setup freeze:

- source commit and clean-tree patch hash;
- canonical setup/config;
- data manifest and source hashes;
- feature schema and fold definitions;
- fitted preprocessing/model artifact, if any;
- simulator version;
- selected identities and reviewed report;
- one root identity hash over all preceding hashes.

No substitution, retuning, replacement, or refit is allowed after freeze.

### Gate 6 — Prospective preregistration completion and wall lock

Requires new explicit authorization after Gate 5. Instantiate
`docs/evidence/ml-v2/forward-test-preregistration-template.md` for the frozen
roster, implement and rehearse only with synthetic and development-period
inputs, independently review exact code/config/data/model hashes, then set the
first eligible future exchange session as the prospective wall. The wall is
deliberately unset now.

**Gate:** preregistration, collector, simulator, artifacts, hashes, and wall are
committed before any on/after-wall row is read.

### Gate 7 — Prospective forward test

Requires separate authorization. The scheduled prospective process is the
first reader/writer of on/after-wall evidence. No backfill, retuning,
substitution, or candidate replacement. Development artifacts and forward
evidence remain in disjoint namespaces.

**Gate:** the locked minimum observation floors are met or the maximum
observation window expires. Produce the preregistered result without changing
the roster or rubric.

### Gate 8 — Forward verdict

Independently reproduce identities and metrics, then record each frozen
setup's rubric result. A portfolio can proceed only under the forward
preregistration; development success alone is not promotion authority.
Deployment or live-money work would require a separate plan and authorization.

## Global STOP conditions

Stop the active gate immediately and write an immutable failure record if:

- work begins without explicit authorization for that gate;
- any new market/source data is opened during Gate 0 or 1;
- a critical input lacks certified point-in-time membership, security type,
  delisting, or corporate-action history;
- a survivor-only roster is silently substituted;
- any row crosses a locked development or prospective wall;
- a feature, transform, rank, order, or outcome uses unavailable future facts;
- overlapping positions reuse cash, risk, a slot, or notional;
- an equal-score path falls through to symbol or alphabetical order;
- geometry, sizing, costs, gaps, rejected-fill handling, folds, controls,
  gates, or candidates change after evidence is read;
- a non-preregistered arm or open-ended search is attempted;
- any selected setup fails a required gate or a credible local permutation
  exists;
- family multiplicity is reinterpreted after results;
- a rerun identity differs without an explained, reviewed input change;
- evidence is backfilled, overwritten, omitted, or mixed with predecessor or
  forward namespaces;
- a frozen setup is substituted, retuned, refit, or replaced;
- a failed result is relabeled or a least-bad setup is promoted.

## Append-only execution log

- 2026-07-28 — Gate 0 planning package created and reviewed under planning-only
  authority. No new market data was read, no implementation or fitting
  occurred, no prospective wall was set, and the ML Task 5 STOP remains
  unchanged. Gate 1 is proposed but not authorized.
- 2026-07-28 — Gate 1 explicitly authorized and completed. Pure contracts,
  canonical identities, metrics, controls, and the synthetic portfolio
  simulator passed focused, full-suite, lint, property, crash/retry, and
  byte-identity checks. No market or vendor dataset was opened, no transform
  or model was fitted, and no run directory was created. Gate 2 remains
  unauthorized.
