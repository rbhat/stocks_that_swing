# Decisions

Append-only. Newest first.

---

## 2026-07-12 — Phase-4 combined book (H1+H2): PARK (rubric-mapped, user-recorded)

Per locked prereg `docs/preregs/2026-07-12_h4-portfolio-combined.md` and
`runs/h4/combined/report.json` (5f0aa4d): the three machine bars pass — net return +9.5%
(base arm), max drawdown 18.1% (≤25%), average deployed 74.3% (≥20%) — but the analyst-
judged year-stability bar **fails**: 2024 negative (−0.073R, n=262), 2025 neutral
(−0.048R inside the ±0.05R band, n=247), 2026 positive (+0.085R, n=146) → 1/3 judgeable
years positive, below the 60% bar. Rubric: stability failure with positive net → **PARK**.
User recorded PARK on 2026-07-12. Not an override.

The prereg's named slot-dilution read fires: H2 got 73 of 655 combined trades (vs 199
solo) and its in-combination expectancy inverted to −0.075R (vs +0.134R solo); H1 took
582 trades at −0.023R. (The report.json lacks the prereg-mandated per-family attribution
slice — a runner gap, logged in the prereg's deviations log; the numbers above were
recomputed deterministically from the locked config, replication verified against the
report's n_trades=655 and net_return=+9.5472% exactly.) Book expectancy −0.028R,
bootstrap p_negative 77.3%; 2,669 candidates slot-skipped. High-fire-rate H1 crowds H2
out of its own edge — the failure mode the combined prereg existed to catch.

Consequence: **H2 solo remains the Phase-5 forward-paper candidate** (its PROCEED is
untouched). No combined book goes forward in this expression; any revisit requires a
fresh prereg with a different expression (ranked selection / throttle — the Phase-4b H1
re-expression study is the prerequisite). Independent review of Phase-4 verdicts:
NOT YET DONE.

---

## 2026-07-12 — Phase-4 H1 portfolio expression: PROCEED (USER OVERRIDE of rubric STOP)

Per locked prereg `docs/preregs/2026-07-12_h4-portfolio-h1.md` and `runs/h4/h1/report.json`
(e63ef74), the rubric maps H1 to **STOP** for this portfolio expression: net return −3.1%
(base arm) with adequate n (648 trades) and deployment (72.8%). The user overrode to
**PROCEED** on 2026-07-12.

Adverse facts, stated plainly: net return negative at both cost arms (−3.1% base, −10.4%
at 2×); book expectancy −0.020R with bootstrap p_negative 70%; 2/3 years negative; jitter
arms sign-flip (−9.0% to +34.9% net) — the prereg's fragility flag fires; 2,425 candidates
skipped for slots. Post-verdict exploratory diagnostics (outside the judged read) attribute
the failure to expression, not signal: all 3,207 OOS events independently still average
+0.113R (reproducing Phase 3 exactly), but slot-constrained, unranked selection captured a
+0.044R subset and clustered/correlated entries did the rest. The override does not rest on
the locked bars; the rubric is unchanged. Independent review: NOT YET DONE.

---

## 2026-07-12 — Phase-4 H3 portfolio expression: PARK (USER OVERRIDE of rubric STOP)

Per locked prereg `docs/preregs/2026-07-12_h4-portfolio-h3.md` and `runs/h4/h3/report.json`
(e63ef74), the rubric maps H3 to **STOP**: net return −4.4% (base) with adequate n (583)
and deployment (57.0%). The user overrode to **PARK — revisit later** on 2026-07-12.

Adverse facts: negative at both arms (−4.4% / −11.7%); expectancy −0.089R, bootstrap
p_negative 98%; all three years negative expectancy; every jitter arm negative expectancy.
Exploratory diagnostics: even the taken subset's independent event expectancy is negative
(−0.029R vs +0.070R for all 1,739 candidates); contested-day entries averaged −0.203R —
the strongest adverse-selection/clustering signature of the three families. Any revisit is
a fresh prereg for a different expression (ranked selection, burst throttle, or tighter
fire rate), never a rerun of this one. Prior H3 caveats (2025+ OOS partially consumed by
parent; two parent parks) carry forward. Rubric unchanged. Independent review: NOT YET DONE.

---

## 2026-07-12 — Phase-4 H2 portfolio expression: PROCEED (rubric-mapped, user-recorded)

Per the locked prereg `docs/preregs/2026-07-12_h4-portfolio-h2.md` and run artifact
`runs/h4/h2/report.json` (commit e63ef74): all four locked bars pass — net return +20.1%
(base arm), max drawdown 9.4% (≤25%), average deployed 26.0% (≥20%), year stability 2/3
judgeable years positive outside the ±0.05R band (2024 +0.287R n=84, 2025 +0.077R n=72,
2026 −0.070R n=43). 199 closed OOS trades (≥40 floor), expectancy +0.134R net, bootstrap
lower90 +0.049, p_negative 2.4%. Survives 2× costs (+17.2%, all bars still pass) and all
four jitter arms positive (+13.2% to +21.2%). Rubric maps this to **PROCEED** — not an
override; user recorded the verdict 2026-07-12.

Adverse facts, stated plainly: SPY buy-and-hold +63.8% over the same window (reference
only per prereg, never a bar); 2026 YTD expectancy is negative beyond the neutral band;
average deployment sits 6 points above the adequacy floor; window remains ~2.5yr and
bull-tape-weighted.

**Independent review: NOT YET DONE** — required before anything acts on this PROCEED
(prereg sign-off clause). H1 and H3 Phase-4 verdicts: pending user judgment (both failed
the net-return bar; rubric maps to STOP for the portfolio expression).

---

## 2026-07-12 — Phase 4 charter numbers ratified; Phase-4 plan adopted

User ratified the two numbers VISION.md's "drawdown inside the charter cap" line left
unset, blind to any Phase-4 result (no portfolio backtest has ever run in this repo):

1. **Max drawdown cap: 25%** peak-to-trough on net portfolio equity. User chose 25% over
   the recommended 20% (and 15%) — tolerates 2022-style tapes at the cost of a weaker gate.
2. **Exposure floor: ≥ 20% average deployed** over the OOS window (recommended option).

VISION.md amended in place. Phase-4 structure decided: **per-family books first, then a
combined book** (user choice, recommended for clean attribution). Implementation plan at
`docs/superpowers/plans/2026-07-12-phase4-portfolio.md`; family preregs must be locked and
committed before any Phase-4 run, combined prereg locked blind to combined results.

---

## 2026-07-12 — Independent review of the three PROCEED verdicts: SIGN OFF

Independent review (Opus subagent) audited the verdict record against the run artifacts
and preregs before Phase 4 acts, per every prereg's sign-off clause. Result: **SIGN OFF.**
Every quoted number reproduces exactly from the report.json files; judged cells are the
prereg primary cells only; neutral-zone, adequacy-floor, and concentration arithmetic
follow the locked wording (recomputed independently: H1 2024 = 63.9%, H3 2025 = 45.9%,
H2 2024 = 69.2% of total edge); the PARK rubric mappings were correct; the H3
partial-consumption caveat is present where mandated. Main session re-verified the
reviewer's arithmetic against the reports.

Two NITs, no file changes required:
1. Override entry says books are "93–97%" bull-tape; H2 is 92.86% (rounds to 93) —
   cosmetic.
2. `report.json["bars"]` holds only the 4 machine-checkable bars, all PASS; the failing
   concentration bar (and bars 3/5) are analyst-judged from `slices`. Phase-4 tooling must
   not read `bars` alone as a clean bill — decisions.md is the governing record.

Sign-off sections in all three preregs marked complete (reviewer, date 2026-07-12).

## 2026-07-12 — User override: H1, H3, H2 all PARK → PROCEED (user directive)

The user overrides all three rubric-mapped PARK verdicts (entries below) to **PROCEED** to
Phase 4 portfolio expression. Per the standing override convention, the override is logged
with the adverse facts intact; the rubric verdicts below are unchanged and remain the
record of what the locked bars said.

Adverse facts carried into Phase 4, not erased by the override:

- **All three families failed the same locked bar** — no single year > ~40% of total edge
  (H1: 2024 ≈ 64%; H3: 2025 ≈ 46%; H2: 2024 ≈ 69%). Partly structural on a ~2.5-year OOS
  window, but unfalsified.
- **H2's edge is fading monotonically** across the window (0.292R → 0.150R → 0.023R by
  year; 2026 is inside the ±0.05R neutral zone), and its bear-regime behavior is unmeasured
  (n=18, below the slice floor).
- **H3's primary cell is the declared known-prior cell** and its 2025+ OOS is partially
  consumed by the parent's swing studies — the dirtiest test of the three; forward paper
  remains the clean arbiter.
- **All three books are bull-tape-concentrated** (93–97% of events with SPY above its
  200d); bear-regime evidence is thin (H1 n=144 positive; H3 n=54 unresolved; H2 not-run).

Per every prereg's sign-off section, a PROCEED **requires independent review before
anything acts on it** — that review is still pending and is the next gate before any
Phase 4 portfolio work executes.

## 2026-07-12 — H1 verdict: PARK (year-concentration bar failed on the short OOS window)

Prereg: `docs/preregs/2026-07-11_h1-trend-pullback.md` (locked; wall 2024-01-01).
Report: `runs/h1/20260712T191251Z/report.json` — primary cell only (Trend-1 × RSI(2)<10 ×
reclaim entry × 2×ATR target), OOS 2024-01-01 .. 2026-07-11, n = 3207 events.

Locked bars, judged as written:

1. Layer (a) positive at h=15 — **PASS** (+1.28% mean, n=3324).
2. Layer (b) OOS expectancy > 0 net of 2× friction, n ≥ 100 — **PASS**
   (base-cost expectancy 0.1134R, 2×-cost 0.0873R, n=3207).
3. Year-by-year stability ≥ 60% positive, ±0.05R neutral zone — **PASS**
   (2024 +0.188R, 2025 +0.111R, 2026 +0.068R: 3/3 judgeable years positive).
4. No single year > ~40% of total edge — **FAIL**: 2024 carries ~64% of total R
   (2024 1517×0.188=285.8R vs total ~447.5R across 2024/2025/2026).
5. Regime slice reported — **PASS/reported**: bear +0.264R (n=144), bull +0.134R
   (n=3063). Not bull-only: the bear slice is positive and judgeable (n ≥ 30), though
   95.5% of events fire in bull regime — bull concentration flagged as required.
6. Cost sensitivity — **PASS/robust**: 2×-cost arm positive (0.0873R); the verdict
   survives both arms.

Rubric mapping (no override, no diagnostics beyond prereg slices): PROCEED requires all
locked bars to pass — bar 4 fails. STOP requires layer (a) non-positive or a well-powered
negative expectancy — neither holds. The prereg's PARK clause covers
stability/concentration bars inconclusive on the partial-OOS window; with ~2.5 OOS years
the largest year (47% of all events) structurally tends to exceed 40% of edge. **PARK** —
revisitable as the post-wall window grows.

## 2026-07-12 — H3 verdict: PARK (year-concentration bar failed marginally; partial-consumption caveat applies)

Prereg: `docs/preregs/2026-07-12_h3-regeometried-breakout.md` (locked; wall 2024-01-01).
Report: `runs/h3/oos_2024-01-01/report.json` — primary cell `avwap_squeeze_seed` only
(declared known-prior cell), OOS 2024-01-01 .. 2026-07-11, n = 1739 events.

Locked bars, judged as written:

1. Layer (a) positive at h=15 — **PASS** (+1.49% mean, n=1781).
2. Layer (b) OOS expectancy > 0 net of 2× friction, n ≥ 100 — **PASS**
   (base-cost 0.0695R, 2×-cost 0.0400R, n=1739).
3. Year-by-year stability ≥ 60% positive, ±0.05R neutral zone — **PASS**
   (2024 +0.090R, 2025 +0.119R, 2026 +0.083R: 3/3 judgeable years positive).
4. No single year > ~40% of total edge — **FAIL (marginal)**: 2025 carries ~46% of total R
   (666×0.119=79.0R vs total ~172R).
5. Regime slice reported — **PASS/reported**: bear +0.122R (n=54, judgeable but lower90
   −0.059 — not resolved), bull +0.098R (n=1685). 96.9% of events fire in bull regime —
   bull concentration flagged as required.
6. Cost sensitivity — **PASS/robust**: 2×-cost arm positive (0.0400R).

**Mandatory caveat (prereg + HYPOTHESES §H3):** 2025+ OOS is partially consumed for these
entries — the parent's swing studies ran them under time-cap exits; the known-prior primary
cell makes this the dirtier test by construction. Forward paper is the clean arbiter.

Rubric mapping (no override): PROCEED needs all bars — bar 4 fails (45.9% vs ~40%). STOP
conditions not met. **PARK** — revisitable as the post-wall window grows and forward paper
accrues; the partial-consumption caveat stands regardless.

## 2026-07-12 — H2 verdict: PARK (2026 in the neutral zone; 2024 dominates the edge)

Prereg: `docs/preregs/2026-07-12_h2-pead.md` (locked; wall 2024-01-01).
Report: `runs/h2/oos_2024-01-01/report.json` — primary cell `top_decile_day2_open` only,
OOS 2024-01-01 .. 2026-07-11, n = 252 events.

Locked bars, judged as written:

1. Layer (a) positive at h=15 — **PASS** (+3.12% mean, n=250).
2. Layer (b) OOS expectancy > 0 net of 2× friction, n ≥ 100 — **PASS**
   (base-cost 0.1637R, 2×-cost 0.1434R, n=252).
3. Year-by-year stability ≥ 60% positive, ±0.05R neutral zone — **PASS**: 2026 (+0.023R,
   n=55) falls inside the neutral zone and votes for nobody; the two judgeable years are
   both positive (2024 +0.292R, 2025 +0.150R → 2/2).
4. No single year > ~40% of total edge — **FAIL**: 2024 carries ~69% of total R
   (110×0.292=32.1R vs total ~46.3R).
5. Regime slice reported — **reported/not-run in part**: bear n=18 is below the slice
   adequacy floor (30) → reported not-run; bull +0.145R (n=234). 92.9% of events fire in
   bull regime — bull concentration flagged as required.
6. Cost sensitivity — **PASS/robust**: 2×-cost arm positive (0.1434R).

Rubric mapping (no override): PROCEED needs all bars — bar 4 fails, and the 2026 neutral
year plus the not-run bear slice leave stability/regime only partially resolved on this
window. STOP conditions not met (raw edge positive, expectancy well-powered positive).
**PARK** — the drift's fade from 2024→2026 (0.292 → 0.150 → 0.023R) is exactly what the
next year of post-wall data will adjudicate.

## 2026-07-12 — Charter amendment: OOS wall re-ratified to 2024-01-01 (user)

The OOS wall moves from 2025-07-01 to **2024-01-01, immutable** — IS = history through
2023-12-31; OOS = 2024-01-01 through the last complete session in cache (~2.5 years: two
full years, 2024 and 2025, plus 2026 YTD — enough for a real year-by-year stability read,
and the window includes the 2024-08 and 2025-04 drawdowns). Ratified by the user 2026-07-12.

Applied everywhere in the same change: VISION.md charter line, PLAN.md Phase-2.5 hard rule,
PREREG_TEMPLATE.md, `scripts/run_h1_study.py` `DEFAULT_OOS_START`, and the staged study
harness code in `port_from_run1/` (H2/H3 runners, Phase-2.5 orchestrator `OOS_WALL`). The
H1 prereg was re-locked with the new wall before any run (see its deviations log); its
window-derived stability-bar wording updated — the bars are now judgeable, not
PARK-on-adequacy-by-construction.

Data-side precondition verified 2026-07-12: all 250 cached frames match
`configs/study_roster_manifest.json` sha256; roster dry-run reports a clean no-op; full
test suite green (192 passed).

Closed `codex_review.md` #3. `scripts/fetch_study_roster.py` writes now route through
`sts.data.study_store.StudyStore.write` (validate + truncate-incomplete + atomic+fsync) instead
of a raw parquet write path; freshness is session-based
(`sts.calendar.last_completed_session()` minus a 5-session staleness allowance) instead of a
fixed `--min-end-year` check.

**Gate: PASSED.** Roster reached 250 symbols (12 gated-store seeds/anchors + 238 fill names).
Run 1 fetched 1 new symbol (GPC) to close the gap; 2 fill candidates were rejected (FDXF too
short, FISV had a missing session) and recorded to the dead-symbol sidecar. Run 2 confirmed a
true no-op: "target already met and all must-haves present — nothing to fetch." `configs/
study_roster.yaml` and `configs/study_roster_manifest.json` from both runs are identical apart
from `as_of`/`generated_at` timestamps. Full suite: 184 passed.

**Committed reproducibility contract:** `configs/study_roster.yaml` (exact 250-symbol
membership, source, eligibility window, seeds/anchors, rationale) and `configs/
study_roster_manifest.json` (per-symbol first/last session, adjustment basis, fetch timestamp,
file sha256) are tracked in git — the study population is now reconstructable from the commit
alone, without re-deriving it from the gitignored parquet cache. `tests/
test_fetch_study_roster.py` added (script previously had no tests).

---

## 2026-07-11 — Phase 2: Swing risk engine + study harness — gate PASSED

Built `src/sts/risk.py` (swing-native risk engine), rewrote `src/sts/eventsim.py` (two-layer
event-level exit-sim harness), added `src/sts/weekly.py` (shift-safe weekly resampler), and
`docs/PREREG_TEMPLATE.md`. Deleted `src/sts/backtest.py` (a stale verbatim parent copy — 30%
stops, Fibonacci targets, fixed-% sizing; Phase 4's job to rebuild against the real charter
numbers, not this phase's).

**Gate: PASSED.** Negative control (`tests/test_eventsim.py`,
`test_negative_control_random_entries_show_no_edge`): 258 random-entry events through the real
ATR stop/target/15-session-time-stop structure show `expectancy_r ≈ 0.0086R` (band: `<0.10R`)
and `expectancy_r_lower90 ≈ -0.069R` (band: `<0.05R`) — no fabricated edge. Shift-guard tests
(`tests/test_weekly.py`) green, including a real-NYSE-holiday-week case (2025-07-04) that a
naive "must end on Friday" heuristic would misjudge. Full suite: 176 passed.

**Independent review (Opus subagent):** no correctness bug, no charter violation, no trace of
the parent's forbidden geometry (30% stops, Fibonacci extensions, fixed-%-of-equity sizing,
≥2R floor) in any reviewed file. One review claim was checked against the parent's own
(pre-deletion) `backtest.py` docstring and found inaccurate: the reviewer read `eventsim.py`'s
entry-bar-skip convention (a position's own fill bar isn't checked for a same-session
stop/target; management starts the bar after entry) as a divergence from the parent's
"same-bar rule." The parent's docstring says the opposite — *"A position opened at session t
is first managed at t+1... a same-day stop/target hit is a documented conservatism, not a
bug"* — the identical convention. No change made; recorded here as confirmed, not open. The
review's other finding (time-stop and censoring exit paths in `eventsim._sim_one` were only
exercised indirectly via the negative control, never hand-traced) was valid and fixed:
`test_simulate_events_time_stop_exit_path` and `test_simulate_events_censored_at_end_of_frame`
added.

**Deferred to Phase 3 (not a Phase 2 gap):** `src/sts/signals/{breakout,sweep_reclaim,markov}.py`
docstrings still describe swing points feeding "the risk layer's Fibonacci targets" and a "2R
fallback" — vestigial parent language — and emit `swing_low`/`swing_high` rather than the
`stop_level`/`target_level` keys `eventsim.py`'s structure mode reads. Running these detectors
in structure mode today would skip every event for want of the right trigger_values keys. This
is real wiring work for whichever H3 study first uses structure mode, not a Phase 2 defect —
noted here so it isn't rediscovered mid-study.

## 2026-07-11 — Phase 0: Charter ratification

All VISION.md charter rules ratified with one amendment (short side). Decisions:

1. **Universe**: 250-name roster (parent shape). Cache already seeded — `universe.yaml`
   (12 seeds) + `cache/study_frames/` (250 parquet files) present at kickoff. Floors:
   price ≥ $5, avg dollar-vol ≥ $20M — confirmed.
2. **OOS wall**: **2025-07-01** (not the proposed 2025-01-01) — ~12 months of virgin OOS
   from kickoff. User chose this over both the 2026-01-01 alternative (too short, ~6mo,
   no year-by-year stability read possible) and the original 2025-01-01 proposal.
3. **Risk numbers**: confirmed as proposed — 0.75% risk/trade, max 8 concurrent positions,
   80% max deployed, 15% per-position notional cap, stop bound ≤12% of entry.
4. **Short side**: **off the table entirely** (AMENDS VISION.md, which proposed a
   phase-gated amendment after Phase 5). Long-only permanently for this project — no
   future short-side path assumed. VISION.md updated to reflect this.
5. **Costs**: confirmed as proposed — 5 bps/side + $1/order, mandatory 2× cost-sensitivity
   arm on every verdict.
6. **Catalyst rule**: confirmed as standing directive — no new entries within 2 sessions
   before a scheduled earnings date; holding through earnings allowed, no forced exits.
7. **Repo name / sync**: `stocks_that_swing` (matches current directory). No Drive sync
   or multi-machine setup before Phase 6.

**Status: VISION.md charter RATIFIED** (short-side clause amended per #4 above).
Proceeding to Phase 1 (port foundations from parent `stocks_that_move` at
`/Users/rajeev/dev/stocks_that_move`).
