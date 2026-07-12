# Prereg: Phase-4 Portfolio Expression — H1 Trend-Conditioned Pullback

**Date locked:** 2026-07-12
**Family:** H1 (docs/HYPOTHESES.md §H1)
**Status:** LOCKED
**Phase:** 4 (portfolio expression + validation gate, docs/PLAN.md). Locked blind: no
Phase-4 portfolio backtest of any family has ever run in this repo (first run postdates
this lock's commit).

## Mechanism

Unchanged from the locked Phase-3 prereg (2026-07-11_h1-trend-pullback.md): short-horizon
sellers dumping a structurally-owned name into a weekly uptrend hand a discount to buyers
who can hold 5–15 sessions. Phase 4 does not retest the signal; it tests whether the signal
survives being expressed as a real book — slot contention, sizing, cash constraints, and
dollar costs.

## Universe & data

- Roster: full 250-name study roster (`universe.yaml` / `cache/study_frames/`), no narrowing.
- OOS wall: **2024-01-01, immutable.** Judged window: signal dates in [2024-01-01, run date).
  Portfolio-level OOS only — no full-history portfolio run is authorized by this prereg.
- Price basis: split/dividend-adjusted, as cached.

## Configuration (all locked; no grid — Phase 4 has exactly one cell per family)

- Candidates: `sts.study.h4_candidates.candidates_for("h1", ...)` — the Phase-3 locked
  primary cell verbatim (`trend_pullback` detector DEFAULTS, ATR14, `atr_stop ×2.0`,
  `atr_target ×2.0`), 2-session pre-earnings `block_entry` embargo on the entry session.
- Simulator: `sts.portfolio.simulate_portfolio` at commit `0ade355` — semantics locked by
  that module's docstring: exits before entries each session; entry priority
  `(signal_date, symbol)` ascending; sizing via `sts.risk.position_size` (0.75% risk, 15%
  notional, 8 slots, 80% deployed, cash-bounded); one position per symbol at a time, where
  **same-session re-entry after that session's exit is permitted** (mechanical consequence
  of exits-first ordering — named here per independent-review finding F2, 2026-07-12);
  entry bar managed same-day; equity marked at close; end-of-window positions censored at
  last close with exit costs.
- Start capital: $100,000 (`sts.risk.START_CAPITAL`).
- Costs charged per fill in dollars: `notional × bps/10,000 + per_order`.

## Bars (locked — the four Phase-4 absolute bars, ratified in decisions.md 2026-07-12)

- [ ] Net return > 0 over the OOS window, base cost arm.
- [ ] Max peak-to-trough drawdown of net equity ≤ 25%.
- [ ] Average deployed fraction ≥ 20% (below → the read is inadequate: PARK-on-adequacy,
      never STOP).
- [ ] Year-by-year expectancy stability, analyst-judged from slices (never machine-checked):
      ≥ 60% of judgeable years positive with a ±0.05R neutral band on `expectancy_r_net`;
      years with n < 10 closed trades are not judgeable (reported not-run).

Also reported, verdict-relevant:
- Cost sensitivity: all bars recomputed at the 2× arm; survives = robust, dies = fragile —
  stated in the verdict either way.
- Param jitter (base costs only): one-at-a-time `atr_stop_multiple ∈ {1.5, 2.5}` and
  `atr_target_multiple ∈ {1.5, 2.5}` (±25% of the locked 2.0). A sign flip of net return in
  any jitter arm is flagged as fragility; jitter arms carry no bar of their own.
- Bootstrap on closed-trade net R (percentile, n_boot=5000, seed=20260712): mean, lower90,
  p_negative reported.
- SPY buy-and-hold over the identical window: **reference only, never a bar** (no relative-
  MAR duel — parent lesson).

## Slices

Year (net expectancy + net return), cost arms, jitter table, exit-reason mix, friction share
of gross P&L, slot-pressure counters (`n_slot_skipped`, `n_dup_symbol`). Nothing else — no
post-hoc diagnostics inside the judged read.

## Adequacy floors

≥ 40 closed OOS trades for the expectancy/bootstrap read; a year needs ≥ 10 closed trades to
be judgeable. Below floor → that read is not-run, PARK-on-adequacy if it blocks the verdict.

## Cost arms

Base: 5 bps/side + $1/order. 2× (mandatory): 10 bps/side + $2/order.

## Known caveats

- Phase-3 verdict for H1 was rubric-PARK (2024 = 63.9% of total edge) overridden to PROCEED
  by the user; that concentration risk carries into this book unexamined.
- ~2.5-year OOS window is short for year-stability; the book is bull-tape-weighted.
- Survivorship: today's roster, historical signals.

## Verdict rubric

All four bars pass → **PROCEED** (to combined book + Phase 5 candidacy; independent review
required before acting). Net return ≤ 0 at base costs with adequate n and deployment →
**STOP** for the portfolio expression (the event edge does not survive being a book). Any
bar failure that is an adequacy failure (deployment floor, trade floor, unjudgeable years) →
**PARK-on-adequacy**. DD or stability bar failure with positive net return → **PARK**.
Runner reports bars only; the verdict is recorded by the user in decisions.md.

## Deviations log

(append-only; none at lock)

## Sign-off

- [ ] Independent review completed before any PROCEED is acted on.
- Reviewer:
- Date:
