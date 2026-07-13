# Prereg: Phase-5 — Forward Paper (H2 solo + H1-4b, shared book)

**Date drafted:** 2026-07-12
**Status:** DRAFT — pending user ratification of the starred (★) decision points, then LOCKED
**Families:** H2 (PROCEED, e63ef74 record) and H1 in the Phase-4b ranked+throttled
expression (PROCEED, d43c560 record). Both PROCEEDs carry the forward-paper-is-the-clean-
arbiter caveat; this study IS that arbiter. No signal or expression parameter moves.

## Purpose

Forward paper is the first virgin data either family has ever seen. Every backtest verdict
to date read a bull-weighted 2024–2026 window, and H1's window was read twice. This study
judges whether the backtested edges survive contact with data that did not exist at lock.

## Book structure (user-decided 2026-07-12: $100k shared)

One paper account, **$100,000 shared** across both families. Charter limits apply globally:
0.75% risk/trade on current shared equity, max 8 concurrent positions, 80% max deployed,
15% per-position notional cap, one position per symbol (cross-family: a symbol held by
either family blocks the other), 2-session pre-earnings entry embargo.

**Slot-contention rule (named now — this is a NEW expression, stated plainly):** the
combined H1+H2 backtest book is PARKED precisely because H1's fire rate diluted H2's edge
(cf796be). To protect the clean candidate:

1. On any entry session, **H2 candidates fill first**, before any H1 candidate is
   considered. H2 internal order: its Phase-4 convention.
2. H1 candidates then compete for remaining slots under the full 4b expression: rank key
   `(is_seed DESC, rsi2_at_trigger ASC, reclaim_wait_sessions ASC)`, throttle max 4 new
   H1 entries per rolling 5 sessions. (Seed preference stays in the key despite the
   adverse 4b seed slice — the 4b PROCEED validated the whole expression; editing the key
   now would be post-hoc selection. Same reason the ranking-only arm's +57.5% does not
   promote it: the throttle stays.)
3. All results are logged **per-family as well as book-level** so each family's paper read
   is separable — the per-family attribution gap logged against the Phase-4 combined run
   must not recur here.

## Execution mechanics (user-directed, feasibility-checked)

Both families are EOD-signal, next-open-entry systems (`h1_events.entry_geometry`; H2
day2_open). The pipeline preserves that convention exactly:

- **EOD signal job** (each trading day after close, once daily bars are final): incremental
  bar fetch for the 250-name roster (resume-capable, append to cache), run both detectors,
  build the ranked entry queue for tomorrow, size each candidate against current paper
  equity, log to an append-only signal journal, **alert to Discord** (webhook): candidates
  with entry/stop/target/shares, plus current book state.
- **Open fill job** (next session at/near open): submit entries to the broker layer.
  **Broker layer = stub for now** (user-decided): an in-repo `PaperBroker` interface whose
  stub implementation fills entries at the session's actual open price + the charter cost
  model (5 bps/side + $1/order), and manages resting stop/target orders against the daily
  bar exactly as the backtest's exit engine does. Interface designed so a real paper
  broker account (e.g. Alpaca/IBKR paper) can replace the stub without touching the
  signal side; when it does, actual fills become the record and slippage-vs-model is
  reported.
- **Intraday monitor** (hourly during regular hours; one pre-market and one post-market
  check): polls quotes for OPEN positions only (≤8 symbols) and Discord-alerts stop/target
  touches and large pre/post moves on held names. **Advisory only — never a fill
  authority**; fills and exits are governed by the daily-bar engine above, matching the
  backtested convention. (Hourly polling of all 250 names for entry triggers was
  considered and rejected: signals are functions of the completed daily bar, so intraday
  "triggers" would be a different, never-backtested strategy.)
- Every job idempotent and resume-capable: re-running a job for a date it already
  processed is a no-op; state lives in the journal, not in process memory.

## Judged window & bars

- ★ **Duration:** judged read at **6 months** of paper (≈126 sessions), with a
  no-judgment floor of one quarter — no verdict of any kind before 63 sessions.
- Adequacy floors: ≥ 30 closed trades book-level and ≥ 15 closed trades for a family to
  be judged solo; below floor at the 6-month read → extend, PARK-on-adequacy only if
  structurally unreachable.
- ★ **Bars (book-level, judged at the 6-month read):**
  - [ ] Net return > 0 (paper, actual/stub fills, net of cost model).
  - [ ] Max drawdown ≤ 25%.
  - [ ] Average deployed ≥ 20%.
  - [ ] Execution fidelity: mean absolute slippage of realized fills vs the modeled
        next-open fill ≤ 10 bps (stub trivially passes; the bar exists for the real
        broker swap and is reported either way).
- ★ **Per-family reads (verdict-relevant, judged separately):** each family's paper
  expectancy sign vs its backtest claim (H2 +0.134R, H1-4b +0.106R), with a ±0.05R
  neutral band. A family negative beyond the band at the read → that family exits the
  book regardless of book-level bars.
- SPY buy-and-hold over the identical window: reference only, never a bar.
- No cost arms or jitter (nothing to re-simulate — this is live-path observation); the
  bootstrap on closed-trade net R is reported descriptively.

## Verdict rubric

All book bars pass AND both families non-negative → **PROCEED** (Phase-6 candidacy:
real-broker paper or small live sizing — separate decision). One family fails its read →
drop that family, book continues on the survivor (fresh deviations-log entry, no new
prereg needed for the removal). Book-level net ≤ 0 or DD breach → **STOP** the shared-book
expression; family-level evidence still read solo. Adequacy failures → extend or
PARK-on-adequacy. Verdict recorded by the user in decisions.md; independent review before
anything acts on a PROCEED.

## Known caveats

- The shared book with H2-priority is itself a first-look expression — never backtested.
  Per-family logging exists so each family's evidence survives even if the book expression
  fails.
- The stub broker cannot surface real slippage, halts, or borrow/locate issues; execution
  fidelity is only truly tested after the real paper-broker swap.
- Discord/webhook or job-scheduler outages create signal gaps; the journal must record
  missed sessions explicitly (a silent gap is a record-integrity failure, not a holiday).

## Deviations log

(append-only; none at draft)

## Sign-off

- [ ] User ratifies ★ items and locks this prereg (status → LOCKED) before the first
      paper signal is generated.
- [ ] Independent review completed before any PROCEED is acted on.
