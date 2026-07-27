# Success-v2 Phase 2 — versioned research/live boundary

- Completed: 2026-07-26 (America/Los_Angeles)
- Starting commit: `d6d330d` (`feat: add success-v2 metric gate`)
- Data-wall statement: implementation used synthetic frames ending
  2023-12-29. A causal test supplied a 2024-01-02 future row and proved the
  EOD candidate source received data only through its 2023-12-29 `asof`.
  No real bar or catalyst data was read.

## Boundary implementation

- Legacy identities, schema-1 rows, and the original `ledger/` root remain
  readable. Legacy writes remain unversioned so already-open synced
  positions can continue through upkeep and exit; the Phase-0 entry/fill
  wall is unchanged.
- `LedgerPaths.success_v2(version)` resolves only to
  `ledger/success-v2/<version>/`. Versioned rows cannot be written to the
  legacy root, and unversioned/cross-version rows cannot be written to a
  success-v2 root.
- The immutable `strategy_version` is present in candidate, signal,
  fill/position, equity-summary, completion-summary, sync-key, and
  deterministic-entry-identity contracts. A versioned identity begins
  `sv2|<version>|`, so it cannot collide with a frozen legacy identity.
- Success-v2 sync resolves only to
  `success-v2/<version>/{h1,h2,equity,signals}.jsonl` beneath the remote
  forward folder. Every local and downloaded row is version-checked before
  merge or upload. Merge remains append-only.
- Candidate rows carry explicit `stop_atr_multiple` and
  `target_atr_multiple` facts. The fill path re-anchors both levels at the
  actual session open, recomputes planned R and initial-risk percentage,
  and accepts only strict `planned_r > 1.5` and strict charter risk below
  12% (therefore also below 25%). It never changes the candidate stop
  multiple.
- A failed actual-open check appends `geometry_reject`, including the open,
  computed levels, metrics, and exact reason. It creates no position row.
- Versioned lifecycle timestamps derive from event/session facts rather
  than retry wall-clock time. Interrupted and uninterrupted EOD signal
  walks produced byte-identical journals at three injected crash points.

## Verification evidence

- Focused Phase-2 contract suite: `12 passed`.
- Forward subsystem suite: `162 passed`.
- Full repository suite: `396 passed in 11.63s`.
- Strict tests cover exact 1.5R rejection, exact 12% rejection, valid 2R
  acceptance, durable rejection, actual-open parity, namespace collision
  refusal, frozen legacy readability, future-bar truncation, and
  byte-identical retry.
- Full `ruff check .` improved the recorded repository baseline from 152 to
  137 findings because safe formatter fixes were applied to touched files;
  Phase-2 core and tests pass targeted lint.
- `git diff --check` passed. Locked `runs/` artifacts and all historical
  preregs were unchanged.

## Phase gate

**PASS.** Legacy ledgers remain readable and were not rewritten;
success-v2 local and remote namespaces are structurally disjoint; explicit
candidate geometry is revalidated at the actual open; rejects are durable;
retry is byte-identical; and EOD selection requires no future bar. No
collector was deployed or enabled.
