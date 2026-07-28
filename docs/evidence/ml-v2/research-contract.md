# ML-v2 Research, Simulator, and Audit Contract

- **Status:** PREREGISTERED; GATE 1 IMPLEMENTED; DATA ACCESS NOT AUTHORIZED
- **Applies to:** all six development setups and all their controls

## Exact accounting and diagnostics

All judged metrics use doubled friction unless suffixed `_base`.

- `entry_notional_i = shares_i × entry_fill_i`.
- `gross_pnl_i = shares_i × (exit_reference_i - next_open_i)`.
- `net_pnl_i = shares_i × (exit_fill_i - entry_fill_i)
  + cash_distributions_i
  - entry_commission_i - exit_commission_i`.
- `initial_risk_dollars_i =
  shares_i × (entry_fill_i - stop_initial_i)`.
- `net_R_i = net_pnl_i / initial_risk_dollars_i`.
- `NROCC = Σ net_pnl_i / Σ entry_notional_i`.
- `net_portfolio_return = ending_equity / starting_equity - 1`.
- `daily_equity = cash + Σ open_shares × conservative_mark`; the conservative
  mark is the session close for a valid open security and certified
  delisting value or zero recovery when delisted.
- `max_drawdown = max_d(1 - equity_d / max_{u<=d}(equity_u))`.
- `CAGR = (ending_equity / starting_equity)^(252 / exchange_sessions) - 1`
  when duration and positive equity permit it; otherwise `not_defined`.
- `Calmar = CAGR / max_drawdown`; when drawdown is zero, report
  `not_defined`, not infinity.
- `profit_factor = Σ positive net_pnl / abs(Σ negative net_pnl)`; no losses
  maps to `not_defined`.
- `win_rate = count(net_pnl > 0) / count(closed trades)`; zero is neither a
  win nor a loss and is separately counted.
- `average_R` and `median_R` use all closed trades.
- `average_exposure = mean_d(gross_open_market_value_d / equity_d)`.
- `turnover = (Σ entry_notional + Σ abs(exit_fill_notional))
  / (2 × mean_d(equity_d))`.
- holding time is the number of exchange sessions from entry through exit,
  inclusive; report mean, median, p90, and maximum.
- concurrency reports mean, p90, maximum, slot-skipped orders, and
  cash-skipped orders.

Mandatory fold and calendar-year tables include starting/ending equity, total
net P&L, `NROCC`, portfolio return, drawdown, trades, independent entry dates,
exposure, turnover, and rejected-fill counts. Annual signs, CAGR, Calmar,
profit factor, win rate, R summaries, exposure, turnover, holding time,
concurrency, and concentration are diagnostics unless a development gate
explicitly names them.

Report profit concentration by entry date, month, year, permanent security ID,
and top 1/5/10 contributors. Short profitable periods are allowed; their
concentration must remain visible.

CAGR and Calmar are computed separately per validation fold. The five
fresh-start fold equity curves are never concatenated into a fictitious
pooled CAGR.

## Point-in-time source requirements

Gate 2 must acquire and certify all of:

1. **Security master:** permanent IDs, listing intervals, primary listing,
   exchange, point-in-time security type, symbol changes, and effective/as-of
   timestamps.
2. **Universe history:** daily or interval membership that can reconstruct the
   eligible US common-share universe on each signal date without today's
   survivors.
3. **Delistings:** delisting date, reason, last executable print, delisting
   return or cash distribution, and provenance.
4. **Corporate actions:** raw OHLCV plus split and dividend events with
   announcement/effective timestamps sufficient to construct causal adjusted
   features without a later roster.
5. **Daily market data:** open, high, low, close, volume, trade status, and
   exchange session for eligible and later-delisted names.
6. **Earnings schedule:** scheduled event date and original announcement/as-of
   timestamps needed for the two-session entry embargo.
7. **Benchmark and calendar:** similarly controlled SPY facts and an
   authoritative exchange calendar.

Every source receives provider, license/use constraint, extraction time,
schema version, covered interval, as-of semantics, revision policy, row count,
content hash, and disposition:

- `point_in_time_certified`;
- `not_run_input_failure`;
- `rejected_leakage_risk`.

`survivor_only_development` is recorded only as a rejected predecessor
limitation; it cannot feed ML-v2.

Features use causal total-return adjustment factors. Execution, capacity, and
cash accounting use raw traded prices and shares. If a corporate action occurs
between signal and entry or while a position is open, ATR/geometry and share
quantities are converted to the executable session's raw-price/share basis
before orders are evaluated. An unresolvable conversion rejects the order or
stops an open-position simulation fail-closed; adjusted and raw price units
may never be mixed.

## Fail-closed input checks

Fatal checks stop the entire active gate:

- missing or uncertified permanent IDs, membership intervals, security type,
  delisting treatment, corporate-action timing, earnings-publication timing,
  or exchange calendar;
- source date outside the authorized interval;
- extraction lacking reproducible version/content identity;
- membership or classification effective after the signal date;
- duplicate `(permanent_id, session)` facts;
- many-to-many joins or join cardinality different from the manifest;
- OHLC violations (`low > high`, open/close outside valid range without a
  documented auction condition), negative prices/volume, or non-session rows;
- unexplained symbol reuse, delisted-name disappearance, split discontinuity,
  or source revision;
- aggregate expected-bar coverage below 99.5% or any calendar year's coverage
  below 98.0%;
- any future-feature, shuffled-session, wall, or leakage canary accepted.

Row/order-level checks reject and count only the affected opportunity:

- a missing or nonpositive next-session open;
- documented halt with no executable opening print;
- excessive entry gap;
- invalid stop/target geometry;
- stale rolling input;
- insufficient shares after risk, cash, slot, and participation caps;
- existing position in the same permanent ID.

If row-level rejection exceeds 5% of otherwise signaled orders overall or 10%
in any validation fold, the setup fails integrity. Missing facts are never
zero-filled, forward-filled across an unknown corporate action, or silently
dropped.

Expected-bar denominators use certified listing intervals and exchange
sessions, excluding documented trading suspensions and exchange-wide
closures. They do not exclude a name merely because it later delisted or a
price row is absent.

## Portfolio simulator requirements

The simulator is a deterministic event-sourced state machine:

- one independent book per setup/control/fold;
- ledger events are append-only and carry setup, fold, permanent ID, signal
  session, order, fill/rejection, position, cash, slot, and source identities;
- cash, risk budget, gross allocation, daily-entry quota, and eight slots are
  reserved atomically at entry and released only at exit;
- a pending or open position cannot reuse capital or a slot;
- ranks are computed once from prior-close information; a rejected higher rank
  advances only to the next already-ranked candidate under the locked
  sequential entry rule and never causes outcome-aware reordering;
- existing opening exits are processed before entries; new entries are
  eligible for same-session stop/target management; time exits occur at the
  close;
- all same-timestamp event ordering is explicit and stable;
- controls traverse the identical state machine;
- terminal liquidation closes every open position;
- total cash plus marked positions reconciles to equity after every event to
  a locked decimal tolerance;
- crashes after any durable event resume to byte-identical final state without
  duplicate orders or fills.

Required hand-calculated tests include cash contention, eight-slot contention,
three-entry throttle, simultaneous candidates, equal scores, symbol changes,
same-symbol re-entry, gap-through-stop, gap-through-target, ambiguous bar
stop-first, entry-day exit, time exit, terminal liquidation, split, delisting
with and without recovery, halt/rejected fill, partial capacity downsize,
commission/slippage, doubled friction, and control parity.

## Deterministic artifacts and audit

Future authorized work writes only under:

`runs/ml-v2/development/<run_id>/`.

Required durable artifacts:

- `authorization.json`;
- `environment.lock.json`;
- `source-manifest.json`;
- `data-quality.json`;
- `setup-matrix.json`;
- `fold-manifest.json`;
- `eligible-row-manifest.json`;
- `feature-schema.json`;
- `models/<setup_id>.<format>` for R/H;
- `scores.parquet`;
- `orders.parquet`;
- `fills-and-rejections.parquet`;
- `trades.parquet`;
- `daily-equity.parquet`;
- `controls/`;
- `permutations/`;
- `metrics.json`;
- `selection.json`;
- `review.md`;
- `identity.json`.

