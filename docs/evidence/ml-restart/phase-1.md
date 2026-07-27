# ML restart Phase 1 — causal research contracts

- Completed: 2026-07-27 (America/Los_Angeles)
- Starting commit:
  `7a49602` (`build: lock bounded ML research dependencies`)
- Initial `git status --short`: empty
- Implementation authorization: Task 2 only

## Red baseline

The five synthetic Task 2 test modules were created before `sts.ml`
existed. The first focused run failed during collection with five
`ModuleNotFoundError: No module named 'sts.ml'` errors. No source data was
opened to create the tests.

## Implemented contracts

All Task 2 modules are pure. They accept explicit dates, exchange sessions,
bars, feature facts, and unit facts; they have no path, parquet, cache,
network, loader, or implicit calendar fallback.

- `contracts.py` rejects non-finite or ambiguous canonical config values,
  normalizes track/symbol keys, hashes a versioned canonical JSON envelope,
  creates deterministic Track A/B row identities, and implements the exact
  preregistered SHA-256 noise formula.
- `walls.py` enforces
  `2010-01-01 <= development_session < 2024-01-01`, refuses fresh reads
  until an actual event wall on or after 2026-07-27 is supplied, and
  performs offsets/windows only against a caller-supplied strictly ordered
  exchange-session sequence.
- `units.py` fail-closes every missing eligibility fact, enforces the
  300-bar, $5 close, $20M trailing-dollar-volume, next-open, geometry, and
  complete-label requirements, groups Track A by signal session, records
  inadequate cross-sections, and deduplicates Track B's six exact detector
  streams while preserving sorted provenance.
- `features.py` locks 34 OHLCV/SPY features for both tracks plus six binary
  detector flags for Track A only. Each feature has a causal source,
  lookback, signal-close availability, and explicit formula. A snapshot
  requires 300 causal sessions and every named feature fact; absent facts
  fail, non-finite values remain missing, and facts available after the
  signal close are rejected.
- `labels.py` implements next-session-open entry, causal ATR14, 2×ATR stop,
  4×ATR target, strict actual-fill geometry, stop-first ambiguous-bar
  resolution, gap fills, a hard 15-session time stop, raw h=15 return, base
  and 2× friction, and targets T1 `relative_net_r_2x`, T2
  `spy_residual_h15`, and T3 `useful_opportunity`.

Canonical fixture values locked by tests:

- config `{"model":"M1","target":"T1"}`:
  `1450ca228e5a3c6d8605fe59c7d9c53564c29f4aea7464dbbb10bd2c06ed75fc`;
- Track A row `(AAPL, 2023-12-29)`:
  `ml-row-v1:ea218b1451e0844d3b80589dcca53d350055e771b36054c26df0c03a449f89e6`.

## Canary evidence

- A row dated exactly 2024-01-01 and a 2026-07-27 post-development canary
  both raise `WallViolation`; bounds are not clipped or filtered silently.
- A fresh row cannot be evaluated when the actual event wall is absent,
  predates 2026-07-27, or is later than the row.
- A known feature stamped one session after the signal raises
  `FutureFeatureViolation`.
- An unknown `future_h15_return` feature and an omitted locked feature fact
  both raise `ContractViolation`; neither can enter a snapshot.
- Missing and infinite feature values remain explicit `None` values and are
  listed in the snapshot's missing tuple; they are never encoded as zero.

## Verification

- Focused synthetic contracts:
  `25 passed in 3.04s`.
- Final frozen-lock full suite:
  `426 passed in 12.25s`.
- Task 2 source/tests:
  `ruff check --fix` passed under Ruff 0.16.0.
- Repository-wide `ruff check --fix .` found the established 135 legacy
  findings: 104 were automatically fixable and 31 remained. The unrelated
  mechanical edits were discarded; Task 2's scoped lint remains clean.
- `git diff --check`: passed.

## Phase gate

Gate: **PASS**. Synthetic wall, session, unit, feature, label, target,
identity, missingness, cost, geometry, and ambiguity contracts pass. No
price parquet, catalyst cache, ledger, run artifact, or real-data ML source
was read; no transform or model was fitted; and no Task 3 data module,
builder, test, or development artifact was created.
