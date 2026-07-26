# Phase 2 — causal family selection

Implemented a public `selected_signals_for()` contract for the forward H1/H2
families. The contract returns only signal-close facts:

- H1: family, symbol, signal date, seed flag, trigger RSI(2), and reclaim wait;
- H2: family, symbol, and signal date after the locked causal top-decile filter.

The historical H1/H2 adapters now compose those facts with the existing
`entry_geometry()` function and apply catalyst embargo only after the historical
entry date exists. H3 remains on its previous adapter. Unknown forward families
fail closed.

Acceptance evidence:

```text
.venv/bin/python -m ruff check --fix \
  src/sts/study/h4_candidates.py tests/test_h4_candidates.py
Found 1 error (1 fixed, 0 remaining).

.venv/bin/python -m pytest -q \
  tests/test_h4_candidates.py tests/test_h4_gate.py \
  tests/test_portfolio.py tests/test_portfolio_ranked.py
26 passed in 3.20s

.venv/bin/python -m pytest -q \
  -k 'not test_default_source_queues_final_bar_selected_signal'
346 passed, 1 deselected in 8.41s

git diff --check
clean
```

The deselected test is the intentional Phase 3 red gate: the forward pipeline
does not yet import or call `selected_signals_for()`. Running it alone fails at
that missing forward connection, not at the Phase 2 selection contract.

No detector, decile, rank, risk, or embargo constant changed. No cache,
production ledger, secret, or cloud resource was modified.