Canonical JSON uses UTF-8, sorted keys, fixed decimal/string rules, and no
volatile timestamps. Parquet schema, row order, compression, and writer
versions are locked. Human timestamps live in non-identity metadata.

The root identity is:

`sha256(canonical_json({
  study_id, authorization_hash, source_commit, clean_patch_hash,
  environment_hash, source_manifest_hash, setup_matrix_hash,
  fold_manifest_hash, eligible_rows_hash, feature_schema_hash,
  model_hashes, score_hash, order_hash, fill_rejection_hash,
  trade_hash, equity_hash, control_hashes, permutation_hashes,
  metrics_hash, selection_hash
}))`.

Two clean reruns in the locked environment must reproduce every component
hash. A difference is STOP until explained and independently reviewed; a
“close enough” metric match is insufficient for candidate freeze.

Development and future forward artifacts must use separate roots,
authorization records, ledgers, sync namespaces, and identity domains.
Forward code may read frozen model/config artifacts but never development
outcomes for runtime decisions.

## Gate 1 implementation surface

At preregistration, the first requested implementation task proposed:

- `src/sts/ml_v2/contracts.py`;
- `src/sts/ml_v2/identity.py`;
- `src/sts/ml_v2/metrics.py`;
- `src/sts/ml_v2/portfolio.py`;
- `src/sts/ml_v2/controls.py`;
- focused `tests/test_ml_v2_*.py`;
- `docs/evidence/ml-v2/gate-1.md`.

The 2026-07-28 explicit Gate 1 authorization created this surface using only
synthetic and hand-calculated fixtures. Data adapters, market reads, model
fitting, and run directories remain outside Gate 1. Completion evidence is
`gate-1.md`.

## Estimated compute and storage

Planning estimates assume roughly 8,000 historical permanent IDs, 22 years,
40–50 million daily rows, six setups, five folds, 200 random controls per
fold, 999 synchronized permutations, and CPU-only deterministic fitting:

| Stage | Wall time | Compute | Scratch | Durable |
|---|---:|---:|---:|---:|
| Gate 1 synthetic contracts | 1–3 hours | 2–8 CPU-hours | <2 GB | <1 GB |
| Gate 2 certification | 4–16 hours plus acquisition | 20–80 CPU-hours | 20–60 GB | 10–30 GB |
| Gate 3 dataset build twice | 8–24 hours | 100–300 CPU-hours | 100–250 GB | 30–80 GB |
| Gate 4 real setups/controls | 12–36 hours | 200–600 CPU-hours | 100–250 GB | 20–60 GB |
| Gate 4 permutations | 24–96 hours | 500–2,000 CPU-hours | 150–400 GB | 20–80 GB |

Expected end-to-end development wall time is 3–10 days on a 16–32-core,
128-GB-RAM host after certified data are locally available. Budget 500 GB
free scratch and 150 GB durable storage. These are capacity estimates, not
authorization to inspect sources; Gate 2 must revise them from metadata before
materialization without expanding the candidate matrix.

## Explicit STOP classifications

- `STOP_AUTH`: gate lacks explicit authorization.
- `STOP_INPUT`: critical point-in-time source or adequacy is unavailable.
- `STOP_WALL`: unauthorized date or future fact was observed.
- `STOP_LEAKAGE`: as-of, transform, purge, embargo, or canary failure.
- `STOP_SIMULATOR`: cash, slot, fill, accounting, or retry invariant failed.
- `STOP_CONTROL`: required control is missing or not comparable.
- `STOP_PERMUTATION`: a credible local permutation exists or adjusted family
  p-value exceeds 0.05.
- `STOP_PROFIT`: any locked profitability, increment, uncertainty, drawdown,
  or count gate fails.
- `STOP_IDENTITY`: clean reruns differ.
- `STOP_FREEZE`: a frozen setup or artifact changed.

STOP classifications are append-only facts. Fixing an implementation defect
before evidence access permits rerunning that gate after review. Fixing or
retuning after development results requires a new independent preregistration;
the original result remains stopped.
