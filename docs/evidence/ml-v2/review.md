# ML-v2 Planning Review

- **Review date:** 2026-07-28 (America/Los_Angeles)
- **Scope:** documentation and preregistration only
- **Result:** PASS WITH IMPLEMENTATION STILL UNAUTHORIZED

## Evidence reviewed

- `docs/reports/ml-task5-diagnostics/report.html`;
- `runs/ml-restart/development/task5-diagnostics.json`;
- `docs/evidence/ml-restart/phase-4.md`;
- archived predecessor `docs/PLAN.md`;
- `decisions.md`.

No market dataset, price frame, catalyst cache, membership source, or
post-plan evidence was opened.

## Task 5 lesson mapping

| Required lesson | ML-v2 lock |
|---|---|
| Profitability is across all trades | `NROCC_2x`, total net P&L, and ending equity include every accepted/terminally liquidated portfolio trade |
| Capital cannot be reused by overlaps | atomic cash/risk/slot reservation in one event-sourced simulator |
| Remove survivor-only construction | certified point-in-time security master, listings, security types, delistings, and corporate actions are fatal input requirements |
| No alphabetical equal-score tie | permanent-ID hash tie-break; symbols never sort scores |
| Valid baselines | 200 seeded random ranks, fixed momentum/pullback/activity ranks, and a separately scoped equal-weight ownership benchmark |
| Local permutations and justified family rule | 999 setup-local reruns plus synchronized Westfall–Young maxT at family alpha 0.05 |
| Preserve causal controls | fold-local transforms, purge, embargo, leakage/wall canaries, deterministic identity, and doubled friction |
| Development/forward separation | distinct gates, walls, roots, ledgers, identity domains, and no post-freeze substitution |

## Deliverable review

| Requested deliverable | Location | Status |
|---|---|---|
| Archive active plan documents | `docs/archive/pre-ml-v2-2026-07-28/` | PASS; three predecessor authorities byte-preserved with SHA-256 |
| New append-only gated plan | `docs/PLAN.md` | PASS |
| Development preregistration | `development-preregistration.md` | PASS |
| Forward-test preregistration template | `forward-test-preregistration-template.md` | PASS; wall/roster unset |
| Bounded setup/model matrix | `setup-matrix.md` | PASS; exactly six cells, no search |
| Metrics, formulas, controls, multiplicity, gates | development preregistration + `research-contract.md` | PASS |
| Data requirements and fail-closed checks | `research-contract.md` | PASS |
| Portfolio simulator requirements | setup matrix + `research-contract.md` | PASS |
| Deterministic artifacts and audit | `research-contract.md` | PASS |
| Runtime and storage estimates | `research-contract.md` | PASS |
| Explicit STOP conditions | `docs/PLAN.md` + `research-contract.md` | PASS |

## Consistency checks

- Primary denominator is executed entry-fill notional everywhere.
- Judged path is doubled friction everywhere; base costs are diagnostic.
- Development folds start with separate cash and pool to a `$5M` accounting
  base without concatenating their CAGR paths.
- Same-date controls use identical opportunity pools and simulator rules.
- Equal-weight ownership is explicitly contextual because it has a different
  mandate.
- Drawdown cap is 25%; adequacy is 300 trades, 150 entry dates, and four
  minimally populated folds.
- Short-period profits and yearly signs are allowed as diagnostics, not
  selection shortcuts.
- Exactly zero to three all-gate-clearing setups may freeze.
- Freeze includes code, config, data manifest, model where applicable,
  simulator, report, component hashes, and root identity.
- The prospective wall is `[UNSET]` and can be set only after a later
  authorization and review.
- `git diff --check` passed after drafting.

## Remaining pre-execution risks

The design intentionally fails closed if a vendor-quality point-in-time
security master, delisting history, corporate actions, or earnings
announcement history cannot be certified. Availability and cost are unknown
because source discovery/data access was prohibited. The permutation workload
is also material; planning reserves up to 2,000 CPU-hours and 500 GB scratch.
Neither risk permits substituting survivor-only inputs, reducing controls, or
expanding/tuning the six-cell matrix after data access.

## Authority conclusion

Gate 0 is complete. Gate 1 is the first proposed implementation task: pure
canonical contracts, metrics, controls, identities, and a synthetic
cash/slot/capacity portfolio simulator. It may not open market data, fit a
market model, create a development run, set a wall, collect evidence, or
deploy. Explicit user authorization is required.
