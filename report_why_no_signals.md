# Why the forward system has never emitted a signal

**Review date:** 2026-07-26
**Scope:** repository design, signal generation, production VM state/logs, tests, deployment, and the research-to-forward handoff.
**Historical status:** diagnosis retained; it is not an active plan.

## Executive conclusion

The vision is not what prevented signals. The forward pipeline contains a deterministic research/live adapter mismatch that makes current-session candidates unreachable.

The EOD job correctly fetches bars only through the latest completed session and asks for events whose `signal_date == asof`. It then calls the Phase-4 **backtest candidate adapter**. That adapter will only return an event after it reads the **next session's open** to construct entry geometry. On a live EOD run, that next bar does not exist yet. Every otherwise valid H1 or H2 event is therefore discarded before ranking, embargo, sizing, book limits, journaling, or alerts see it.

The decisive chain is:

1. `forward_eod.py` resolves `asof` to the last completed session and loads the cache.
2. `pipeline._default_candidate_source()` requests H1/H2 candidates in `[asof, asof + 1 day)`.
3. `h4_candidates` finds signal events, then calls `h1_events.entry_geometry()`.
4. `entry_geometry()` sets `entry_iloc = signal_iloc + 1` and returns `None` if that row is absent.
5. Both H1 and H2 adapters silently `continue` when geometry is `None`.
6. `generate_signals()` receives empty raw queues, so it reports `0 queued, 0 skipped`.

For a fresh symbol, `asof` is its last cached row and `signal_iloc + 1` cannot exist. For a stale/failed symbol, the `asof` signal bar itself does not exist. There is therefore no normal live-data state in which the current implementation can emit a current-session signal.

This is an implementation violation of the already-locked design, not a request to loosen the strategy. The Phase-5 implementation plan explicitly recognized that next-open geometry is unavailable at EOD and instructed the live path to construct provisional geometry from the signal close/ATR, then re-anchor it at the actual next-session open. The implementation added the provisional-geometry function, but calls it only **after** the backtest adapter has already discarded the event.

## Production evidence

The production writer is running on the documented `sts-forward` VM. Read-only inspection on 2026-07-26 found:

- VM state: running.
- Cron entries: present for EOD, fill, and monitor at the documented PT times.
- Successful EOD sessions: 2026-07-13 through 2026-07-24 (10 consecutive market sessions in the inspected logs), plus an `upkeep_done` record for 2026-07-10.
- Every inspected EOD run: `0 queued, 0 skipped`.
- Signal-generation runtime: approximately 31–34 minutes every night, so the detector code did run; this was not an immediate crash or disabled stage.
- Fetch coverage: normally 228–247 of 250 frames updated on a run. Per-symbol Yahoo/quality failures occurred, but there was still a broad fresh roster.
- `ledger/h1.jsonl`: 0 bytes.
- `ledger/h2.jsonl`: 0 bytes.
- `ledger/signals.jsonl`: only `upkeep_done` records; no `candidate`, `skip`, or monitor-entry records.
- Morning fill logs: 0 candidates to fill on every inspected session.
- Equity journal exists and updates, confirming the scheduled jobs and ledger mounts are active.

This rules out several alternative explanations:

- **Not merely a Discord problem:** there are no candidate records in the source-of-truth signal journal.
- **Not book capacity:** empty books have all eight slots and all deployment room.
- **Not throttling:** no candidates reached the throttle, and `skipped` remained zero.
- **Not the earnings embargo:** the auto calendar is symbol/date-specific and fail-open; more importantly, the current-session event is discarded for missing future geometry before the adapter reaches its embargo check.
- **Not one bad market day:** the same outcome repeated across every production session.
- **Not a total data outage:** most of the 250-symbol roster updated each day.
- **Not an H3 expectation mismatch:** Phase 5 intentionally runs H1 and H2 only; H3 was not promoted into this forward book.

The especially useful operational clue is `0 queued, 0 skipped`. Strict risk or portfolio rules would create skips. Zero of both means the candidate source itself returned nothing.

The historical expression was not designed to be this silent. H1-4b recorded 3,207 raw candidates and 450 taken trades over 631 OOS sessions (`runs/h4b/h1/report.json`); H2 recorded 199 taken trades over the same 631-session window (`runs/h4/h2/report.json`). Those rates do not guarantee a trade in any particular short live window, but they make candidate-stage observability and a consecutive-zero health alarm essential.

## Exact root cause with code pointers

### 1. Live EOD correctly stops at the completed bar

`scripts/forward_eod.py:173-199` resolves `asof`, fetches through it, and loads `StudyStore`.

`src/sts/data/study_store.py:38-42` explicitly truncates anything after the last completed session. That is the correct anti-lookahead behavior.

### 2. The live pipeline asks a backtest adapter for today's signals

`src/sts/forward/pipeline.py:148-156` does:

```python
oos_start = asof
oos_end = asof + dt.timedelta(days=1)
candidates_for("h2", prices, oos_start, oos_end, catalyst)
candidates_for("h1", prices, oos_start, oos_end, catalyst)
```

This asks for events on the just-completed signal session, which is also correct.

### 3. The adapter requires tomorrow's open before returning the event

For H1, `src/sts/study/h4_candidates.py:117-132` detects the event but then calls `entry_geometry()` and drops it when geometry is unavailable.

For H2, `src/sts/study/h4_candidates.py:187-208` selects a top-decile reaction event, calls the same `entry_geometry()`, and drops it when geometry is unavailable.

`src/sts/study/h1_events.py:51-84` defines the backtest geometry:

```python
entry_iloc = sig_iloc + 1
if entry_iloc >= len(idx):
    return None
entry = float(df["open"].iloc[entry_iloc])
```

That behavior is correct for a historical backtest adapter: a backtest candidate is not tradable without a modeled next-open fill. It is incorrect as the first stage of a live EOD detector, where that open necessarily belongs to the future.

### 4. The intended live-safe geometry exists, but it is downstream of the discard

`src/sts/forward/pipeline.py:169-185` computes provisional close/ATR/stop/target using only the signal bar. This is exactly the information available at EOD.

But `generate_signals()` first calls the backtest adapter at `src/sts/forward/pipeline.py:195`. The provisional function is reached later at `src/sts/forward/pipeline.py:223-227`, after the raw adapter has already returned an empty list.

So the implementation has the right live-safe second half attached to an impossible first half.

### 5. The morning fill path already performs the correct final re-anchoring

`scripts/forward_fill.py:166-181` obtains the actual next-session open, re-anchors the 2×ATR stop and target to that fill, and re-sizes against current book state.

This means fixing EOD detection does not require changing the strategy, risk multiples, or fill convention. The required division is:

- EOD: detect and rank using completed information; record signal-bar ATR and provisional display geometry.
- Next open: observe the actual open; compute final entry/stop/target/size.

That is also what the removed legacy forward specification required.

## The design document already anticipated this bug

The removed legacy Phase-5 specification was unusually explicit:

- the live path cannot depend on next-bar geometry and must compute provisional signal-close/ATR geometry;
- the fill job must re-anchor at the actual open.

The prose at lines 180–184 contains the required design, but `pipeline._default_candidate_source()` still reuses `candidates_for()` as if it could return the underlying signal without geometry. It cannot.

This was a handoff failure between:

- a backtest adapter whose contract is “signal plus known historical fill geometry”, and
- a live detector whose contract must be “signal facts now, fill geometry later”.

## Why the tests passed

The tests validate components around the broken seam but do not exercise that seam in a live-equivalent state.

### Pipeline tests bypass the real candidate source

`tests/forward/test_pipeline.py:210-335` injects a custom `candidate_source` containing already-built candidate dictionaries. These tests cover H2 priority, H1 ranking/throttle, duplicate symbols, deploy sizing, and embargo behavior, but they bypass `_default_candidate_source()` and the backtest adapter entirely.

### Candidate-adapter tests include future padding

`tests/test_h4_candidates.py:55-79` verifies that an H1 candidate's entry equals the next bar's open. The synthetic frame deliberately includes trailing bars after the event. This is correct for the Phase-4 adapter but says nothing about a signal on the final available bar.

There is no test asserting:

> An H1/H2 event on the last completed cached bar is returned to the EOD pipeline even though the next bar does not yet exist.

### EOD tests normalize an empty latest-bar queue

`tests/forward/test_eod_script.py:89-108` explicitly checks the “No candidates” alert on a flat latest-bar frame. It verifies outage visibility, not candidate reachability.

There is no production-like EOD test with a valid detector event on the last row.

### The manual rehearsal was historical, not live-equivalent

The legacy rehearsal used a prior Friday followed by the next session's fill.
When a historical `asof` is used against a cache that already contains later
bars, `entry_geometry()` can see the next session and the broken adapter
appears to work.

A valid live rehearsal must truncate every frame exactly at `asof` before signal generation.

### No observability assertion exists between detection and portfolio gates

The backtest adapter silently drops:

- no-next-bar geometry,
- invalid entry geometry,
- insufficient ATR,
- catalyst embargoes.

The forward pipeline only counts records returned by that adapter. It cannot report whether detectors found events that the adapter later discarded. That is why production says `0 skipped` instead of exposing `detected > 0, unavailable_future_fill > 0`.

## Secondary correctness and operational findings

These did not cause the repeated successful `0 queued` runs, but they can independently lose signals or make diagnosis harder.

### P0: completion is checkpointed before signal generation is complete

`scripts/forward_eod.py:127-129` defines completion as:

```python
asof in ledger.processed_upkeep_dates() and bool(ledger.signals(asof))
```

`run_upkeep()` appends an `upkeep_done` signal record at `src/sts/forward/pipeline.py:131-143`. Therefore, immediately after upkeep:

- the date is in `processed_upkeep_dates()`, and
- `ledger.signals(asof)` is non-empty because it contains `upkeep_done`.

If the process crashes after upkeep but before or during signal generation, the next run treats the date as fully processed and skips stages 1–5. A partially written candidate queue can also be mistaken for a complete queue.

There must be a distinct `signals_done` control record, written only after the full per-family/per-book walk completes. `_already_done()` should require both `upkeep_done` and `signals_done`.

### P1: the signal stage is much more expensive than a daily scan needs to be

The production signal stage takes roughly 31–34 minutes. H2 rebuilds historical earnings-reaction events and causal deciles across the entire cache on every EOD call (`src/sts/study/h4_candidates.py:169-208`), even though only the newest session can be emitted.

This is not the zero-signal cause, but it:

- lengthens the failure window,
- increases exposure to Yahoo/cache inconsistencies,
- makes retries expensive,
- discourages shadow/reconciliation runs,
- hides quick fail-fast invariants.

Correctness should be fixed first. Then H2's causal state can be incrementally persisted or precomputed without changing its definition.

### P1: internal adapter drops are silent

The adapter should return structured outcomes or counters for:

- detector events,
- selected events,
- missing signal bar,
- ATR not warm/invalid,
- future entry geometry unavailable,
- catalyst embargo,
- final live candidates.

The nightly status should show those counts by family. A streak such as “detected > 0 but emitted = 0” should page immediately.

### P1: per-symbol fetch failures need a visible stale-roster summary

Production logs show 3–22 per-session fetch/quality failures, often due to inconsistent Yahoo OHLC ranges. The pipeline correctly continues with the old frame, so this is not the universal blocker. However, the nightly report should state:

- fresh through `asof`,
- stale by one session,
- stale by more than one session,
- missing/unreadable,
- quality-gate failure reasons.

After the primary fix, a live detector should only consider a symbol for `asof` when that exact completed bar exists.

### P2: documentation names the study store as non-trading data

`src/sts/data/study_store.py:1-17` says the store feeds evidence only and that its symbols are never traded, while the forward jobs use it as their production price source. The actual implementation is coherent enough to run, but this stale contract makes architectural reviews harder.

## High-level code design map

This is the recommended starting map for future work.

### Product and evidence contracts

- `docs/VISION.md:1-55` — product goal, success criteria, evidence principles.
- `docs/VISION.md:70-112` — ratified capital, sizing, exits, catalyst, universe, and process rules.

### Data and calendar

- `configs/study_roster.yaml` — 250-symbol research/forward roster.
- `scripts/forward_eod.py:68-124` — roster loading, incremental fetch, earnings refresh.
- `src/sts/data/fetch.py:25-55` — adjusted Yahoo daily download and normalization.
- `src/sts/data/study_store.py:35-115` — parquet cache, incomplete-bar truncation, quality-before-atomic-write.
- `src/sts/data/quality.py:35-79` — OHLCV, index, missing-session, and warning rules.
- `src/sts/calendar.py:21-44` — NYSE sessions and last-completed-session logic.
- `src/sts/catalyst.py:123-234` — merged earnings/curated calendar and session-distance embargo.

### Signal definitions

- **H1 trend pullback:** `src/sts/signals/trend_pullback.py:43-120`
  - completed-week uptrend,
  - RSI(2) first oversold episode below 10,
  - close reclaim above the prior day's high within 10 sessions,
  - rank fields: seed status, RSI depth, reclaim wait.
- **H2 PEAD proxy:** `src/sts/study/h2_events.py:68-185`
  - first qualifying post-earnings high-volume reaction session,
  - volume at least 1.5× the trailing 20-session median,
  - causal trailing-252-session top-decile return score,
  - at least 100 comparison events,
  - enter at reaction-session + 1 open.
- `src/sts/weekly.py:50-139` — weekly aggregation and daily alignment with incomplete-week protection.

### Research adapters and portfolio simulation

- `src/sts/study/h1_events.py:51-123` — historical next-open geometry and single-event simulation.
- `src/sts/study/h4_candidates.py:70-233` — locked family parameters and Phase-4 candidate adapters.
- `src/sts/portfolio.py:75-321` — historical book simulation, entry ordering, slots, throttle, daily exits, equity, and summaries.
- `runs/h4b/h1/report.json` — promoted H1 ranked/throttled expression.
- `runs/h4/h2/report.json` — promoted H2 solo expression.
- `runs/h4/h3/report.json` — H3 portfolio failure; explains its absence from Phase 5.

### Forward EOD orchestration

- `scripts/forward_eod.py:148-249` — job orchestration and error handling.
- `src/sts/forward/pipeline.py:50-145` — exit upkeep, equity snapshots, and upkeep checkpoint.
- `src/sts/forward/pipeline.py:148-358` — live candidate sourcing, ranking, gates, provisional sizing, and signal journaling.
- `src/sts/forward/book.py:30-138` — virtual-book replay, entry limits, sizing, and H1 throttle.

### Fill, exits, state, and alerts

- `scripts/forward_fill.py:102-244` — find next-session candidates, obtain open, re-anchor geometry, re-size, and append open rows.
- `src/sts/forward/broker.py:23-62` — cost model and stub open-fill broker.
- `src/sts/risk.py:39-167` — charter constants, ATR geometry, and position sizing.
- `src/sts/risk.py:170-246` — position invariants and stop/target/time exit order.
- `src/sts/forward/ledger.py:24-228` — journals, schemas, deterministic IDs, latest-state replay, signals, and checkpoints.
- `src/sts/forward/journal.py:24-69` — durable append/read primitive.
- `src/sts/forward/alerts.py:28-97` — Discord delivery and formatting.
- `scripts/forward_monitor.py:99-185` — advisory-only intraday monitoring of open positions.

### Persistence and production

- `src/sts/forward/sync.py:124-255` — merge-only Drive ledger sync and artifact upload.
- `deploy/docker-compose.yml:12-54` — one-shot production services and mounted state.
- `deploy/deploy.sh:111-200` — state/config shipping, image pull, and cron installation.
- `Dockerfile:1-29` — production image contents.

## Intended end-to-end flow

```text
17:30 PT cron
  -> forward_eod.py
     -> fetch/validate/cache completed daily bars
     -> replay exits and write equity/upkeep_done
     -> detect today's H2 and H1 signal facts
     -> rank H2 first, then ranked H1
     -> apply embargo, duplicate, slot, throttle, and sizing checks
     -> append candidate/skip records
     -> append signals_done
     -> Discord status
     -> merge-only Drive sync

Next session 06:31 PT
  -> forward_fill.py
     -> select yesterday's candidates
     -> read actual session open
     -> re-anchor stop/target with signal-bar ATR
     -> re-size/re-check current book
     -> append open position row

Later EOD sessions
  -> run_upkeep()
     -> replay completed bars through stop/target/15-session time exit
     -> append closed row and equity snapshot
```

The current break occurs at “detect today's signal facts”: it instead requests a fully filled historical candidate.

## Recommended fix, without changing the vision

### P0: separate signal identity from historical fill geometry

Create one shared, causal signal-selection layer per family:

```text
H1/H2 raw data
  -> selected signal fact
     {family, symbol, signal_date, rank fields, signal-bar ATR}
```

Then use two consumers:

- **Backtest consumer:** attach next bar's historical open through `entry_geometry()`.
- **Forward consumer:** keep provisional close/ATR geometry at EOD; attach the real open in `forward_fill.py`.

Do not duplicate the detector thresholds or ranking rules. Refactor the existing adapters so both consumers share signal selection and differ only in how/when fill geometry is attached.

### P0: add a real signal-stage checkpoint

Add `kind="signals_done"` to the signal schema. Write it after both books have been completely walked. Require:

```text
upkeep_done(asof) AND signals_done(asof)
```

before the EOD job takes its no-op path.

### P0: add regression tests at the actual causal boundary

Required tests:

1. H1 event on the final cached bar, no future bar: EOD emits a candidate.
2. H2 selected reaction event on the final cached bar, no future bar: EOD emits a candidate.
3. The same frames with a next bar: backtest and forward paths agree on signal identity, rank fields, signal ATR, and final fill-anchored stop/target.
4. Production-like `generate_signals()` using its default source, not an injected source.
5. Every frame explicitly truncated at `asof`.
6. Crash after `upkeep_done` but before `signals_done`: retry resumes signal generation.
7. Crash after a partial candidate queue: retry safely completes the queue without duplicates.
8. A completed signal stage with genuinely zero events writes `signals_done`, making “zero” distinguishable from “not run”.

### P1: expose stage counts and zero-streak alarms

Nightly output should include:

```text
H1 detected / selected / embargoed / queued / skipped-by-reason
H2 detected / selected / embargoed / queued / skipped-by-reason
fresh / stale / missing symbols
signal stage completed: yes/no
```

Alert after an implausible consecutive-zero streak based on the historical fire rate. This is a pipeline-health alarm, not a forced trade and not a strategy relaxation.

### P1: replay only for incident assessment

After fixing the code, replay 2026-07-10 through the deployment date against data truncated at each historical `asof` to enumerate signals the broken system would have emitted.

Do **not** add retrospective paper fills to the judged forward ledger. They were not observed/acted on prospectively. Record the outage and missed signals in the deviations log, preserve the append-only ledgers, and restart the clean forward observation window from the first fixed production session.

### P1: optimize H2 only after parity is locked

Persist or incrementally update reaction/decile state so a one-session EOD scan does not rebuild the full history nightly. Before promotion, prove the incremental result is identical to the existing causal full-history calculation.

## Does the vision need to change?

No—not to solve the absence of signals.

The locked vision already says:

- completed daily-bar signal,
- next-session-open entry,
- signal-bar ATR risk,
- actual-open re-anchoring in forward paper,
- no lookahead.

The implementation currently violates that contract by demanding the next open during signal detection. Fixing the boundary restores the vision; it does not loosen it.

There are separate evidence cautions worth retaining:

- The unranked H1 portfolio expression failed before H1-4b ranking/throttling was promoted.
- H2 was positive over the full OOS window but negative in the 2026 slice in `runs/h4/h2/report.json`.
- The original combined H1/H2 book had negative mean trade expectancy despite positive net return in `runs/h4/combined/report.json`.
- The forward study exists precisely because the historical window is short, bull-heavy, and partially consumed.

Those are reasons to keep the forward-paper test strict, not reasons for a system that can never enter the test.

## Decision summary

1. **Root cause:** confirmed deterministic live/backtest adapter mismatch.
2. **Vision change required:** no.
3. **Strategy parameter change required:** no.
4. **Code change required:** yes, P0 before another judged session.
5. **Forward evidence accrued so far:** none; the system was structurally unable to observe eligible live candidates.
6. **Forward clock after repair:** restart from the first verified fixed session and log the outage/deviation.
7. **Next implementation gate:** causal last-bar integration tests plus a production shadow run showing non-empty detector-stage counts even on a zero-trade night.
