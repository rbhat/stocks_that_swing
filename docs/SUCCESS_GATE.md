# Success-v2 metric artifact

`sts.study.success_gate` is the pure, strategy-agnostic Phase-1 contract for
new success-v2 studies. It performs no I/O and does not select a detector,
read a price frame, or know a data wall. Callers must enforce their phase's
wall before supplying facts.

The artifact schema is `success-v2.phase1` and has three independently
stateful sections:

- `event_gate`: actual-fill planned geometry, event adequacy, base and 2×
  net profit, win/loss and profit factor, hold, MAE, friction, and raw h=15
  return;
- `portfolio_gate`: net return, peak-to-trough drawdown, average deployed
  capital, and actual/modelled fill geometry;
- `matched_oos_band`: a seeded circular blocked bootstrap that samples the
  forward book's elapsed-session count and accepts only replicates with its
  exact closed-trade count. The 90% band is the 5th/95th percentile of
  compounded accepted returns.

Every section reports `not_run`, `inadequate`, `invalid_geometry`, or
`evaluated` as applicable. Missing evidence is never converted to a zero.
The event success bars are strict: planned R must be greater than 1.5,
initial risk must be below 25%, and the existing below-12% charter bound
also remains enforced.

Canonical closed-event fields are:

```text
entry_fill, stop_initial, target_initial,
gross_profit, friction_base, hold_sessions, mae_r
```

`friction_base` is total both-side dollar friction for one closed event;
the 2× arm doubles that fact. `mae_r` is the non-negative magnitude of
maximum adverse excursion in initial-R units. Portfolio session rows use
`equity` and `deployed_capital`; bootstrap source rows use `session_return`
and the non-negative integer `closed_trades`.

Locked historical JSON under `runs/` is not rewritten. New study runners
add the dictionary returned by `build_success_artifact` to their own
versioned report only after their data-wall and prereg gates authorize the
read.
