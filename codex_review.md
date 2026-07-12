# Codex repository review — 2026-07-11

> **Fix status (updated 2026-07-11 — Claude):** 5 code-correctness bugs fixed + tests
> (pytest 180 passed). Done: Fix-1 (entry-bar risk), H2 (auto-earnings block_entry only),
> H3 adapter (structure levels), fail-closed config, Fix-3 sidecar bug. Deferred (research /
> process, need decisions): Fix-2 evidence contract (**slippage assumed 0 for now**),
> Fix-3 remainder, Fix-4, Fix-5, hypothesis changes, docs cleanup. See tags below.

## Verdict

The project is aligned in direction: a small modular research engine, swing-native risk,
causal weekly bars, pre-registration, and edge-before-ops are the right design. Phase 0 is
substantively ratified, and the risk/weekly parts of Phase 2 are strong. However, Phase 1 and
the event-simulator part of Phase 2 should be reopened before Phase 3; the current harness
cannot yet produce the net, auditable evidence required by its own charter.

## Fix before Phase 3

1. **✅ DONE — Activate risk on the fill session.** `eventsim._sim_one` starts management at
   `entry_iloc + 1` (`src/sts/eventsim.py:210`), while the charter requires a hard stop *at
   entry* (`docs/VISION.md:66`). A hand-traced case where the entry bar crosses the stop and
   the next bar reaches the target currently reports **+1R instead of -1R**. Manage the entry
   bar immediately after the next-open fill, with the existing conservative stop-before-target
   rule, and add a regression test. Amend the Phase-2 ledger claim that skipping this bar is
   merely conservative; it can be optimistic.

2. **⏸ DEFERRED (slippage assumed 0 for now) — Implement the evidence contract, not just gross R.** The simulator explicitly has no
   slippage or commissions (`src/sts/eventsim.py:18`), yet every promotion bar requires base
   and 2x friction (`docs/VISION.md:17`, `docs/PREREG_TEMPLATE.md:50`). It also marks an
   immature trade to the last close and includes that partial return in expectancy
   (`src/sts/eventsim.py:225`), which can bias the most recent OOS events. Before studies:

   - define whether the bps assumption is execution slippage or an additional fee;
   - return gross, base-cost, and 2x-cost R using charter-sized reference positions so the
     $1/order term is meaningful;
   - exclude right-censored events from judged `n` and expectancy (report them as immature);
   - emit auditable per-event rows: symbol, signal/entry/exit dates, prices, exit reason,
     initial risk, gross/net R, hold, cap/clamp flags, and skip reason. The current summary-only
     API cannot produce the required regime/liquidity slices or independently reproduce a
     verdict.

3. **✅ RESOLVED — Close Phase 1 with a reproducible roster and real quality gate.** Fetch
   writes now route through `StudyStore.write` (validate + truncate-incomplete + atomic+fsync);
   freshness is session-based (`sts.calendar.last_completed_session()` minus a 5-session
   allowance) instead of a fixed calendar year; the sidecar `set.discard` bug was already fixed.
   The roster reached 250 symbols, a second run confirmed true no-op idempotence, and
   `configs/study_roster.yaml` (exact membership, source, eligibility, seeds/anchors, rationale)
   plus `configs/study_roster_manifest.json` (per-symbol first/last session, adjustment basis,
   fetch timestamp, file sha256) are committed to git as the reproducibility contract. See
   `decisions.md` 2026-07-11 entry. Script now has tests (`tests/test_fetch_study_roster.py`).

4. **⏸ DEFERRED — Calibrate the statistical null on real market data.** The synthetic zero-drift negative
   control is a useful arithmetic test, but a positive raw return is expected from random
   long entries in an equity market with positive drift. Add symbol/year/regime-matched random
   entry controls (and SPY- or beta-adjusted returns as a sensitivity). Judge Layer A on uplift
   over that matched null as well as absolute return. Preserve per-event rows so inference can
   cluster by signal date and symbol; overlapping events should have a one-active-event-per-
   symbol sensitivity rather than being treated as independent observations.

5. **⏸ DEFERRED — Make the preregistration actually constrain search.** H1's stated grid is already 54
   cells, before resolving ambiguous choices such as 20 vs 40 weeks, 3 vs 5 down closes, and
   10 vs 20-day exits (`docs/HYPOTHESES.md:46-64`). Lock one executable primary cell; secondary
   cells are descriptive and cannot PROCEED without a fresh prereg. State which bars use IS,
   OOS, or both, how partial 2025/2026 years vote, and how multiplicity is controlled. The
   current “no year >40%” rule is not interpretable if it is applied only to roughly two
   partial OOS years.

## Fix before the relevant family

- **H2 earnings:** ✅ DONE (block_entry-only) / ⏸ DEFERRED (rest). Auto-fetched earnings currently inherit `exit_before` even though the
  charter permits holding through earnings (`src/sts/catalyst.py:46-59` vs
  `docs/VISION.md:76-79`). Make auto earnings `block_entry` only. **[DONE + test.]** Preserve announcement time
  and BMO/AMC status; stripping timestamps to a date cannot identify the “first post-report
  session.” Use a causal, pre-wall/frozen reaction threshold—full-quarter or full-sample
  deciles would look ahead. The present cache covers only 12 symbols (9 with dates), so version
  and validate a 250-name event dataset before preregistering H2.

- **H3 structure exits:** ◐ PARTIAL. The known `swing_low`/`swing_high` versus
  `stop_level`/`target_level` mismatch skips every structure-mode event. Define a detector-to-
  risk adapter **[DONE: `eventsim._structure_level` maps swing_low→stop / swing_high→target,
  explicit `*_level` still wins; + test]**, test each H3 family end-to-end, and report skip
  reasons/rates before running the study **[DEFERRED — needs per-event rows from Fix-2]**; do
  not silently select the ATR-capable subset.

- **Fail closed on study configuration:** ◐ PARTIAL. Invalid `stop_mode`/`target_mode` values fall through
  to ATR, and an unknown squeeze `trend_filter` removes the filter. Reject unknown keys and
  enum values so a typo cannot change the registered hypothesis while retaining its label.
  **[DONE: unknown enum VALUES for `stop_mode`/`target_mode` (eventsim) and `trend_filter`
  (squeeze) now raise ValueError + tests. DEFERRED: rejecting unknown param KEYS across all
  detectors — larger contract change.]**

## Hypothesis changes — ⏸ DEFERRED (research decisions)

1. **Add the missing core ablation, not another chart pattern.** For every H1 daily trigger,
   compare the identical trigger unfiltered versus the preregistered weekly condition. The
   core multi-timeframe claim passes only if the higher-timeframe condition adds net
   expectancy/stability over the matched daily-only control; absolute positivity alone does
   not test the thesis.

2. **One worthwhile new exploratory family: news-adjusted intraday liquidity-shock
   reversal.** Mechanically define a large negative open-to-close, market/sector-residual move,
   exclude earnings/news dates, enter next open, and test 3/5/10-session recovery. Pre-register
   the prediction that high-volatility shocks reverse faster while low-turnover shocks persist
   longer. This is daily-OHLC compatible and has a clearer mechanism than FVG/island/Wyckoff:
   temporary inventory/liquidity pressure. Evidence: [Dai et al., *Reversals and the Returns to
   Liquidity Provision*](https://www.nber.org/papers/w30917) and [Miwa, *Short-Term Return
   Reversals and Intraday Transactions*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3174484).
   Treat it as the **single** exploratory-round candidate (or choose H4 instead), not an extra
   lottery ticket after other exploratory failures.

3. **Constrain H4/H6.** H4's published result uses share turnover; dollar volume is not the
   same variable, so obtain point-in-time shares outstanding or rename the hypothesis to a
   within-symbol relative-volume effect. Fold H6a/H6b into H1/H3 as secondary entry variants,
   and keep H6c/H6d out of the current Phase-3 budget unless a single mechanical definition is
   chosen now. Require an event-overlap/novelty bar so a relabeled H1 event family is not
   counted as new evidence. Four H6 setups cannot collectively count as “one exploratory
   round.”

## Documentation and reproducibility cleanup — ⏸ DEFERRED

- Update `docs/README.md:24-44` (it still says the charter is proposed), remove or mark H5
  rejected (shorting is permanently off), and fix the prereg's claim that `universe.yaml` is
  the 250-name roster. Separate the 100-name mutable watchlist contract from the research
  roster.
- Ratify the currently missing drawdown cap and Phase-4 exposure floor before seeing Phase-3
  winners (`docs/VISION.md:24`, `docs/PLAN.md:73-74`).
- Add a dependency lock and stamp Python/package versions plus git/data hashes into every
  artifact. Clean stale `stm`, `CLAUDE.md`, Phase-9/10, missing-transcript, Fibonacci-target,
  and 2R-fallback references; they contradict the repo's self-contained claim and obscure the
  live contracts.

## Verification performed

- `pytest -q`: **176 passed**.
- `compileall`: passed; `git diff --check`: passed before this report.
- Cache spot audit: 249 unique symbols, 2,037,117 rows, no NaN/index structural failures;
  all names passed the ratified price and 20-session dollar-volume floors as of 2026-07-09.
- These green checks support the module mechanics, but they do not cover the Phase-3 validity
  gaps above.
