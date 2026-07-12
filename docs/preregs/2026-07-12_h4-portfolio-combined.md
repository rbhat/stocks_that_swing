# Prereg: Phase-4 Combined Book — H1 + H2

**Date locked:** 2026-07-12
**Family:** combined (H1 trend-pullback + H2 PEAD)
**Status:** LOCKED
**Phase:** 4, Task 7 (docs/superpowers/plans/2026-07-12-phase4-portfolio.md). Locked blind
to any combined-book result: no combined portfolio backtest has ever run in this repo. The
three family results are open and cited; that is permitted by the plan's Task-7 clause.

## Membership (named blind, from verdicts already recorded)

H1 (PROCEED, user override of rubric STOP) and H2 (PROCEED, rubric-mapped) — per
decisions.md 2026-07-12. **H3 is excluded** (PARKED). Runner invocation:
`run_h4_study.py --family combined --combine h1,h2`.

## Mechanism

Two families with distinct event clocks share one 8-slot book: H1 fires on market
pullback bursts, H2 on the earnings calendar. The combined question is whether H2's edge
survives sharing slots with high-fire-rate H1 (slot dilution risk runs H2→worse), and
whether the blend improves deployment and drawdown versus either book alone.

## Universe & data

Identical to the family preregs: full 250-name roster, OOS wall **2024-01-01 immutable**,
signal dates in [2024-01-01, run date), portfolio-level OOS only, adjusted prices.

## Configuration (locked; one cell)

- Candidates: concatenation of `candidates_for("h1", ...)` and `candidates_for("h2", ...)`
  at each family's locked params (FAMILY_PARAMS verbatim, embargo applied to both).
- Simulator, start capital, cost mechanics, entry priority `(signal_date, symbol)` — family
  never enters the tie-break — and the F2 same-session re-entry clause: identical to the
  H1 family prereg (2026-07-12_h4-portfolio-h1.md "Configuration").

## Bars (locked — the four ratified Phase-4 absolute bars, unchanged)

- [ ] Net return > 0, base cost arm.
- [ ] Max drawdown ≤ 25%.
- [ ] Average deployed ≥ 20% (below → PARK-on-adequacy).
- [ ] Year stability, analyst-judged: ≥ 60% of judgeable years positive, ±0.05R neutral
      band on expectancy_r_net, years with n < 10 closed trades not judgeable.

Also reported, verdict-relevant:
- 2× cost arm on all bars.
- Jitter (base costs): each member's `atr_stop_multiple ∈ {1.5, 2.5}` and
  `atr_target_multiple ∈ {1.5, 2.5}` varied one at a time with the other family locked
  (8 arms total); sign flips flagged, no bar.
- Bootstrap on closed-trade net R, seed 20260712.
- SPY buy-and-hold: reference only, never a bar.
- **Slot-dilution read (named now, analyst-judged):** per-family trade counts and
  expectancy inside the combined book, compared to each family's solo book. H2's
  in-combination expectancy collapsing versus solo (while solo stays the governing PROCEED
  record) is the failure mode this study exists to catch.

## Slices

Year, cost arms, jitter table, per-family attribution (n, expectancy_r_net, share of
trades), exit-reason mix, friction share, slot-pressure counters. Nothing else.

## Adequacy floors

≥ 40 closed OOS trades total; ≥ 10 closed trades per judgeable year; the per-family
attribution slice needs ≥ 20 closed trades for that family to be judged in-combination.

## Cost arms

Base: 5 bps/side + $1/order. 2×: 10 bps/side + $2/order.

## Known caveats

- H1 enters PROCEED only by user override; its solo book failed the net-return bar
  (−3.1%). A combined-book pass driven by H2 with H1 dragging must be stated plainly, not
  averaged away — the per-family attribution slice exists for exactly this.
- H1's fire rate (3,207 OOS candidates) will dominate slot contention; adverse-selection
  and clustering dynamics from the solo books carry in.
- Short (~2.5yr), bull-tape-weighted OOS window; survivorship as before.

## Verdict rubric

Same mapping as the family preregs: all four bars pass → PROCEED (combined book becomes
the Phase-5 forward-paper candidate; independent review required before acting); net ≤ 0
at base with adequate n/deployment → STOP for this combination (family verdicts
untouched); adequacy failures → PARK-on-adequacy; DD/stability failure with positive
net → PARK. Runner reports bars only; the user records the verdict.

## Deviations log

(append-only; none at lock)

- 2026-07-12 (post-run): `report.json` omits the prereg-mandated per-family attribution
  slice (runner gap — `build_report` never grouped trades by family). Attribution was
  recomputed deterministically from the locked config (`.scratch/combined_attrib.py`),
  replication verified against the report exactly (n_trades=655, net_return=+9.5472%):
  H2 73 trades at −0.075R, H1 582 at −0.023R. Recorded in decisions.md.
- 2026-07-12 (post-verdict): rubric mapped the run to PARK (machine bars pass, year-
  stability bar fails 1/3, slot-dilution read fires); user recorded PARK in decisions.md.
  Rubric unchanged. Independent review NOT YET DONE.

## Sign-off

- [ ] Independent review completed before any PROCEED is acted on.
- Reviewer:
- Date:
