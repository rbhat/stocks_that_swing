# Swing-v1 Practical Swing-System Plan

- **Created:** 2026-07-28 (America/Los_Angeles)
- **Status:** GATE 0 COMPLETE; GATE 1 NOT AUTHORIZED
- **Study identity:** `swing-v1`
- **Governing charter:** `docs/VISION.md`
- **Planning package:** `docs/evidence/swing-v1/`
- **Historical ML-v2 plan:** `docs/PLAN.md`

## Scope

Build the simplest deterministic daily-data system that can identify, size,
simulate, and prospectively paper-trade 3–15-session long swing setups.

This project accepts the repository's Yahoo-derived, current-roster,
split-and-dividend-adjusted parquet cache for retrospective screening. It does
not require institutional point-in-time membership, permanent-ID, delisting,
corporate-action, or historical earnings-revision datasets.

That practical choice narrows the claims:

- retrospective results are survivor-biased screening evidence, not proof of
  a deployable edge;
- adjusted historical prices are simulation units, not reconstructable raw
  executions;
- the current roster says nothing about names absent from today's cache;
- no retrospective period is called genuinely untouched OOS; and
- only a preregistered forward paper book can qualify a setup for continued
  paper operation.

ML-v2's `STOP_INPUT`, source manifest, and all predecessor verdicts remain
historical facts. Swing-v1 does not amend or resume them.

## Fixed system roster

Swing-v1 evaluates exactly two human-readable deterministic setups:

1. `SV1-P` — trend pullback;
2. `SV1-B` — compression breakout.

Their exact signals, ranking, execution, risk, and cost rules are locked in
`docs/evidence/swing-v1/setup-contract.md`. There is no ML, feature search,
parameter sweep, ensemble, or third setup.

Each setup is simulated as a complete portfolio on a fresh `$100,000` book
with the charter's 0.75% risk, 15% position cap, eight slots, 80% gross cap,
long-only rule, 15-session time stop, and doubled friction.

## Evidence hierarchy

1. **Synthetic correctness:** simulator, accounting, ties, gaps, missing bars,
   cash, slots, and replay invariants.
2. **Retrospective screen:** fixed-rule performance on the accepted local
   cache, with survivor and adjusted-price caveats on every artifact.
3. **Prospective paper evidence:** first post-freeze reader of future bars,
   with no backfill or retuning.

Retrospective profitability may qualify one setup for a forward paper test.
It cannot qualify live money, deployment, or an edge claim by itself.

## Sequential authorization

Only the current gate may be authorized. Passing a gate does not authorize the
next one.

### Gate 0 — Scope and preregistration

Authorized by the user's 2026-07-28 requests to use the practical project
scope, build the swing system, and change scope.

- preserve ML-v2 and predecessor evidence;
- lock the two setups and complete portfolio policy;
- accept and bound the existing Yahoo cache;
- lock the screening interval, metrics, controls, selection rule, forward
  role, artifacts, and STOP conditions;
- update active repository handoffs.

**Gate:** documentation is internally consistent and does not relabel prior
results or claim the accepted cache is point-in-time. Stop before reading
price values or implementing Swing-v1.

### Gate 1 — Cache freeze, adapter, and simulator

Requires explicit authorization.

- inventory and content-address the actual parquet files;
- freeze the usable symbol intersection and `<2026-01-01` screening slice;
- validate schema, dates, duplicates, OHLCV, missingness, and SPY coverage;
- implement the adjusted-price input adapter;
- adapt the deterministic Gate 1 event-sourced simulator to the Swing-v1
  charter without changing ML-v2 code or identities;
- implement both setup detectors and ranking;
- pass hand-calculated, synthetic, crash/retry, and byte-identity tests.

No retrospective performance summary or selection is allowed in Gate 1.

**Gate:** deterministic cache manifest and all adapter/simulator tests pass,
or record `STOP_INPUT`/`STOP_SIMULATOR`.

### Gate 2 — Bounded retrospective screen

Requires separate authorization.

- execute exactly `SV1-P` and `SV1-B`;
- execute 200 preregistered same-date random-ranking controls per setup;
- produce complete portfolio trades, rejections, daily equity, era tables,
  metrics, uncertainty, concentration, and limitation disclosures;
- run twice from the frozen inputs and reproduce every identity.

**Gate:** apply the locked screening gates mechanically. Freeze zero or one
setup as forward-paper eligible. None is a valid `STOP`; never promote a
least-bad setup.

### Gate 3 — Forward-paper freeze and wall

Requires separate authorization only if Gate 2 selects one setup.

- freeze source commit, clean patch, setup, roster, adapter, simulator, costs,
  and all identities;
- complete a prospective paper preregistration;
- rehearse on synthetic inputs only;
- set the first future eligible exchange session after the committed freeze
  as the wall.

The forward process applies the charter's two-session scheduled-earnings
entry veto using information fetched contemporaneously. Historical screening
does not pretend to reconstruct that unavailable schedule.

### Gate 4 — Prospective paper operation

Requires separate authorization.

- append future decisions, orders, fills/rejections, positions, and equity;
- no backfill, tuning, setup replacement, or wall crossing;
- continue until at least 30 closed trades and three calendar months have
  elapsed.

### Gate 5 — Forward verdict

Independently reproduce the paper ledger and compare realized net return with
the preregistered retrospective band at matched trade count.

- `CONTINUE_PAPER` only if every forward gate passes;
- otherwise `STOP`;
- real money always requires a new plan and explicit authorization.

## Global STOP conditions

Stop the active gate and record the result if:

- work begins without authorization for that gate;
- ML-v2 evidence is overwritten, reinterpreted, or mixed into Swing-v1;
- a third setup, threshold variant, model, feature search, or ensemble is
  added;
- a cache limitation is hidden or a retrospective result is called
  point-in-time, unbiased, or genuinely prospective;
- rows on or after the locked screening end feed retrospective selection;
- future facts enter a signal, rank, order, or retrospective feature;
- equal scores fall through to alphabetical/symbol order;
- cash, slots, gross exposure, risk, or daily entries are reused;
- costs, geometry, sizing, folds, controls, or gates change after results;
- a rerun identity differs without a reviewed input change;
- forward rows are read before the committed wall;
- a failed or unqualified setup is promoted; or
- evidence is overwritten or backfilled.

## Append-only execution log

- 2026-07-28 — Gate 0 authorized and completed. Swing-v1 replaced ML-v2 as
  the active project scope without altering ML-v2's `STOP_INPUT`. The
  practical Yahoo/current-roster limitation, two deterministic setups,
  charter portfolio, retrospective screening claims, and forward-paper
  authority were locked. No price values were read for Swing-v1, no code was
  implemented, no retrospective screen was run, and Gate 1 remains
  unauthorized.
