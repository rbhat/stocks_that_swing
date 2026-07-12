# Prereg: Trend-conditioned pullback (H1)

**Date locked:** 2026-07-11
**Family:** H1 (docs/HYPOTHESES.md)
**Status:** LOCKED

## Mechanism

A name in a confirmed weekly uptrend attracts structural buyers (trend-followers, dip-buyer
flow) who are absent on any given down day; short-term sellers dumping into a brief daily-scale
pullback are transacting against that standing demand, not against a name in genuine distress.
We are on the other side of short-horizon panic/rebalancing sellers inside a bought trend —
short-term reversal conditioned on medium-term momentum (Medhat–Schmeling lineage, Jegadeesh/
Lehmann). We get paid for supplying liquidity precisely where the HTF trend says demand should
reassert.

## Universe & data

- Roster: intended 250-name roster per `docs/HYPOTHESES.md`/`PLAN.md`. **As of this lock, the
  study-roster is not yet finalized** — `universe.yaml` holds 14 seed symbols only, and
  `codex_review.md` item 3 (roster/manifest, StudyStore.write routing, reach 250) is deferred.
  This study does not run until that gate closes; recorded here as a hard dependency, not
  relitigated by this prereg.
- OOS wall: **2025-07-01, immutable**, per VISION.md. IS = earliest cached history through
  2025-06-30; OOS = 2025-07-01 through the last complete session in cache. No overlap with any
  parent-study exposure (H1 is a new family; the parent never ran this exact grid).
- Price basis: split/dividend-adjusted total return throughout.

## Detector / config grid — named before looking at results

- **Trend condition(s):**
  1. Weekly close above a rising 20-week MA (rising = higher than 4 weeks prior) — computed via
     `sts.weekly.resample_weekly` + `align_to_daily`, causal (uses only completed weekly bars).
  2. Weekly close above a rising 40-week MA (same construction).
  3. Weekly higher-highs/higher-lows structure over the trailing 3 completed weekly swings.
- **Trigger(s):**
  1. RSI(2) < 10 (daily, standard Wilder/Connors RSI(2)).
  2. 3–5 consecutive down closes (daily).
  3. Tag or undercut of the 20-day SMA (daily close <= 20d SMA, prior close above it).
- **Entry mode(s):**
  1. Stop-entry: buy on first close back above the prior day's high (next-open fill per
     harness convention if the level triggers intraday-equivalent on daily bars — i.e. entry
     bar is the day after the reclaim day, per `eventsim` next-open convention).
  2. Limit-at-level: resting limit at the trigger day's low, filled if touched within 3
     sessions, else cancelled (no event).
- **Exit rule(s):** see Risk & exit below — three candidates (10/20-day MA touch, prior swing
  high, 2×ATR).
- **Total cells:** 3 trend × 3 trigger × 2 entry × 3 exit = 54 cells (matches HYPOTHESES.md's
  stated grid size).

