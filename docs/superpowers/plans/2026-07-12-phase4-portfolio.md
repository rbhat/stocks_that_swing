# Phase 4 — Portfolio Expression + Validation Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the three PROCEED families (H1 trend-pullback, H3 re-geometried breakout, H2 PEAD) into real portfolio backtests — per-family books first, then a combined book — judged absolutely against locked preregs.

**Architecture:** A new pure portfolio simulator (`src/sts/portfolio.py`) consumes pre-built candidate-entry lists (one adapter per family reusing the Phase-3 study modules) and drives them through `sts.risk` primitives (`position_size`, `Position`, `manage_bar`) on a daily loop with real dollar costs. A separate gate module computes the validation-gate stats (bootstrap, year stability, param jitter). One runner script per invocation (`--family h1|h3|h2|combined`), resumable, reporting to `runs/h4/<family>/report.json`. Preregs locked and committed before any run.

**Tech Stack:** Python 3 (.venv/bin/python), pandas/numpy, pytest. No new dependencies.

## Global Constraints

- Charter risk numbers (already in `src/sts/risk.py`, do not re-declare): 0.75% risk/trade, 8 max positions, 80% max deployed, 15% notional cap, stop ≤12% of entry, 15-session time stop, long only, no averaging, stops never widened.
- Costs: 5 bps/side + $1/order base arm; 2× arm (10 bps, $2) mandatory on every report.
- **Phase-4 absolute bars (ratified 2026-07-12, user):** max peak-to-trough drawdown of net equity ≤ **25%**; average deployed fraction over the OOS window ≥ **20%**; net return > 0 (base cost arm); expectancy stable year-by-year (neutral band per prereg).
- OOS wall 2024-01-01, immutable. OOS-only judgment; full-history runs only if a locked prereg names them.
- Catalyst rule: no new entries within 2 sessions before a scheduled earnings date (`sts.catalyst.CatalystCalendar`) — **all three families**, H2 included: its locked Phase-3 prereg locks the embargo, so the plan's original H2 exemption was an error (corrected 2026-07-12 per independent-review finding F1).
- Scripts must be resumable and log elapsed/ETA (user global rule).
- Runner reports PASS/FAIL bars only; **never writes a decisions.md verdict** (verdicts are the user's).
- SPY buy-and-hold reported for reference only — never a relative bar.
- Determinism: no RNG except the bootstrap, which takes a fixed seed recorded in the report.

## File Structure

- Create: `src/sts/portfolio.py` — portfolio simulator (pure, no I/O).
- Create: `src/sts/study/h4_candidates.py` — per-family candidate adapters (H1/H3/H2 → uniform candidate dicts).
- Create: `src/sts/study/h4_gate.py` — validation-gate stats (bootstrap, year stability, jitter orchestration helper).
- Create: `scripts/run_h4_study.py` — runner CLI.
- Create: `tests/test_portfolio.py`, `tests/test_h4_candidates.py`, `tests/test_h4_gate.py`.
- Create: `docs/preregs/2026-07-12_h4-portfolio-{h1,h3,h2}.md` (family preregs, locked before family runs) and later `docs/preregs/*_h4-portfolio-combined.md` (locked after family runs but blind to any combined result).

---

### Task 1: Portfolio simulator core

**Files:**
- Create: `src/sts/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `sts.risk` (`position_size`, `Position`, `manage_bar`, `r_multiple`, `START_CAPITAL`).
- Produces:

```python
def simulate_portfolio(
    prices: dict[str, pd.DataFrame],          # daily OHLC frames, tz-naive DatetimeIndex
    candidates: list[dict],                    # uniform candidate dicts, see below
    start: dt.date, end: dt.date,              # portfolio session window [start, end)
    bps_per_side: float = 5.0,
    per_order: float = 1.0,
    start_capital: float = risk.START_CAPITAL,
) -> dict
```

Candidate dict (produced by Task 2 adapters):
`{"symbol": str, "signal_date": dt.date, "entry_date": dt.date, "entry": float, "stop": float, "target": float | None, "family": str}` — entry/stop/target already validated at Phase-3 geometry; the simulator re-validates via `risk.Position` and skips violators (counted).

Semantics (these are the prereg-locked mechanics — implement exactly):
1. Daily loop over the sorted union of all trading dates in `prices` within `[start, end)`.
2. **Exits first**: each open position advances via `risk.manage_bar` on its symbol's bar (position skips days its symbol has no bar); exits book cash at `price*shares - costs`; cost per fill = `notional * bps_per_side/10_000 + per_order`.
3. **Entries second**: candidates with `entry_date == today`, deterministic priority `(signal_date, symbol)` ascending; each sized via `risk.position_size(equity, entry, stop, deployed, cash, open_count)` using *post-exit* state updated candidate-by-candidate; size 0 or `RuleViolation` → skipped (counted as `n_slot_skipped` / `n_invalid`). Entry fill at candidate `entry` (that session's open, matching eventsim convention); entry cost charged at fill. Entry bar is managed **that same day** for exits? No — the entry bar was already processed in step 2's pass for pre-existing positions only; to match eventsim's entry-bar-managed convention, after opening, run `manage_bar` on the entry bar for the new position too (same-session stop/target can resolve, time clock starts on entry bar).
4. One position per symbol at a time; a candidate for an already-held symbol is skipped (`n_dup_symbol`).
5. Equity marked daily at close (cash + Σ shares×close); missing bar → last known close.
6. `end` reached with open positions → censor at last close, `exit_reason="censored"`, exit costs applied.

Returns dict:
```python
{
 "equity": {iso_date: float, ...},            # daily net equity
 "trades": [ {symbol, family, entry_date, exit_date, entry, exit, shares,
              stop, target, exit_reason, r_gross, r_net, pnl_net} ... ],
 "summary": {"net_return", "max_drawdown", "avg_deployed", "n_trades",
             "expectancy_r_net", "friction_share",       # Σcosts / Σ|gross pnl|
             "by_year": {yyyy: {"n", "expectancy_r_net", "net_return"}},
             "n_slot_skipped", "n_invalid", "n_dup_symbol"},
}
```
`r_net = (net proceeds per share − entry incl. entry cost per share) / (entry − stop)`; `max_drawdown` = max peak-to-trough on the daily equity series; `avg_deployed` = mean over sessions of (Σ shares×close)/equity.

- [ ] **Step 1: Write failing tests** covering, with tiny hand-built 2–3 symbol frames: (a) a single candidate fills next-day open, stops out, cash/costs arithmetic exact to the penny; (b) slot contention — 9 same-day candidates, 8 fill in `(signal_date, symbol)` order; (c) deployed-cap binding; (d) duplicate-symbol skip; (e) same-day entry-bar stop resolves as loss; (f) censoring at `end`; (g) equity marking with a missing bar; (h) determinism (two runs identical).
- [ ] **Step 2: Run tests, verify FAIL** (`pytest tests/test_portfolio.py -v` → import error).
- [ ] **Step 3: Implement `simulate_portfolio`** per semantics above; module stays pure (no file I/O, no prints).
- [ ] **Step 4: Tests pass**, plus full suite (`pytest -q`) still green (176+ passing).
- [ ] **Step 5: Commit** `feat: add portfolio simulator (Phase 4)`.

### Task 2: Per-family candidate adapters

**Files:**
- Create: `src/sts/study/h4_candidates.py`
- Test: `tests/test_h4_candidates.py`

**Interfaces:**
- Consumes: `sts.study.h1_events`, `h3_events`, `h2_events` (reuse their event collection + stop/target derivation exactly as the Phase-3 runners wired them — read `scripts/run_h{1,3,2}_study.py` for the locked primary-cell params and copy them as module constants with a comment citing the prereg); `sts.catalyst.CatalystCalendar` for the entry-embargo filter (H1/H3 only).
- Produces: `candidates_for(family: str, prices, oos_start, oos_end, catalyst) -> list[dict]` returning Task-1 candidate dicts, plus `FAMILY_PARAMS: dict[str, dict]` (the locked primary-cell params per family, for jitter).

- [ ] **Step 1: Failing tests** — for each family, a fixture frame that fires exactly one known event; assert the candidate dict's entry/stop/target match a hand-computed value and that a candidate 1 session before a catalyst date is dropped for H1/H3 but kept for H2.
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** — thin adapters only; any geometry logic must be imported from the existing study modules, never re-derived (if a study module lacks a needed helper, extract it there with its own test rather than duplicating).
- [ ] **Step 4: Tests + full suite pass.**
- [ ] **Step 5: Commit** `feat: add Phase-4 candidate adapters for H1/H3/H2`.

### Task 3: Validation-gate stats

**Files:**
- Create: `src/sts/study/h4_gate.py`
- Test: `tests/test_h4_gate.py`

**Interfaces:**
- Produces:
```python
def bootstrap_expectancy(r_values: list[float], n_boot: int = 5000, seed: int = 20260712) -> dict
    # -> {"mean", "lower90", "p_negative"}  (percentile bootstrap on mean R)
def year_stability(by_year: dict, neutral_band: float = 0.05) -> dict
    # -> {"years": {...}, "n_positive", "n_negative", "n_neutral", "worst_year"}
    # a year is neutral when |expectancy_r_net| <= neutral_band
def jitter_grid(params: dict, jitter_keys: dict[str, list]) -> list[dict]
    # cartesian one-at-a-time perturbations (each key varied alone, others at locked value)
```

- [ ] **Step 1: Failing tests** — bootstrap on a known constant array returns mean exactly and lower90==mean; seed determinism; year classification incl. neutral-band edges; jitter grid size = Σ len(values) and each dict differs from base in exactly one key.
- [ ] **Step 2: Verify FAIL.** **Step 3: Implement.** **Step 4: Pass + full suite.** **Step 5: Commit** `feat: add Phase-4 validation-gate stats`.

### Task 4: Runner CLI

**Files:**
- Create: `scripts/run_h4_study.py`
- Test: smoke via `--dry-run` (mirrors `run_h1_study.py` conventions: ROOT/sys.path shim, StudyStore load, argparse).

**Interfaces:**
- Consumes: Tasks 1–3, `StudyStore`, `calendar`, `CatalystCalendar`.
- CLI: `run_h4_study.py --family {h1,h3,h2,combined} [--oos-start 2024-01-01] [--dry-run]`.

Behavior: loads roster frames; builds candidates (combined = concatenation of all three families, same priority rule — family never enters the tie-break); runs both cost arms; runs jitter arms (base costs only) per `FAMILY_PARAMS` and a prereg-named jitter spec; computes gate stats; writes `runs/h4/<family>/report.json` with `bars` (machine-checkable: net_return>0, max_drawdown<=0.25, avg_deployed>=0.20) and `slices` (by_year, cost arms, jitter table, SPY buy-and-hold reference over the same window) — **year-stability stays analyst-judged from slices, exactly like Phase 3; do not put it in `bars`** (see memory: bars array is not the governing record, keep the shape consistent). Resumable: existing `report.json` for the wall → skip with a log line. Logs start/end/elapsed per stage to stderr.

- [ ] **Step 1: Implement** (conventions copied from `run_h1_study.py`). **Step 2: `--dry-run` smoke passes for all four families.** **Step 3: Commit** `feat: add Phase-4 portfolio study runner`.

### Task 5: Lock family preregs (BEFORE any run)

**Files:** `docs/preregs/2026-07-12_h4-portfolio-h1.md`, `..._h4-portfolio-h3.md`, `..._h4-portfolio-h2.md` (PREREG_TEMPLATE.md shape).

Each prereg locks, blind to any Phase-4 result: the simulator semantics of Task 1 (by reference to the module docstring at a named commit), the family's locked params, wall 2024-01-01, the four absolute bars (net>0 base-arm, DD≤25%, avg deployed≥20%, year stability with ±0.05R neutral band analyst-judged), both cost arms, the jitter spec (which keys, which values), bootstrap seed 20260712, SPY-reference-only clause, the catalyst embargo applying to all three families (F1 correction), same-session re-entry after an exit being permitted (mechanical consequence of exits-first ordering; review finding F2), and H3's consumed-OOS caveat carried forward. Rubric maps to PROCEED/PARK/STOP identically to Phase 3.

- [ ] **Step 1: Write all three preregs.** **Step 2: Commit as a lock** (`chore: lock H4 family preregs (wall 2024-01-01) before any Phase-4 run`) — this commit must precede any commit containing Phase-4 run artifacts.

### Task 6: Run family studies, report

- [ ] **Step 1:** `mkdir -p runs/h4 && nohup caffeinate -i .venv/bin/python scripts/run_h4_study.py --family h1 >> runs/h4/run.log 2>&1` sequentially for h1, h3, h2 (or a small sequential wrapper mirroring `run_all_studies.py`); confirm start via log tail; monitor.
- [ ] **Step 2:** Present each family's locked bars + slices to the user. **STOP — no verdicts written; the user judges** (verdict-override memory).

### Task 7 (after user verdicts): Combined-book prereg + run

Same shape: lock `..._h4-portfolio-combined.md` (blind to combined results; may cite family results since they're already open), run `--family combined`, report, user judges. H6 confluence stretch is out of scope for this plan — separate prereg if pursued.

## Self-Review notes

- Spec coverage: sizing/caps (T1), slot contention (T1.3), cost arms (T1/T4), absolute bars (globals, T4/T5), gate-v2 stats — bootstrap/year-band/jitter (T3), fold≫hold satisfied by year folds vs 15-session hold, SPY reference (T4), prereg+review gate (T5, review at execution via Opus per workflow), per-family-then-combined sequencing (T6/T7).
- Types consistent: candidate dict defined once (T1) and referenced by T2/T4; `FAMILY_PARAMS` produced T2, consumed T4.
- Known open point deferred deliberately: exact jitter keys/values per family are chosen while writing T5 preregs (blind — jitter of *locked* params can be named without seeing results).
