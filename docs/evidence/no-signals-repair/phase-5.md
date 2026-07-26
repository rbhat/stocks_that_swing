# Phase 5 — Durable EOD observability

The existing durable EOD markers now double as the status source of truth.
`signals_done` journals:

- roster freshness counts plus the exact fresh, stale, and missing symbols;
- the last cached session for every stale symbol;
- H2/H1 detected, selected, queued, embargoed, invalid-input, and
  book-skip counts;
- a distinct signal outcome (`selected_zero`, `selected_embargoed`,
  `selected_book_blocked`, `selected_data_rejected`, or `queued`);
- fetch, load, upkeep, and signal-stage runtimes.

After the complete at-least-once notification set succeeds,
`notifications_done` journals the single completed nightly status. It adds
all three completion markers, notification runtime, the adjacent-session
`selected=0` streak, its configured threshold, and any health warning. The
same summary is emitted in the nightly notification set. A missing
`signals_done` remains distinguishable as `signal_stage_incomplete`; it is
not counted as a legitimate zero-event session.

The default warning threshold is five adjacent completed sessions and is
configurable with `forward_eod.py --zero-streak-warning N` (`0` disables).
This is an operations-only setting: it does not modify a detector, rank,
embargo, sizing, throttle, risk, or book decision and cannot manufacture a
candidate.

Acceptance evidence:

```text
.venv/bin/python -m ruff check --fix \
  src/sts/forward/pipeline.py scripts/forward_eod.py \
  tests/forward/test_pipeline.py tests/forward/test_eod_script.py
All checks passed!

.venv/bin/python -m pytest -q \
  tests/forward/test_pipeline.py tests/forward/test_eod_script.py \
  tests/forward/test_ledger.py
60 passed in 7.35s

.venv/bin/python -m pytest -q
366 passed in 11.13s

git diff --check
(no output)
```

The plan-prescribed repository-wide `ruff check --fix .` was also run. It
found 35 pre-existing, non-auto-fixable findings outside this phase after
applying 122 unrelated mechanical fixes. Those unrelated rewrites were
discarded so this commit remains focused; the scoped Phase-5 lint gate is
clean. The repository-wide lint baseline must be resolved in Phase 6 before
its explicit full-suite gate can pass.

The 83 MB local cache was preserved. No production ledger was read or
written, no secret was exposed or modified, and no `gcloud` command was
called.
