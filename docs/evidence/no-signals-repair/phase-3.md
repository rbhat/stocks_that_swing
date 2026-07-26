# Phase 3 — forward EOD causal connection

The default forward candidate source now calls `selected_signals_for()` for
H2 and H1 instead of asking the historical `candidates_for()` adapter for a
next-open-complete candidate. Before selection, every supplied price frame is
causally truncated through `asof`; the same truncated mapping is used for
signal geometry and book marks, and the caller's frames are not mutated.

`generate_signals()` now validates each selected fact before either book walk:

- the selected signal date must equal `asof`;
- the symbol frame must exist and contain the exact `asof` bar;
- signal-close/ATR provisional geometry must be finite and valid.

Valid facts retain the existing H2-before-H1 shared walk, H1 rank key, H1-only
walk, four-in-five throttle, book limits, next-session embargo, and stored
`atr_sig`. The fill job remains the authority for actual-open re-anchoring.

The returned `counts` mapping is keyed by family. `detected` and `selected`
count causal facts delivered by the family-selection source; signal-bar
failures and invalid geometry count unique facts; `embargoed` also counts
unique facts; `queued` and `skipped_by_reason` count book outcomes, since an
H1 fact is independently evaluated in the shared and H1-solo books.

Acceptance evidence:

```text
.venv/bin/python -m ruff check --fix \
  src/sts/forward/pipeline.py tests/forward/test_pipeline.py
All checks passed!

.venv/bin/python -m pytest -q \
  tests/forward/test_pipeline.py tests/forward/test_fill.py \
  tests/test_h4_candidates.py
32 passed in 5.02s

.venv/bin/python -m pytest -q tests/forward tests/test_h4_candidates.py \
  tests/test_h4_gate.py tests/test_portfolio.py tests/test_portfolio_ranked.py
156 passed in 6.91s

.venv/bin/python -m pytest -q
349 passed in 8.61s
```

The final-bar default-source integration covers both H2 and H1 without a
future bar. A separate test supplies a future bar and proves the selection
source receives only data through `asof` while the input cache frame remains
unchanged. Missing, stale, and invalid signal bars have explicit stage counts.

No detector, decile, rank, risk, embargo, sizing, or book constant changed.
No cache, production ledger, secret, cloud resource, or `gcloud` command was
used.
