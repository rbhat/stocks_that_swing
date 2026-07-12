# Prereg: Re-geometried breakout/squeeze (H3)

**Date locked:** 2026-07-12 (before any H3 run)
**Family:** H3 (docs/HYPOTHESES.md)
**Status:** LOCKED

## Mechanism

A name coiling in a volatility squeeze or tight consolidation has sellers exhausted and
supply absorbed; the expansion bar that breaks the range forces two crowds to pay us —
shorts positioned against the range top who must cover, and sidelined momentum buyers who
chase the confirmed break. The sweep-reclaim variant adds stop-run fuel: a pierce below a
prior swing low transfers shares from stopped-out longs to stronger hands, and the reclaim
squeezes the late shorts. The parent proved these entries carry raw short-horizon edge
(positive layer-a at 5/10/21 sessions) but never tested them with swing-native exits — the
entry×exit confound (long-hold geometry + time cap) is what this study finally breaks.

## Universe & data

- Roster: the finalized 250-name study roster (`StudyStore.load_all()`), same store as H1.
- OOS wall: **2024-01-01, immutable** (decisions.md re-ratification, newest entry). OOS =
  2024-01-01 through the last completed session. **Known prior exposure:** 2025+ OOS is
  partially consumed for these exact entries — the parent's swing studies ran them there
  under time-cap exits. Every verdict from this study must state this caveat verbatim;
  forward paper is the clean arbiter.
- Price basis: split/dividend-adjusted total return throughout.

## Detector / config grid — named before looking at results

Parent detectors VERBATIM on their studied DEFAULTS, zero re-tuning
(`scripts/run_h3_study.py` CELLS):

1. **vol_squeeze** — `sts.signals.squeeze` DEFAULTS: atr_window=14, squeeze_window=60,
   squeeze_percentile=0.20, expansion_ratio=1.5, close_pos_min=0.6, trend_filter="none".
2. **consolidation_breakout** — `sts.signals.breakout` DEFAULTS: lookback=20,
   max_range_pct=0.10, quiet_window=10, quiet_vol_ratio=0.8, breakout_vol_ratio=1.5,
   swing_window=60.
3. **sweep_reclaim** — `sts.signals.sweep_reclaim` DEFAULTS: swing_window=60,
   fib_retrace=0.618, pierce_window=3.
4. **avwap_squeeze_seed** — vol_squeeze DEFAULTS with trend_filter="avwap_252_above"
   (squeeze.py §5-C1 studied constants: 252-session min-low anchor, ±1% band).

- Entry mode: next-session-open after the signal bar (harness convention, all cells).
- Exit rule: single, fixed (see Risk & exit).
- Total cells: 4.

**Primary cell (named before any run): `avwap_squeeze_seed`.** This is a **declared
known-prior cell**, exactly as HYPOTHESES.md §H3 requires: the avwap-252 × vol_squeeze seed
passed every bar in both parent gate runs and the avwap-252-above condition was
price-predictive at every horizon tested in-house — a genuine prior, recorded there as a
post-hoc cross-check, not proof. That prior is the reason for the pick (strongest
mechanism-plus-evidence combination in the family) and is disclosed here rather than
discovered. The three DEFAULT cells are secondary/descriptive: a result in a secondary cell
requires a fresh dated prereg to become primary.

## Risk & exit parameters

- Stop: `risk.atr_stop(entry, atr14, multiple=2.0)` (h1_events `_PARAM_DEFAULTS`, shared
  harness via `h3_events._simulate_event`).
- Target: `risk.atr_target(entry, atr14, multiple=2.0)`. Expected R:R shape ~1:1 with
  breakout-style win rates below mean-reversion's — the edge, if real, shows as expectancy,
  not win rate.
- Time stop: 15 sessions, hard (charter constant).
- Position sizing: charter constants not applied — event-level (layer a/b) study only, no
  portfolio expression in this prereg.
- Catalyst rule: standard 2-session pre-earnings entry embargo (`block_entry` only);
  holding through earnings permitted.

## Two-layer read

- **Layer (a):** `raw_forward_returns` at h = 5/10/15 sessions, exit-free. Must be positive
  at h=15 (the traded horizon).
- **Layer (b):** exit-simmed event expectancy on the primary cell, net of 2× friction.

## Bars (locked — judged against the primary cell only)

- [ ] Layer (a): positive raw forward return at h=15.
- [ ] Layer (b): OOS event-level expectancy > 0, net of 2× friction, n ≥ 100 OOS events.
      Below-n is PARK-on-adequacy, never STOP.
- [ ] Year-by-year stability: ≥ 60% of judgeable OOS years positive, ±0.05R neutral zone
      (window holds full 2024 and 2025 plus partial 2026).
- [ ] No single year > ~40% of total edge (over the two full years + partial 2026).
- [ ] Regime slice (SPY above/below 200d) reported; bull-only concentration flagged
      explicitly — breakout families are structurally bull-skewed.
- [ ] Cost sensitivity: verdict recomputed at 2× costs (10bps/side + $2/order); survives =
      robust, dies = fragile — stated explicitly in the verdict.

## Slices

- Year
- Era (pre/post-2015) — reported by the runner; OOS window is post-2015 only, so this is
  degenerate here and carried for format parity.
- Regime (SPY above/below 200d)
- Dollar-volume tercile (20-session mean dollar volume)
- Exit-reason mix (stop/target/time/censored) — diagnostic for the re-geometry question
  itself: whether swing-native exits change how these entries resolve.

## Adequacy floors

Minimum n = 30 OOS events per slice cell to be judged; below that, the cell is reported
not-run. Below the study-level n = 100 floor the whole study is PARK-on-adequacy.

## Cost arms

- Base: 5 bps/side + $1/order.
- 2× sensitivity (mandatory): 10 bps/side + $2/order.

## Known caveats

- **Partial OOS consumption (the H3 caveat):** 2025+ entries were partially consumed by the
  parent's swing studies under time-cap exits. Any PROCEED is provisional on forward paper.
- **Known-prior primary cell:** the avwap seed was looked at twice in the parent. The
  prior is declared above; the OOS window here (2024+) overlaps the parent's exposure for
  2025+, so this study is a dirtier test for the seed than for the three untouched DEFAULT
  cells — stated, not hidden.
- Survivorship: feed reflects today's constituents/survivors.
- Regime flattery: a bull-skewed window flatters breakout styles — regime bar is locked,
  not optional.
- Evidence-contract gap (codex_review.md #2) still deferred; layer-b numbers inherit that
  limitation, stated in the verdict if unresolved at run time.

## Verdict rubric

- **PROCEED** → Phase 4 portfolio expression, independent review required first. Maps to:
  all locked bars pass on the primary cell, both cost arms — and the verdict text carries
  the partial-consumption caveat regardless.
- **PARK** → Maps to: layer (a) positive but n < 100 (PARK-on-adequacy); or
  stability/concentration bars inconclusive on the short OOS window; or base-cost arm
  passes but 2× arm fails (fragile, not refuted).
- **STOP** → mechanism refuted: layer (a) h=15 non-positive, or layer (b) OOS expectancy
  negative with n ≥ 100.

## Deviations log

(append-only; none at lock)

## Sign-off

- [ ] Independent review completed (required before a PROCEED verdict is acted on).
- Reviewer:
- Date:
