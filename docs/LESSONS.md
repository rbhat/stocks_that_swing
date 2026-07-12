# Lessons — what the parent project already paid for

Everything from `stocks_that_move` (the parent, 2026-07) that this project inherits: the swing
arc's actual numbers, the structural diagnosis, transferable findings, the method discipline,
the pitfalls, and the code worth copying. Parent ledgers of record: `swing_decisions.md`,
`replan_swing.md`, `swing_next_signals.md`, `decisions.md`, `knowledge_base.md`.

## §1 The swing arc in the parent — what actually happened

| Date | Step | Result |
|---|---|---|
| 07-05 | Study 0: 6 long-hold entries × 16 exits (time caps, R-ladders) on a 250-name roster | Per-trade R: capping loses vs the 2-yr-hold ladder everywhere (best cell −0.28R) — expected, the ladder rides a huge tail. **Layer a: every entry positive raw fwd returns at h=5/10/21 (+0.5%/+0.9%/+1.6%).** Velocity: 10-bar caps beat control on OOS R/slot-day (+0.0027 vs +0.0022; net ~+0.0007 after friction ≈ ⅓ drag) |
| 07-06 | Redeploy portfolio A/B (10-session cap vs long-hold), modern windows | Swing MAR beat baseline on both matched decades incl. GFC (IS_mod +0.69/+0.24, OOS +0.65/+0.50) at roughly half the drawdown → PROCEED to validation |
| 07-08 | Phase 2 on virgin 2025+ | **FAIL**: swing made more money (+27.5% vs +23.9%) at lower exposure (0.46 vs 0.59) and n=138 vs 29, but relative MAR lost (1.21 vs 1.43; maxDD 14.5% vs 10.7%) on an 18-month bull tape; walk-forward 6/18 folds → PARK |
| 07-10 | Phase 2R, sleeve-contribution reframe (combined book 70/30, 50/50) | 2005–2024: combined beats baseline emphatically (MAR up to 0.54 vs 0.24 at ~half the maxDD). **2025+: FAIL by 0.08–0.12 MAR** (1.35/1.31 vs 1.43) — same-detector sleeves can't diversify one calm-tape path → PARK again. The avwap seed book **passed every bar both times** (recorded as post-hoc cross-check) |

Fold map worth remembering: the capped book won 2008 (+1.29 vs −0.88), 2015, 2020 (+4.75 vs
−0.02), 2022 (−0.14 vs −0.66) — every stress year — and lost nearly every calm trend year. A
fast-exit book is structurally defensive; judged against a trend-follower on a bull tape it
will lose *that duel* while being absolutely fine.

## §2 Why those attempts failed — the structural diagnosis (the reason this repo exists)

1. **Geometry mismatch (the killer).** R was welded to a 30% stop, so 1R = a +30% price move —
   essentially unreachable in 10–15 sessions (typical liquid-name moves: 2–8%). Every R-based
   read was distorted: R-ladders never triggered (time exits did all the work), "wins" were
   fractional-R against a full −1R stop, and per-trade comparisons against a 456-bar-hold
   ladder were tautologies. Median parent holds: 175–420 days; consolidation up to 1016.
   **Fix here:** stops at ATR/structure scale, R defined off *that* stop, expectancy governs.
2. **Entry mismatch.** Squeeze/breakout entries are tail-harvesters — designed to catch the
   start of multi-month trends; their payoff *is* the tail. A time cap keeps their noise and
   amputates their payoff. Swing-native entries harvest a repeating oscillation (pullback,
   drift, gap) where the move *completes* inside the hold. No parent study ever used one.
3. **Benchmark mismatch.** Every gate judged swing *relative to the long-hold baseline* (MAR
   duels, fold win-rates) — on tapes where trend-following is at its best. A defensive,
   high-velocity book loses that framing even when absolutely profitable (it was: Bar A passed
   every clause). **Fix:** absolute bars + SPY as reference only.
4. **Multi-timeframe was never actually tested.** Parent Study 3 (weekly/monthly pattern →
   daily entry) was designed and never ran — the vertical parked first. The one trend-filter
   test that did run (bos_bullish × vol_squeeze, long horizon) *passed* and became a live
   config. The user's core thesis is genuinely untested, not refuted.

## §3 Transferable positives (priors, not proof)

- Short-horizon signal exists in-house: layer-a raw forward returns positive at h=5/10/21 for
  every entry family; **avwap-252-above price-predictive at every horizon** — the single
  best-validated in-house condition; natural H1 trend filter.
- Velocity economics are real: capped books redeploy capital ~46× faster; the freed-slot
  effect, not per-trade R, is where a swing edge pays (judge on return per slot-day and
  portfolio equity, never per-trade R alone).
- Crisis-alpha fold map (§1): fast exits cut time-trapped-in-falling-names; expect swing to
  shine in chop/stress years and lag in melt-ups. Design and judge accordingly.
- The avwap × vol_squeeze seed passed both parent gate runs end-to-end — flagged post-hoc both
  times, so it's a prior begging for a pre-named, blind re-test (H3 note).

## §4 Transferable negatives & cautions

- **Cross-sectional momentum-rank has no short-horizon edge** (measured: Q5−Q1 flat-to-
  negative at h=5/10/21/63). Don't build on momentum ranking. (Turnover-conditioned momentum,
  H4, is a different object.)
- "Tighter stops are worse" (parent structure-stops study: doubling stop-outs, hold collapse)
  is **exit-confounded** — measured under the long ladder. It does NOT pre-condemn ATR stops
  in a swing structure, but it warns: stop placement interacts with everything; study it, not
  assume it.
- Same-detector sleeves don't diversify a single calm-tape path (Phase 2R mechanism) — if this
  project ever runs multiple configs, diversification claims need de-correlated entries.
- Signal horizon must match holding horizon (parent Markov finding: a real 5-day edge died
  through a long-hold exit structure). This project's entire premise — enforce it both ways.

## §5 Method capital (inherit wholesale — this is the parent's most valuable export)

- **Prereg before the script exists**; bars, slices, adequacy floors locked; deviations only
  by a new dated prereg *before* re-running (the parent did this correctly once — copy the
  pattern, including the honesty entry).
- **Append-only decision ledger**, newest first, every verdict with its evidence. A locked bar
  honored through a near-miss is the whole point of locking (parent 2R verdict entry is the
  model).
- **Immutable OOS wall**; nothing fits on it, verdicts state what was and wasn't virgin.
- **Event-level judging on a wide roster** (parent gate-v2 lesson: judging a capped 12-name
  book starved every verdict; the same detectors gave hundreds-to-thousands of events on 250
  names). Portfolio expression is a second check, not the sample.
- **Two-layer read**: raw forward returns before exit-simmed R — separates entry edge from
  exit artifact.
- **Censoring-matching** (parent: month-scale windows truncated year-scale holds and biased
  everything) — swing's 15-session cap makes this nearly moot, which is a structural advantage:
  folds and windows always exceed the hold.
- **Neutral bands on consistency votes** (±0.05R-class years vote for nobody; ≥60% banded
  beats ≥70% raw); **exclude no-bind ties** for one-sided interventions.
- **Fixed-horizon bootstrap** (path-length-normalized), never lifetime-max thresholds on
  variable-length paths; **param jitter** for knife-edge fits; **negative controls** (random
  entries must fail the gate).
- **Adequacy floors: below-n ⇒ PARK, never STOP**; a test the window can't support is
  reported not-run, never silently failed.
- **Independent review** for promotions, trade-semantics changes, and method changes;
  PROCEED routes to *more* scrutiny, not to trading.

## §6 Pitfalls ledger

- **Survivorship** (deepest): yfinance returns today's survivors; a "buy dips in names that
  survived" edge is the exact failure mode for pullback strategies. Mitigations: modern
  windows, liquidity floors, the caveat stated on every artifact, and the forward book (no
  survivorship) as final arbiter. Never claim it solved.
- **Regime flattery**: 2005–2024 is stress-heavy (GFC/COVID/2022) and flatters defensive
  books; 2025+ is one bull path and flatters trend books. Neither window alone is the truth —
  year-slices + regime slices always reported.
- **Single-path 18-month holdouts are weak instruments** — the parent parked a vertical twice
  on one. Prefer event-level n + stability structure + forward accrual over any one aggregate
  on one path.
- **Friction at turnover**: ~⅓ of the parent's measured velocity edge went to costs at
  5bps+$1. The 2× cost arm is mandatory, not decorative.
- **Weekly-bar shift-safety**: a weekly bar is known only after Friday's close; resampled
  conditions must use completed bars only (parent has shift-guard test patterns to copy).
- **yfinance revision noise**: upstream bars get revised; the parent logs revisions and
  rebuilds on adjustment-basis changes — port that discipline.
- **Ops before edge** (sequencing): the parent built a superb operation — 340+ tests,
  dashboard, VM, Drive sync, alerts — while zero configs ever reached `validated`. The
  investment is reusable (Phase 6 is cheap *because* of it), but this project finds the edge
  first. Guard against the pull of satisfying infrastructure work when studies stall.

## §7 What to copy from the parent (files, verbatim or near)

Copy files into the new repo; do **not** share a library — the projects will diverge.

| Parent path | Why |
|---|---|
| `src/stm/calendar.py` | XNYS sessions, NY time — horizon-agnostic |
| `src/stm/data/fetch.py` | yfinance wrapper, retries, total-return adjusted bars |
| `src/stm/data/store.py` | atomic parquet store, re-adjustment detection, revision log |
| `src/stm/data/quality.py` | validate-before-write gate |
| `src/stm/data/study_store.py` | wide study-roster cache pattern |
| `src/stm/eventsim.py` | signal-level exit-sim shape (rewrite exits swing-native) |
| `src/stm/backtest.py` | loop mechanics: next-bar slipped fills, stop-first same-bar rule, commissions, dust guard, per-config `time_exit` seam (risk module gets replaced) |
| `src/stm/tradelog.py` | append-only JSONL, first-wins dedupe |
| `src/stm/env.py` | minimal .env loader |
| `src/stm/signals/` | detector families for H3 (port verbatim, zero re-tune) |
| `src/stm/catalyst.py` + earnings fetch job | H2 event dates + the embargo predicate |
| `.scratch/fetch_study_roster.py` pattern | budgeted, resumable roster fetch |
| `tests/` patterns | atomicity, idempotency, shift-guard, parity-when-inert |
| `Makefile`, `pyproject.toml`, `Dockerfile` | shapes only; trim to Phase-1 needs |
| Later (Phase 5–6): `forward.py`, `jobs/forward_test.py`, `notify.py`, `ledger.py`, dashboard | port when earned |

Data facts: 250-name roster ≈ 2.05M daily bars, ~hours to fetch budgeted/resumable; parent
floors deep history at 1970; 202/250 names carry 2025+ bars. Fetch fresh into the new repo's
own cache — never share cache directories between the projects.

## §8 Standing user constraints (2026-07-11, recorded in the parent — govern here)

1. **Catalyst handling is entry-embargo only**: no new entries within 2 sessions before a
   known earnings date; **no pre-event forced exits** — positions may hold through earnings.
2. **Hold horizon 2–3 weeks max** (~10–15 sessions) — the 15-session time stop is a charter
   rule, not a tunable.
3. House-wide: deploy nothing to any VM without an explicit request; alerts (if ever) are
   trade events only; paper trading only.

**Relationship to the parent:** the parent's swing vertical stays PARKED and its ledgers
closed — this project does not reopen them, it replaces the hypothesis (swing-native entries +
swing-native geometry vs. time-capped long-hold entries). If this project one day produces a
surviving book, any cross-portfolio question (does it diversify the parent's book?) goes back
through the parent's own decision process. Until then the two share nothing but lessons.
