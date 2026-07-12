# Decisions

Append-only. Newest first.

---

## 2026-07-11 — Phase 1 gate: reproducible 250-name study roster — gate PASSED

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
