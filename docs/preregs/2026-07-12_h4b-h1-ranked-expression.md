# Prereg: Phase-4b — H1 Re-Expression (Ranked Selection + Burst Throttle)

**Date locked:** 2026-07-12
**Family:** H1 (docs/HYPOTHESES.md §H1)
**Status:** LOCKED
**Phase:** 4b (portfolio re-expression study). Locked blind: no ranked-selection or
throttled portfolio backtest of any kind has ever run in this repo (first run postdates
this lock's commit). Phase-4 H1 solo results are open and cited as motivation — that is
what this study exists to fix — but every ranking criterion and the throttle number below
are named from mechanism/structure only, never from any Phase-4 slice, trade list, or
diagnostic regression. No expectancy-vs-criterion analysis of any kind was run before
this lock.

## Motivation (from the Phase-4 record, decisions.md 2026-07-12)

H1's event edge is real (+0.113R over all 3,207 OOS events, reproducing Phase 3) but the
Phase-4 expression destroyed it (−3.1% net): slot-constrained selection in arbitrary
`(signal_date, symbol)` order captured a +0.044R subset, and clustered correlated entries
on burst days did the rest. This study tests a different expression of the SAME signal —
the signal itself is not retested and none of its parameters move.

## Mechanism (for the expression, named blind)

1. **Ranked selection.** When candidates compete for slots, take the strongest first.
   Strength is defined from the H1 mechanism (short-horizon sellers dumping a
   structurally-owned name into a weekly uptrend):
   - *Seed-preferred first:* the 12 `universe.yaml` seed names are the charter's
     structurally-owned core — the mechanism's "standing structural demand" premise is
     strongest there. Seeds outrank non-seeds.
   - *Deeper dislocation next:* lower `rsi2_at_trigger` = a harder dump into that
     standing bid = a bigger handed-over discount.
   - *Faster demand response next:* smaller `reclaim_wait_sessions` = the standing bid
     answered sooner = stronger confirmation the dump met demand rather than distress.
2. **Burst throttle (on top of ranking only, never instead of it).** Clustered same-burst
   entries are correlated expressions of one market-wide dip; a book of 8 slots gains no
   diversification from filling them all on one signal burst. Cap the rate of NEW entries
   so a single burst cannot saturate the book.

## Universe & data

- Roster: full 250-name study roster, no narrowing. Seed set: the 12 symbols under
  `seeds:` in `universe.yaml` at this lock's commit.
- OOS wall: **2024-01-01, immutable.** Judged window: signal dates in
  [2024-01-01, run date). Portfolio-level OOS only; no full-history portfolio run.
- Price basis: split/dividend-adjusted, as cached.

## Configuration (locked; primary cell + one named descriptive arm, no grid)

- Candidates: `candidates_for("h1", ...)` — Phase-3 locked primary cell verbatim
  (`trend_pullback` DEFAULTS, ATR14, `atr_stop ×2.0`, `atr_target ×2.0`), 2-session
  pre-earnings `block_entry` embargo — identical to the Phase-4 H1 prereg. Candidates
  additionally carry `rsi2_at_trigger`, `reclaim_wait_sessions`, and `is_seed`
  (membership in the seed set above), read from the detector's existing
  `trigger_values` — no new computation, no new signal.
- Simulator: `sts.portfolio.simulate_portfolio` with exactly two semantic changes from
  the Phase-4 lock (everything else — exits-before-entries, sizing via
  `sts.risk.position_size` (0.75% risk, 15% notional, 8 slots, 80% deployed,
  cash-bounded), one position per symbol with the F2 same-session re-entry clause,
  entry bar managed same-day, equity at close, censoring with exit costs — unchanged):
  1. **Entry priority per entry session** (replaces `(signal_date, symbol)` ascending):
     sort candidates by `(is_seed DESC, rsi2_at_trigger ASC, reclaim_wait_sessions ASC,
     signal_date ASC, symbol ASC)`. The last two keys are deterministic tiebreaks only.
  2. **Throttle (primary cell only):** at most **4 new entries per rolling 5-session
     window** (counting entries actually opened, in this book, sessions counted on the
     union trading calendar the simulator already walks). A candidate blocked by the
     throttle is skipped that session (counted `n_throttle_skipped`), never queued.
     The number is derived from structure, blind: 8 slots at the H1 hold horizon
     (5–15 sessions, midpoint ~10) implies steady-state turnover ≈ 8/10 positions per
     session ≈ 4 per 5-session week; the throttle caps entries at steady-state pace so
     bursts spread out instead of saturating the book.
- **Descriptive arm (named now, never load-bearing):** ranking only, throttle off —
  reported alongside so the two changes can be attributed separately. No bar attaches to
  it; the verdict judges the primary cell alone.
- Start capital: $100,000. Costs per fill: `notional × bps/10,000 + per_order`.

## Bars (locked — the four ratified Phase-4 absolute bars, unchanged, primary cell only)

- [ ] Net return > 0 over the OOS window, base cost arm.
- [ ] Max peak-to-trough drawdown of net equity ≤ 25%.
- [ ] Average deployed fraction ≥ 20% (below → PARK-on-adequacy, never STOP — the
      throttle makes this bar newly live; an over-tight throttle must read as an
      inadequate expression, not a dead signal).
- [ ] Year-by-year expectancy stability, analyst-judged from slices: ≥ 60% of judgeable
      years positive with a ±0.05R neutral band on `expectancy_r_net`; years with n < 10
      closed trades not judgeable.

Also reported, verdict-relevant:
- 2× cost arm on all bars (survives = robust, dies = fragile; stated either way).
- Param jitter (base costs, primary cell): one-at-a-time `atr_stop_multiple ∈ {1.5, 2.5}`
  and `atr_target_multiple ∈ {1.5, 2.5}`; **plus one expression-jitter arm named now:
  throttle 3 and 5 per rolling 5 sessions** (±1 around the locked 4). Sign flips flagged
  as fragility; no jitter arm carries a bar.
- Bootstrap on closed-trade net R (percentile, n_boot=5000, seed=20260712).
- SPY buy-and-hold over the identical window: reference only, never a bar.
- **Selection-quality read (named now, analyst-judged):** independent event expectancy of
  the taken subset vs all candidates (Phase-4 baseline: +0.044R taken vs +0.113R all).
  Ranking working = the gap closing or inverting; ranking selecting adversely = the gap
  widening. This read is why the study exists and is stated in the verdict either way.

## Slices

Year (net expectancy + net return), cost arms, jitter table (ATR + throttle arms),
descriptive ranking-only arm summary, exit-reason mix, friction share, seed vs non-seed
trade counts and net expectancy, slot-pressure counters (`n_slot_skipped`,
`n_dup_symbol`, `n_throttle_skipped`), selection-quality read. Nothing else — no post-hoc
diagnostics inside the judged read.

## Adequacy floors

≥ 40 closed OOS trades for the expectancy/bootstrap read; ≥ 10 closed trades per
judgeable year; the seed-vs-non-seed slice needs ≥ 20 closed trades on a side for that
side to be judged. Below floor → not-run, PARK-on-adequacy if it blocks the verdict.

## Cost arms

Base: 5 bps/side + $1/order. 2× (mandatory): 10 bps/side + $2/order.

## Known caveats

- This is the second portfolio expression of the same H1 OOS window; the window is being
  reused, and a pass here is weaker evidence than a first-look pass would have been.
  Stated plainly in any PROCEED. Forward paper remains the clean arbiter.
- H1's Phase-3 rubric-PARK (2024 concentration) and the ~2.5-year bull-weighted window
  carry forward unexamined. Survivorship: today's roster, historical signals.
- Seed preference concentrates the book in 12 names; the 15% notional cap and
  one-position-per-symbol rule are the only concentration brakes. The seed slice exists
  to see this.

## Verdict rubric

Identical mapping to the Phase-4 family preregs: all four bars pass → **PROCEED**
(candidate for a re-run combined book and Phase-5 candidacy; independent review required
before acting). Net return ≤ 0 at base costs with adequate n and deployment → **STOP**
for this expression (two expressions of the H1 edge have now failed; a third requires
new mechanism reasoning, not another prereg of the same shape). Adequacy failures →
**PARK-on-adequacy**. DD or stability failure with positive net → **PARK**. Runner
reports bars only; the verdict is recorded by the user in decisions.md.

## Deviations log

(append-only; none at lock)

## Sign-off

- [ ] Independent review completed before any PROCEED is acted on.
- Reviewer:
- Date:
