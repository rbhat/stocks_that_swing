# Prereg: Phase-4 Portfolio Expression — H2 Earnings-Reaction Drift (PEAD)

**Date locked:** 2026-07-12
**Family:** H2 (docs/HYPOTHESES.md §H2)
**Status:** LOCKED
**Phase:** 4 (portfolio expression + validation gate, docs/PLAN.md). Locked blind: no
Phase-4 portfolio backtest of any family has ever run in this repo.

## Mechanism

Unchanged from the locked Phase-3 prereg (2026-07-12_h2-pead.md): limited-attention
underreaction to earnings news, proxied by the first post-report session's price reaction;
top-decile reactions drift for days-to-weeks. Phase 4 tests the book, not the signal.

## Universe & data

- Roster: full 250-name study roster; earnings dates from `cache/catalysts/earnings.json`
  (past dates only, as Phase 3).
- OOS wall: **2024-01-01, immutable.** Signal (reaction-session) dates in
  [2024-01-01, run date); portfolio-level OOS only.
- Price basis: split/dividend-adjusted, as cached.

## Configuration (locked; one cell)

- Candidates: `sts.study.h4_candidates.candidates_for("h2", ...)` — Phase-3 locked primary
  cell verbatim (`top_decile_day2_open`: reaction-session rule, causal trailing-252
  comparison decile, day-2-open entry; ATR14, `atr_stop ×2.0`, `atr_target ×2.0`).
- **Catalyst rule:** the standing 2-session pre-earnings `block_entry` embargo applies to H2
  exactly as its Phase-3 prereg locked it. The Phase-4 plan's original H2 exemption was an
  error caught by independent review (finding F1, 2026-07-12) and corrected in commit
  `0ade355` before this lock; no run ever executed under the exempted adapter.
- Simulator, start capital, cost mechanics, same-session re-entry clause (F2), entry
  priority `(signal_date, symbol)`: identical to the H1 Phase-4 prereg
  (2026-07-12_h4-portfolio-h1.md "Configuration"), simulator at commit `0ade355`.

## Bars (locked — identical to the H1 Phase-4 prereg's four absolute bars)

- [ ] Net return > 0, base cost arm.
- [ ] Max drawdown ≤ 25%.
- [ ] Average deployed ≥ 20% (below → PARK-on-adequacy; PEAD is event-clustered around
      earnings seasons, so this floor is the bar most at risk for H2 — named now, blind).
- [ ] Year stability, analyst-judged: ≥ 60% of judgeable years positive, ±0.05R neutral band,
      years with n < 10 closed trades not judgeable.

Also reported: 2× cost arm on all bars; jitter `atr_stop_multiple ∈ {1.5, 2.5}`,
`atr_target_multiple ∈ {1.5, 2.5}` (sign flips flagged, no bar); bootstrap on closed-trade
net R (seed 20260712); SPY buy-and-hold reference only.

## Slices

Year, cost arms, jitter table, exit-reason mix, friction share, slot-pressure counters.
Nothing else.

## Adequacy floors

≥ 40 closed OOS trades; ≥ 10 closed trades per judgeable year.

## Known caveats

- Phase-3 verdict was rubric-PARK (2024 = 69.2% of total edge) overridden to PROCEED.
- Earnings-season clustering means slot contention and deployment are lumpy by construction.
- Short OOS window, bull-tape-weighted; survivorship as H1.

## Cost arms

Base: 5 bps/side + $1/order. 2×: 10 bps/side + $2/order.

## Verdict rubric

Identical mapping to the H1 Phase-4 prereg: all pass → PROCEED (review required before
acting); net ≤ 0 at base with adequate n/deployment → STOP; adequacy failures →
PARK-on-adequacy; DD/stability failure with positive net → PARK. Runner reports bars only;
user records the verdict.

## Deviations log

(append-only; none at lock)

## Sign-off

- [x] Independent review completed before any PROCEED is acted on.
- Reviewer: Independent review (Opus subagent), verified by main session against run artifacts
- Date: 2026-07-12