**Primary cell** (named blind, before any run): **Trend-1 (20-week rising MA) × Trigger-1
(RSI(2) < 10) × Entry-1 (reclaim of prior day's high) × Exit-3 (2×ATR target)**. No prior run
has touched this cell; it carries no known bias. Rationale for the pick: RSI(2) is the
best-evidenced daily reversal trigger in the cited literature and Connors canon, the 20-week MA
is the more responsive of the two trend filters (faster to re-flag regime changes than 40-week),
the reclaim entry avoids paying for a still-falling knife (unlike the limit entry), and a fixed
2×ATR target keeps this cell's exit independent from H3's structure-target machinery so the two
families stay non-confounded.

Secondary cells (2–53) are descriptive only: reported for context, never used to justify a
PROCEED on their own — a result in a secondary cell requires a fresh dated prereg to become
primary.

## Risk & exit parameters

- Stop: `risk.atr_stop(entry, atr14, multiple=2.0)` for the primary cell (ATR mode). Secondary
  cells may swap in `structure_stop` at the pullback low where the trigger has a natural swing
  level (Trigger-2/3 only; RSI(2) has none) — recorded as a grid axis, not run for the primary
  verdict.
- Target: primary cell uses `risk.atr_target(entry, atr14, multiple=2.0)` (Exit-3). Secondary
  exits use `structure_target` at the prior swing high (Exit-2) or literal MA-touch exit,
  which is not expressible as a static level and is therefore run as a distinct, simpler
  event-loop pass outside `eventsim.simulate_events`'s stop/target contract — reported
  separately, not blended into the primary bars.
- Time stop: 15 sessions, hard (`sts.risk.TIME_STOP_SESSIONS`).
- Position sizing: charter constants (0.75% equity risk/trade, 15% notional cap, 8 max
  concurrent, 80% max deployed) — not applied here. This is a Layer (a)/(b) event-level study
  only, run without portfolio caps per convention; no portfolio expression in this prereg.
- Catalyst rule: standard embargo — auto-fetched earnings block new entries within 2 sessions
  pre-report (`block_entry` only); holding through earnings is permitted, consistent with
  H2 being the dedicated earnings-drift family.

## Two-layer read

- **Layer (a):** `sts.eventsim.raw_forward_returns` at h = 5/10/15 sessions, exit-free. Must be
  positive at h=15 (this study's primary traded horizon, matching the exit's typical hold).
- **Layer (b):** `sts.eventsim.simulate_events` on the primary cell, net of 2× assumed friction.

## Bars (locked — judged against the primary cell only)

- [ ] Layer (a): positive raw forward return at h=15.
- [ ] Layer (b): OOS event-level expectancy > 0, net of 2× friction, n >= 100 OOS events.
      Below-n is PARK-on-adequacy, never STOP.
- [ ] Year-by-year stability: >= 60% of judgeable OOS years positive, ±0.05R neutral zone
      (years with |mean R| < 0.05 vote for nobody — this window has at most ~1.5 partial OOS
      years, so this bar is likely PARK-on-adequacy rather than pass/fail; stated explicitly
      per Fix-5 concern, not glossed over).
- [ ] No single year > ~40% of total edge (same partial-OOS-years caveat applies).
- [ ] Regime slice (SPY above/below 200d) reported; bull-only concentration flagged explicitly
      — this is H1's named failure mode (beta-dip-buying on a bull tape).
- [ ] Cost sensitivity: verdict recomputed at 2x costs (10bps/side + $2/order); survives =
      robust, dies = fragile — stated explicitly in the verdict.

## Slices

- Year
- Era (pre/post-2015)
- Regime (SPY above/below 200d)
- Symbol-liquidity tercile
- Dollar-volume interaction (study-specific: per Medhat–Schmeling, reversal lives in
  low-turnover names — report low/mid/high dollar-volume tercile split explicitly, since this
  is H1's second named failure mode)
- Fill-lag cost: entry-mode A (reclaim, next-open) vs a same-day theoretical fill, reported as
  a diagnostic only (not a judged bar) to quantify how much of the edge the next-open
  convention gives back

## Adequacy floors

Minimum n = 30 OOS events per slice cell to be judged; below that, the cell is reported
not-run. (Below the study-level n=100 floor, the whole study is PARK-on-adequacy per the locked
bar above, regardless of slice floors.)

## Cost arms

- Base: 5 bps/side + $1/order.
- 2x sensitivity (mandatory): 10 bps/side + $2/order.

## Known caveats

- **Roster not yet locked** (see Universe & data) — this is a hard precondition, not a
  statistical caveat; the study does not run until `study_roster.yaml` exists.
- Evidence-contract gap noted in `codex_review.md` #2 (per-event audit rows, right-censoring
  treatment, slippage-vs-fee definition) is still deferred; this study's Layer (b) numbers
  inherit that limitation until the contract is implemented. If the contract lands before this
  study runs, use it; if not, state the limitation in the verdict rather than silently
  proceeding as if it were resolved.
- Survivorship: feed reflects today's constituents/survivors, not the historical membership at
  each signal date.
- Regime flattery: the backtest window may flatter momentum/dip-buying styles if it is
  bull-skewed overall — this is exactly why the regime slice is a locked bar, not a slice-only
  diagnostic.
- Entry-mode A pays a real fill-lag cost (buying strength after the reclaim gives back part of
  the bounce) — measured as a diagnostic, not swept away.

## Verdict rubric

- **PROCEED** → Phase 4 portfolio expression. Requires independent review before anything acts
  on it. Maps to: all locked bars pass on the primary cell, including both cost arms.
- **PARK** → recorded in `decisions.md`, revisitable on new evidence. Maps to: Layer (a)
  positive but Layer (b) n < 100 OOS events (PARK-on-adequacy), or year-stability/regime bars
  inconclusive due to the partial-OOS-years limitation, or the base-cost arm passes but the 2x
  arm fails (fragile, not refuted).
- **STOP** → mechanism refuted, not merely underwhelming. Maps to: Layer (a) raw forward return
  at h=15 is non-positive (no raw entry edge), or Layer (b) OOS expectancy is negative with
  n >= 100 (a real, well-powered loss, not a small-sample fluke).

## Deviations log

(none yet — append-only from this point)

## Sign-off

- [ ] Independent review completed (required before a PROCEED verdict is acted on, or before
      any risk-rule or method change).
- Reviewer:
- Date:
