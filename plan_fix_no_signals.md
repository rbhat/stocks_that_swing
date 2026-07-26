# Plan: repair and validate the forward signal pipeline

**Prepared:** 2026-07-26
**Primary diagnosis:** `report_why_no_signals.md`
**Execution model:** localhost first; production only after every local correctness/parity gate passes.

## Outcome

Repair the research/live boundary so a valid H1 or H2 event on the latest completed bar can be queued at EOD without tomorrow's bar, filled at the actual next-session open, managed under the existing charter, and durably resumed after interruption.

This plan does **not** change:

- H1/H2 detector thresholds;
- H2 causal-decile definition;
- H2-before-H1 priority;
- H1 seed/RSI/reclaim ranking;
- H1 four-in-five-session throttle;
- 2×ATR stop/target;
- position sizing or book caps;
- next-session-open entry;
- catalyst rules;
- the paper-only vision.

## Non-negotiable safety rules

1. Preserve the user's existing dirty changes in `docs/VISION.md` and `deploy/open_remote.sh`.
2. Never write retrospective paper fills into the judged ledgers.
3. Use only `.scratch/` or a dedicated scratch ledger for local/replay work.
4. Keep the production VM as the sole writer; do not run laptop jobs against the production ledger.
5. Do not deploy until local unit, integration, causal replay, parity, and full-suite gates pass.
6. Do not loosen a strategy rule to make a test produce a signal.
7. Do not expose `.env`, webhook, rclone, service-account, or other secret contents in logs/output.
8. Use `ruff --fix`, as required by the repository instructions.
9. Do not call `gcloud` during development, testing, replay, or local audit. The first new `gcloud` call is allowed only after every localhost gate passes and Phase 9 production rollout begins.
10. At the end of every phase: save artifacts/results, run that phase's gate, and create a focused commit containing only that phase. Do not begin the next phase with uncommitted repair work.

## Target architecture

Split the current overloaded backtest-candidate contract into three explicit stages:

```text
family data
  -> selected signal fact (causal at signal-bar close)
  -> execution geometry
       backtest: known historical next open
       forward: actual next open observed by fill job
  -> portfolio/book gates and state
```

### Selected signal fact

The shared family-selection layer should return only information known at EOD:

```python
{
    "family": "h1" | "h2",
    "symbol": str,
    "signal_date": date,
    # H1 only:
    "is_seed": bool,
    "rsi2_at_trigger": float,
    "reclaim_wait_sessions": int,
}
```

It must not require:

- `entry_date`,
- tomorrow's open,
- final stop,
- final target.

### Backtest composition

`candidates_for()` remains the historical portfolio contract. It composes selected signal facts with `entry_geometry()` and applies the embargo using the historical entry date. Existing Phase-3/4 results must remain reproducible.

### Forward composition

The forward source consumes selected signal facts directly. `generate_signals()`:

- confirms the signal bar exists at `asof`;
- calculates signal-bar ATR;
- computes provisional display/sizing geometry from signal close;
- computes the calendar-true next entry session without reading its bar;
- journals embargo/book/throttle/size outcomes;
- stores ATR for the fill job.

`forward_fill.py` remains the authority for:

- observing the actual next-session open;
- re-anchoring stop/target from the stored signal ATR;
- current-state sizing and book re-check;
- writing the open ledger row.

## Work plan

### Phase 0 — Baseline and workspace protection

1. Read:
   - `report_why_no_signals.md`;
   - this plan;
   - `docs/VISION.md`;
   - the Phase-5 prereg;
   - `docs/FORWARD_OPS.md`.
2. Record `git status --short` and preserve all pre-existing changes.
3. Create the local environment if missing:

   ```sh
   uv venv --python 3.12 .venv
   make setup
   ```

4. Run the existing baseline:

   ```sh
   .venv/bin/python -m pytest -q
   ```

5. Build the ignored local `cache/` from the configured market-data sources if it is absent:

   ```sh
   make fetch-roster
   ```

   Fetch/refresh the local catalyst cache through the existing local catalyst path as needed for H2. Do not obtain development data through the production VM.
6. Reproduce the incident locally with data explicitly truncated at each test `asof`; save results under `.scratch/baseline/`.

**Gate:** existing tests pass, dirty user files are untouched, and baseline replay shows the current latest-bar adapter failure.

### Phase 1 — Add failing causal-boundary tests

Add red tests before implementation:

1. H1 event on the final cached bar with no next bar:
   - selected signal fact exists;
   - historical `candidates_for()` may correctly lack geometry;
   - forward `generate_signals()` must queue the fact.
2. H2 top-decile reaction event on the final cached bar with no next bar:
   - selected signal fact exists;
   - forward path queues it.
3. Default production candidate source:
   - no injected `candidate_source`;
   - all frames truncated to `asof`;
   - current-bar event reaches the forward walk.
4. A real zero-event session:
   - no candidate/skip rows;
   - explicit signal-stage completion record exists.
5. Signal identity parity:
   - when a next bar is later appended, backtest and forward selection agree on family/symbol/signal date and H1 rank fields.
6. Geometry parity:
   - with the same next-open price and signal ATR, fill-time stop/target match historical `entry_geometry()`.

Likely test locations:

- `tests/test_h4_candidates.py`;
- `tests/forward/test_pipeline.py`;
- `tests/forward/test_eod_script.py`;
- `tests/forward/test_fill.py`.

**Gate:** new tests fail for the expected reason, not fixture/setup errors.

### Phase 2 — Refactor family selection from geometry

1. Extract a public causal selection function from `src/sts/study/h4_candidates.py`, with a clear name such as `selected_signals_for()`.
2. H1 selection must reuse `detect_trend_pullback()` and carry the existing three rank fields unchanged.
3. H2 selection must reuse:
   - `load_earnings_dates()`;
   - `build_reaction_events()`;
   - `assign_deciles()`;
   - the locked `"top"` flag.
4. Keep catalyst filtering out of the raw signal-identity layer:
   - historical adapter applies it after historical `entry_date` is known;
   - forward pipeline applies it against the calendar-derived next session.
5. Rebuild existing `candidates_for()` on top of selected signal facts plus `entry_geometry()`.
6. Keep H3 behavior unchanged unless a small shared refactor is necessary; H3 is not part of the forward book.
7. Fail closed on unknown family/contract values.

**Gate:** historical adapter tests pass unchanged, new selected-signal tests pass, and no strategy constants move.

### Phase 3 — Connect the forward EOD path

1. Change `pipeline._default_candidate_source()` to use causal selected signal facts, not fully formed Phase-4 candidates.
2. Keep `_provisional_geometry()` as the forward-only signal-close/ATR calculation.
3. Validate exact `asof` bar presence before provisional geometry.
4. Apply forward embargo using the calendar-true next session already calculated by `generate_signals()`.
5. Preserve:
   - H2-first ordering;
   - H1 rank key;
   - shared and H1-solo walks;
   - throttle and all book limits;
   - stored `atr_sig`;
   - next-open fill behavior.
6. Return structured counts by family/stage:
   - detected/selected;
   - missing/stale signal bar;
   - invalid ATR/geometry;
   - embargoed;
   - queued;
   - skipped by portfolio reason.

**Gate:** final-bar H1/H2 integration tests pass with no future bar present.

### Phase 4 — Make EOD resumption correct

Add explicit stage records:

- `upkeep_done`;
- `signals_done`;
- `notifications_done` (at-least-once alert completion).

Required changes:

1. Extend ledger signal kinds.
2. Fix local signal deduplication for control records with `entry_id=None`; include `kind` in their identity so `upkeep_done`, `signals_done`, and `notifications_done` can coexist.
3. Add ledger readers such as `processed_signal_dates()`/`processed_notification_dates()` rather than using generic `bool(signals(asof))`.
4. Write `signals_done` only after both books are fully walked.
5. On a partial retry:
   - recognize already-journaled candidate/skip outcomes;
   - reconstruct their provisional slot/notional/throttle effects exactly once;
   - continue the deterministic queue;
   - never let same-day existing candidates double-count against themselves;
   - return the complete day's journaled outcomes for notification.
6. If `signals_done` exists but `notifications_done` does not:
   - rebuild candidate/no-candidate/book-status notifications from the ledger;
   - send them at least once;
   - append `notifications_done`.
7. Continue to run sync on every invocation.

Required crash tests:

1. crash after `upkeep_done`, before first candidate;
2. crash after one H2 candidate;
3. crash midway through H1 shared-book queue;
4. crash between shared and H1-solo books;
5. crash after `signals_done`, before notifications;
6. complete zero-event night;
7. complete night re-run is a no-op except sync;
8. candidate IDs and throttle counts remain identical to an uninterrupted run.

**Gate:** interrupted and uninterrupted runs produce identical ledger state.

### Phase 5 — Add durable observability

1. Include one nightly summary with:
   - fresh/stale/missing symbol counts;
   - per-family detected/selected/queued/skip counts;
   - stage completion markers;
   - runtime by stage.
2. Journal the signal-stage summary with `signals_done`.
3. Add a consecutive-zero health warning:
   - warning only;
   - never manufactures a trade;
   - threshold documented and configurable as an operational setting, not a strategy setting.
4. Distinguish:
   - legitimate `selected=0`;
   - selected but embargoed;
   - selected but book-blocked;
   - signal stage failed/not completed.
5. Make per-symbol staleness visible.

**Gate:** a zero-trade night is diagnosable from one status record without reading raw logs.

### Phase 6 — Localhost causal replay and full-flow rehearsal

Add or adapt a read-only audit runner that:

1. loads the locally fetched study/catalyst cache;
2. truncates every symbol frame to each historical `asof`;
3. runs 2026-07-10 through the latest completed production session;
4. records selected H1/H2 facts and forward outcomes;
5. never writes to the production ledger;
6. saves machine-readable and human-readable results under `.scratch/`.

Run:

1. causal replay for every incident date;
2. one uninterrupted EOD sequence into `.scratch/ledger-rehearsal-v2`;
3. the same sequence with injected crash/retry points;
4. fill jobs for emitted candidates using the next cached session's actual open;
5. upkeep through stop/target/time paths where enough bars exist;
6. same-date reruns for idempotency;
7. full suite:

   ```sh
   .venv/bin/python -m pytest -q
   .venv/bin/python -m ruff check --fix .
   .venv/bin/python -m pytest -q
   git diff --check
   ```

`git diff --check` may continue to report the user's pre-existing trailing whitespace in `docs/VISION.md`; do not edit that file unless explicitly needed for this repair.

**Gate:** all tests pass, replay exposes the missed-signal incident window, fill geometry matches the backtest convention, and scratch ledgers are deterministic across retries.

### Phase 7 — Evidence and operations documentation

1. Update `report_why_no_signals.md` with the exact fixed behavior and replay counts.
2. Append the implementation deviation/outage to the Phase-5 prereg:
   - incident window;
   - root cause;
   - no valid forward evidence accrued;
   - no retrospective fills;
   - forward clock restarts on the first verified fixed session.
3. Add a concise `decisions.md` incident entry without changing prior verdicts.
4. Update `docs/FORWARD_OPS.md` with:
   - `signals_done`/`notifications_done` health checks;
   - local causal replay command;
   - zero-streak response;
   - crash/retry behavior.
5. Correct the stale `StudyStore` “never traded” contract if that module remains the production source.

**Gate:** another engineer can operate and diagnose the pipeline from the docs alone.

### Phase 8 — Independent local audit before deployment

Audit:

1. no detector/rank/risk constants changed;
2. no lookahead in selected signal facts;
3. H2 deciles remain causal;
4. historical candidate/trade parity on representative/full windows;
5. forward candidate identity parity;
6. book ordering/throttle parity;
7. ledger compatibility and sync keys;
8. no secret exposure;
9. no production-ledger mutation;
10. all pre-existing user changes preserved.
11. no `gcloud` calls were made during Phases 0–8.

Confirm every completed phase has its own focused commit containing only that phase's repair, tests, artifacts, and relevant docs. Do not include unrelated dirty files.

**Gate:** audit is clean and the deployable commit SHA is known.

### Phase 9 — Production rollout

Only after all local gates pass:

1. Begin the first permitted `gcloud` interaction. Batch production inspection/deploy/verification commands where practical instead of repeatedly opening new remote sessions.
2. Confirm no cron job/container is active.
3. Record current production image digest and take a recoverable snapshot/copy of ledgers and logs without shortening or rewriting them.
4. Build/tag the image with the repair commit SHA; retain the previous digest for rollback.
5. Deploy using existing production secrets without printing/copying them into tracked files.
6. Verify the VM is running the intended image digest.
7. Run a read-only causal audit in production against the mounted cache.
8. Run a scratch-ledger EOD rehearsal inside the deployed image; do not point it at `~/sts/ledger`.
9. Let the scheduled production EOD job be the first writer of the repaired path.
10. Verify after that job:
   - `signals_done` exists;
   - `notifications_done` exists;
   - per-family counts are present;
   - candidate/skip totals reconcile;
   - sync succeeded.
11. Verify the next fill session:
    - candidates are discovered;
    - actual-open geometry is re-anchored;
    - open rows validate;
    - duplicate fills do not occur.

**Rollback:** restore the prior immutable image digest and cron configuration. Do not roll back or truncate ledgers; append-only state remains authoritative.

## Final acceptance criteria

The repair is complete only when all are true:

1. A valid H1 final-bar event queues without a future bar.
2. A valid H2 final-bar event queues without a future bar.
3. Historical backtest candidate behavior is unchanged.
4. Actual-open fill geometry matches the locked convention.
5. H2/H1 ordering, H1 ranking, and throttle are unchanged.
6. Crash/retry state equals uninterrupted state.
7. Zero-event completion is explicit.
8. Production status exposes detector and gate counts.
9. Incident dates are documented and never treated as valid forward evidence.
10. The forward-paper clock restarts on the first verified fixed production session.

## Out of scope unless a new decision is made

- changing the vision;
- changing H1/H2 thresholds or risk parameters;
- adding H3 or a new setup;
- real-money trading;
- real broker integration;
- retroactive paper fills;
- using the repair to reinterpret prior research verdicts.
