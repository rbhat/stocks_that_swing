# Phase 4 — EOD crash/retry parity

The EOD ledger now records three independent durable stages:
`upkeep_done`, `signals_done`, and `notifications_done`. Control records use
their `kind` as part of the local identity when `entry_id` is `None`, so all
three can coexist for one session while repeated writes remain idempotent.
Dedicated ledger readers expose the completed dates for each stage.

`generate_signals()` writes `signals_done` only after the shared and H1-solo
walks both finish. On retry, candidate and skip outcomes already journaled
for the session must form a prefix of the deterministic book queue. Existing
candidates are returned as part of the complete daily result and rebuild
provisional slot and notional state once; the ledger-backed H1 throttle also
counts their entry IDs once. A non-prefix journal fails closed instead of
guessing at a changed queue.

The EOD job rebuilds candidate (or explicit no-candidate) and same-session
book-status messages from the ledger whenever signals are complete but
notifications are not. `notifications_done` is appended only after every
message reports successful delivery. A crash during delivery can duplicate
messages on retry, providing at-least-once rather than at-most-once
semantics. Sync is attempted from the job's finalization path on successful,
failed, and fully completed invocations.

Crash coverage exercises:

- after `upkeep_done`, before the first candidate;
- after one H2 candidate;
- midway through the H1 shared-book queue;
- between the shared and H1-solo books;
- after `signals_done`, before notifications;
- during the notification set;
- a complete zero-event night;
- a fully complete same-date re-run.

For every signal-walk crash point, the resumed and uninterrupted ledgers have
identical signal records, equity snapshots, position state, returned
candidate IDs, and H1 queued/throttle counts.

Acceptance evidence:

```text
.venv/bin/python -m ruff check --fix \
  src/sts/forward/ledger.py src/sts/forward/pipeline.py \
  scripts/forward_eod.py tests/forward/test_ledger.py \
  tests/forward/test_pipeline.py tests/forward/test_eod_script.py \
  tests/forward/test_sync.py
All checks passed!

.venv/bin/python -m pytest -q \
  tests/forward/test_ledger.py tests/forward/test_pipeline.py \
  tests/forward/test_eod_script.py
53 passed in 6.78s

.venv/bin/python -m pytest -q tests/forward
141 passed in 10.29s

.venv/bin/python -m pytest -q tests/forward tests/test_h4_candidates.py \
  tests/test_h4_gate.py tests/test_portfolio.py tests/test_portfolio_ranked.py
167 passed in 10.26s

.venv/bin/python -m pytest -q
359 passed in 12.94s

git diff --check
(no output)
```

`docs/FORWARD_OPS.md` now documents the three markers, deterministic partial
resume, at-least-once notification behavior, and sync-on-every-invocation
contract. No detector, decile, rank, risk, sizing, embargo, or book constant
changed. The existing 83 MB local cache was preserved, no production ledger
was read or written, no secret was exposed or modified, and no `gcloud`
command was called.
