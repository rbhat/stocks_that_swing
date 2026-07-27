# Success-v2 Phase 1 — strategy-agnostic success gate

- Completed: 2026-07-26 (America/Los_Angeles)
- Starting commit: `8d7484a` (`ops: freeze legacy forward entries`)
- Artifact schema: `success-v2.phase1`
- Data-wall statement: implementation and verification used hand-built and
  seeded synthetic facts only. No real price or catalyst data was read in
  Phase 1, so no evidence beyond an allowed wall was accessed.

## Implementation evidence

`sts.study.success_gate` is pure and performs no I/O. It adds:

- actual-fill `initial_risk`, `planned_r`, and `initial_risk_pct`;
- strict boundaries: 1.5R fails, 25% risk fails, and the existing 12%
  charter boundary also fails;
- closed-event count and adequacy, base/2× net dollar profit, win/loss
  counts and distributions, profit factor, hold distribution, MAE in R,
  both-side friction, and raw h=15 return;
- portfolio net return, peak-to-trough drawdown, average deployed capital,
  and fill-geometry validation;
- a deterministic circular blocked bootstrap whose replicates match both
  the forward book's elapsed-session count and exact closed-trade count;
- explicit `not_run`, `inadequate`, `invalid_geometry`, and `evaluated`
  states. Missing evidence remains missing and is never treated as zero.

`build_success_artifact` returns a JSON-safe metrics section for new,
versioned study reports. The consumed files under `runs/` were not changed
or regenerated.

## Verification evidence

- Hand-calculated geometry, event-economics, drawdown, deployment, and
  constant-return bootstrap cases passed.
- Exact 1.5R, 25%, and 12% boundary cases passed.
- Seeded property checks covered 500 valid random geometries plus drawdown
  bounds and scale invariance.
- A 5,000-event antithetic random-entry negative control had exactly zero
  gross mean and negative base/2× net profit after friction, with profit
  factor below one and worsening at 2× costs.
- Focused Phase-1 suite: `16 passed in 2.21s`.
- Full repository suite: `384 passed in 11.70s`.
- New implementation and tests: `ruff check` passed.
- Full-repository lint remained at the Phase-0 baseline of 152 pre-existing
  findings; no new finding was introduced.
- `git diff --check` passed.

## Phase gate

**PASS.** The metrics exist before any success-v2 strategy, required unit,
property/boundary, and negative-control tests pass, the full suite is green,
and locked historical reports remain unchanged. No collection or deployment
was attempted. Phase 2 is the next authorized phase.
