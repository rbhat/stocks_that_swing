# Phase 1 — failing causal-boundary tests

Added regression coverage for:

- H1 selected identity on the final cached bar without a next-open bar;
- H2 top-decile selected identity on the final cached bar;
- the default forward candidate source reaching the live EOD walk.

Red gate:

```text
ImportError: cannot import name 'selected_signals_for'
```

The failure is the intended missing causal selection contract, not fixture or
environment setup.
