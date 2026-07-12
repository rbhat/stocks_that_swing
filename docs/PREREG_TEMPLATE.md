# Prereg: <Study Name> (H<N>)

Copy this file to `docs/preregs/YYYY-MM-DD_<slug>.md` and fill it in **before the study
script exists**. Once dated and committed, it is locked: any deviation is a new dated prereg,
never an edit to this one (LESSONS §5). Bars, slices, and adequacy floors below come from
`docs/HYPOTHESES.md`'s "Bars shape" and `docs/VISION.md`'s charter — this template wires them
to one study, it doesn't relitigate them.

**Date locked:**
**Family:** H1 / H2 / H3 / H4 (docs/HYPOTHESES.md)
**Status:** LOCKED

## Mechanism

One paragraph: who is on the wrong side of this trade and why they pay us. If you can't state
this, the study isn't ready to prereg.

## Universe & data

- Roster: 250-name roster (`universe.yaml`) unless narrowed — state the narrowing and why.
- OOS wall: **2024-01-01, immutable.** State what fraction of this study's window is
  in-sample vs. out-of-sample, and whether any of it overlaps a parent-study exposure
  (H3 caveat: 2025+ entries partially consumed by the parent's swing studies).
- Price basis: split/dividend-adjusted total return (never mixed).

## Detector / config grid — named before looking at results

List every cell; the grid is small and pre-registered, not swept post-hoc.

- Trend condition(s):
- Trigger(s):
- Entry mode(s):
- Exit rule(s) (see Risk & exit below):
- Total cells: N

**Primary cell:** name the single cell this study is judged on, chosen *before* running
anything. If a cell carries a known prior (e.g. it was flagged post-hoc in an earlier study),
say so explicitly — a prior is not disqualifying, but it must be named, not discovered.

## Risk & exit parameters

- Stop: ATR multiple or structure rule, with exact params (e.g. `atr_stop(entry, atr14, multiple=2.0)` or the structure level definition).
- Target: ATR multiple or structure rule, with exact params. No R:R floor is imposed — state the expected R:R shape anyway (e.g. "~1:1, high win rate" for mean reversion) so a reader can sanity-check the result against the mechanism.
- Time stop: 15 sessions, hard (charter constant, `sts.risk.TIME_STOP_SESSIONS` — not a per-study tunable).
- Position sizing: 0.75% equity risk/trade, 15% per-position notional cap, 8 max concurrent positions, 80% max deployed (charter constants, `sts.risk` — not per-study tunables). Event-level studies (layer b via `sts.eventsim`) run without portfolio caps by convention; state here if this study is event-level-only or also runs a portfolio expression.

## Two-layer read

- **Layer (a):** raw forward returns at h = 5/10/15 sessions (`sts.eventsim.raw_forward_returns`), exit-free. Must be positive at the study's traded horizon — a family that only wins after exit-sim is an exit artifact, not an entry edge.
- **Layer (b):** event-level exit-simmed expectancy (`sts.eventsim.simulate_events`), net of 2× assumed friction.

## Bars (locked — check the ones this study is judged against; do not add bars after seeing results)

- [ ] Layer (a): positive raw forward return at the traded horizon.
- [ ] Layer (b): OOS event-level expectancy > 0, net of 2× friction, n ≥ 100 OOS events. Below-n is PARK-on-adequacy, never STOP (a test the window can't support is reported not-run).
- [ ] Year-by-year stability: ≥ 60% of judgeable years positive, with a ±(state noise band) neutral zone — near-zero years vote for nobody.
- [ ] No single year > ~40% of total edge.
- [ ] Regime slice (SPY above/below 200d) reported; bull-only concentration flagged explicitly.
- [ ] Cost sensitivity: verdict also computed at 2× costs (10bps/side + $2/order); survives = robust, dies = fragile — state which in the verdict.

## Slices

- Year
- Era (pre/post-2015)
- Regime (SPY above/below 200d)
- Symbol-liquidity tercile
- (study-specific slices — name them here, e.g. reaction sign for H2, dollar-volume interaction for H1)

## Adequacy floors

State the minimum n per slice cell below which that slice is reported not-run rather than judged.

## Cost arms

- Base: 5 bps/side + $1/order.
- 2× sensitivity (mandatory): 10 bps/side + $2/order.

## Known caveats

State anything a reader needs to discount the result for: survivorship (feed returns today's
survivors), regime flattery (window choice flatters one style), prior exposure (H3's partial
2025+ consumption), or anything specific to this study's construction.

## Verdict rubric

- **PROCEED** → Phase 4 portfolio expression. Triggers independent review before anything acts on it.
- **PARK** → recorded in `decisions.md`, revisitable on new evidence. Includes PARK-on-adequacy.
- **STOP** → mechanism refuted by the locked bars, not merely underwhelming.

State explicitly which bar failure(s) map to which verdict for this study, so the verdict
isn't a judgment call made after seeing the numbers.

## Deviations log

Append-only. Any change to this prereg after the lock date goes here with a date and reason,
or — if it changes what's being tested, not just recorded — as a fresh dated prereg file
instead, referencing this one.

## Sign-off

- [ ] Independent review completed (required before a PROCEED verdict is acted on, or before any risk-rule or method change).
- Reviewer:
- Date:
