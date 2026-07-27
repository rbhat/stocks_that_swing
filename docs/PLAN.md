# Restart Plan — Success-v2

- **Locked:** 2026-07-26
- **Canonical plan:** this file
- **Clean OOS wall:** 2026-07-27
- **Starting code baseline:** the repository state immediately before this plan's commit

## Restart decision

This is a strategic restart, not a continuation of the Phase-5 no-signals repair.

- All pre-restart H1/H2/H3 studies, Phase-4 verdicts, and the Phase-5 forward prereg are
  retained as historical context only. None authorizes a new entry or promotion.
- Existing data, calendar, store, risk, event simulator, portfolio simulator, append-only
  journal, causal signal-selection, retry, and observability code may be reused only after
  it passes the gates below.
- No old setup is grandfathered. H1/H2 may reappear only as newly named candidates selected
  without using consumed OOS results.
- No production entry generation, retrospective paper fills, dashboard work, or live-money
  work occurs until this plan explicitly permits it.
- Every phase ends with tests, evidence, and one focused commit. Do not carry uncommitted
  work into the next phase.

## Success contract

The following definitions are load-bearing:

- `initial_risk = entry_fill - stop_initial`
- `planned_r = (target_initial - entry_fill) / initial_risk`
- `initial_risk_pct = initial_risk / entry_fill`
- `net_profit = sum of closed-trade P&L after both-side friction`
- `matched OOS band = 90% blocked-bootstrap interval of net portfolio return, sampled at the
  forward book's closed-trade count and elapsed-session count`

A setup family succeeds only if all event-level bars pass:

1. At least 100 closed events strictly on or after the clean OOS wall.
2. Planned reward:risk is strictly greater than 1.5R on every valid entry.
3. Initial stop risk is below 25% of entry on every valid entry. The existing 12% stop bound
   remains stricter and may not be loosened.
4. Total net profit is positive at base and 2× assumed friction.
5. Median hold is at most 15 sessions.
6. Raw h=15 forward return is positive; exit logic cannot manufacture the entire edge.

A portfolio expression succeeds only if:

- net return is positive after friction;
- max peak-to-trough drawdown is at most 40%;
- average deployed capital is at least 10%;
- every actual/modelled fill still satisfies planned R >1.5 and initial risk <25%;
- year, regime, exit-reason, net-R, MAE, and friction distributions are reported.

Forward promotion is a second, later holdout. It starts only after an event-level PROCEED and
additionally requires at least 30 closed trades and three calendar months, with realized net
return positive and inside the matched event-OOS band. A profitable realized time-stop exit
below 1.5R is reported honestly; the 1.5R rule is entry-time planned geometry, not a post-hoc
relabeling of outcomes.

## Phase 0 — Freeze and baseline

1. Record the restart commit SHA and `git status --short`.
2. Inspect local and production state read-only:
   - identify any active cron/container;
   - identify open legacy paper positions and queued legacy candidates;
   - record image digest, ledger roots, last completed stages, and last sync.
3. If legacy entry generation is active, disable new entries while preserving upkeep, exits,
   notifications, and append-only sync for already-open paper positions.
4. Never fill a queued legacy candidate after the restart wall.
5. Run the full local suite and repository lint baseline. Record all pre-existing failures
   before changing code.
6. Record local price/catalyst coverage and freshness. A missing catalyst cache is an input
   failure, never a zero-event result.

**Gate:** baseline evidence committed; no new legacy entry can occur; existing paper
positions remain safely managed; no ledger was truncated or rewritten.

## Phase 1 — Build the success gate before a strategy

Implement pure, strategy-agnostic metrics and tests:

- planned R and initial-risk calculations;
- strict boundary behavior (`1.5R` fails, `<25%` means 25% fails);
- net profit at base and 2× costs;
- event count, hold distribution, win/loss distribution, profit factor, MAE, and friction;
- portfolio drawdown, deployment, and matched-return bootstrap;
- explicit not-run/adequacy/invalid-geometry states.

Extend study artifacts with the metrics, but do not change any locked historical report.

**Gate:** hand-calculated unit cases, property/boundary tests, random-entry negative control,
and full suite pass.

## Phase 2 — Version the research/live boundary

1. Add an immutable `strategy_version` to candidate, signal, fill, position, summary, sync,
   and deterministic identity contracts.
2. Preserve legacy row readability; new writes use a fresh ledger and remote namespace.
3. Make stop/target multiples explicit candidate facts rather than hidden forward constants.
4. Revalidate planned R and initial risk at the actual next-session-open fill.
5. Reject invalid actual-fill geometry with a durable reason; never widen a stop to pass.
6. Preserve final-bar causality, actual-open geometry parity, H2/H1 ordering semantics,
   crash/retry determinism, and zero-event observability.

**Gate:** legacy ledgers remain readable and immutable; success-v2 ledgers are disjoint;
interrupted and uninterrupted state is identical; no future bar is required at EOD.

## Phase 3 — IS-only candidate discovery

Use only bars strictly before 2024-01-01. The previously read 2024–2026 window is consumed
and cannot select a detector, target, rank key, throttle, or parameter.

1. Re-evaluate a small mechanism-led set:
   - trend-conditioned pullback;
   - post-earnings drift after catalyst coverage passes;
   - volatility-compression/breakout;
   - at most one exploratory family.
2. Every candidate must satisfy planned R >1.5 by construction without widening stops or
   extending the 15-session hold.
3. Screen exact geometry on IS only. Report raw returns, net profit, n, MAE, regime slices,
   parameter neighborhoods, and negative controls.
4. Select at most three exact candidates. If none is credible, record STOP; do not force a
   2R target onto a mechanism that does not support it.
5. Save all screen inputs, candidate configs, and rejection reasons.

**Gate:** a short frozen candidate list or an honest STOP; no bar dated 2024-01-01 or later
was read by discovery code.

## Phase 4 — Lock preregs before fresh evidence

For each selected candidate:

1. Create a dated prereg with exact detector, entry, stop, target, time stop, ranking,
   throttle, catalyst treatment, cost arms, slices, bars, and verdict rubric.
2. Declare all prior exposure and the discovery results as priors.
3. Lock the prereg and implementation commit before reading any bar on or after 2026-07-27.
4. Add an independent checklist for causality, geometry, costs, and data-wall enforcement.

**Gate:** prereg and code hashes are immutable; the post-wall reader refuses to run against
an unlocked or mismatched config.

## Phase 5 — Local full-flow rehearsal

1. Replay representative pre-wall sessions with every frame truncated at each `asof`.
2. Verify selected-signal identity, next-session calendar handling, catalyst embargo,
   actual-open geometry, fills, stops, targets, time exits, sizing, and costs.
3. Inject crashes after every durable stage and compare resumed state byte-for-byte with an
   uninterrupted run.
4. Run a multi-session scratch ledger through entry, upkeep, exit, notification, and sync.
5. Run the full suite, `ruff check --fix`, `git diff --check`, and a secret-exposure scan.

**Gate:** all local gates pass; independent review signs off; deployable commit SHA known.

## Phase 6 — Untouched event-level shadow collection

Deploy only the reviewed, versioned event collector:

- keep legacy upkeep isolated until all old positions close;
- use a fresh local ledger root and remote namespace;
- simulate every selected event independently for event-level n; portfolio limits never
  suppress an event in this phase;
- do not count this phase as the later forward portfolio holdout;
- never backfill missed trades;
- journal data coverage, detector counts, geometry rejects, event outcomes, and completion
  markers nightly;
- make the scheduled job the first writer of post-wall evidence.

**Gate:** first scheduled EOD/fill/upkeep cycle reconciles; no duplicate or legacy entry;
sync is append-only and namespace-isolated.

## Phase 7 — Event-level verdict

After a family reaches 100 closed post-wall events:

1. Produce the locked report at base and 2× costs.
2. Verify raw h=15 return, planned geometry, initial risk, net profit, hold time, MAE,
   friction, and required slices.
3. Record PROCEED/PARK/STOP in `decisions.md`.
4. Require independent review before acting on PROCEED.

**Gate:** at least one family PROCEEDs, or the project records the honest STOP.

## Phase 8 — Portfolio expression and forward promotion

Only event-level survivors receive a fresh portfolio prereg. Test slot contention, ordering,
throttle, sizing, drawdown, deployment, and costs. Lock a second untouched forward wall after
the event-level verdict, then start a fresh portfolio ledger. No Phase-6 event row counts
toward the forward read. Continue until both forward floors are met: at least 30 closed trades
and three months.

**Final promotion gate:** positive forward net return inside the matched OOS band, drawdown
≤40%, deployment ≥10%, geometry intact at every fill, no unresolved data/execution divergence,
and independent review.

## Stop conditions

Stop immediately and record the reason if:

- discovery or fitting reads data on or after its allowed wall;
- code changes a detector/geometry after its prereg lock;
- a fill at planned R ≤1.5 or initial risk ≥25% is accepted;
- a legacy and restart ledger/sync namespace can collide;
- evidence is retrospectively filled, rewritten, or silently omitted;
- a failed bar is bypassed by an override.

## Definition of done

The restart is complete only when one newly preregistered family passes 100 untouched
event-level trades and a later, independently walled versioned forward portfolio passes the
30-trade/three-month promotion gate. Infrastructure completion, a profitable consumed-data
backtest, or a successful deployment is not success by itself.

## Execution log (append-only)

- 2026-07-26 — Phase 0 PASS. Evidence:
  `docs/evidence/success-v2/phase-0.md`; commit `8d7484a`.
- 2026-07-26 — Phase 1 PASS. Evidence:
  `docs/evidence/success-v2/phase-1.md`; commit `d6d330d`.
- 2026-07-26 — Phase 2 PASS. Evidence:
  `docs/evidence/success-v2/phase-2.md`. No collection or deployment was
  enabled; Phase 3 is the next authorized data wall.
