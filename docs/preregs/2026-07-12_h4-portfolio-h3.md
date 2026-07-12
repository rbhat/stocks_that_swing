# Prereg: Phase-4 Portfolio Expression — H3 Re-Geometried Breakout (avwap × squeeze)

**Date locked:** 2026-07-12
**Family:** H3 (docs/HYPOTHESES.md §H3)
**Status:** LOCKED
**Phase:** 4 (portfolio expression + validation gate, docs/PLAN.md). Locked blind: no
Phase-4 portfolio backtest of any family has ever run in this repo.

## Mechanism

Unchanged from the locked Phase-3 prereg (2026-07-12_h3-regeometried-breakout.md): volatility
compression under a long-anchored trend condition (above avwap-252) resolves upward; the
parent's detector, swing-native exits. Phase 4 tests the book, not the signal.

## Universe & data

- Roster: full 250-name study roster, no narrowing.
- OOS wall: **2024-01-01, immutable.** Signal dates in [2024-01-01, run date); portfolio-level
  OOS only.
- **Prior-exposure caveat (mandatory restatement):** 2025+ OOS entries were partially consumed
  by the parent project's swing studies. Any verdict on this book restates this; the forward
  paper book is the clean arbiter.
- Price basis: split/dividend-adjusted, as cached.

## Configuration (locked; one cell)

- Candidates: `sts.study.h4_candidates.candidates_for("h3", ...)` — Phase-3 locked primary
  cell verbatim (`vol_squeeze` DEFAULTS + `trend_filter="avwap_252_above"`, ATR14,
  `atr_stop ×2.0`, `atr_target ×2.0`), 2-session pre-earnings `block_entry` embargo.
- Simulator, start capital, cost mechanics, same-session re-entry clause (F2), entry
  priority `(signal_date, symbol)`: identical to the H1 Phase-4 prereg
  (2026-07-12_h4-portfolio-h1.md "Configuration"), simulator at commit `0ade355`.

## Bars (locked — identical to the H1 Phase-4 prereg's four absolute bars)

- [ ] Net return > 0, base cost arm.
- [ ] Max drawdown ≤ 25%.
- [ ] Average deployed ≥ 20% (below → PARK-on-adequacy).
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

## Cost arms

Base: 5 bps/side + $1/order. 2×: 10 bps/side + $2/order.

## Known caveats

- Phase-3 verdict was rubric-PARK (2025 = 45.9% of total edge) overridden to PROCEED.
- 2025+ OOS partially consumed by the parent (see Universe & data) — the weakest evidentiary
  base of the three families; two parent parks preceded it.
- Short OOS window, bull-tape-weighted; survivorship as H1.

## Verdict rubric

Identical mapping to the H1 Phase-4 prereg: all pass → PROCEED (review required before
acting); net ≤ 0 at base with adequate n/deployment → STOP; adequacy failures →
PARK-on-adequacy; DD/stability failure with positive net → PARK. Runner reports bars only;
user records the verdict.

## Deviations log

(append-only; none at lock)

- 2026-07-12 (post-verdict): rubric mapped the run (runs/h4/h3/report.json, e63ef74) to
  STOP (net −4.4% at base, adequate n and deployment); user overrode to PARK — revisit via
  a fresh prereg for a different expression, never a rerun. Recorded in decisions.md with
  adverse facts; rubric unchanged. Independent review NOT YET DONE.

## Sign-off

- [ ] Independent review completed before any PROCEED is acted on.
- Reviewer:
- Date:
