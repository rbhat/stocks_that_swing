# ML restart Phase 2 — walled development matrices

- Completed: 2026-07-27 (America/Los_Angeles)
- Starting commit:
  `09e0293` (`feat: add causal ML research contracts`)
- Initial `git status --short`: empty
- Implementation authorization: Tasks 3 and 4; this evidence covers Task 3 only
- Task 5 authorization: not granted

## Walled source inventory

The builder used only the frozen 250-name roster in
`configs/study_roster.yaml` and predicate-filtered adjusted OHLCV in
`cache/study_frames` to
`2010-01-01 <= date < 2024-01-01` before materialization. It then checked
every returned row against the same wall. There is no fetch, network, alternate
cache, or unfiltered fallback.

Source dispositions are explicit:

- 237 roster inputs loaded as `survivor_only_development`;
- ten roster parquets were missing and three had no pre-2024 development rows,
  all recorded as `not_run_input_failure`;
- catalyst data remains `not_run_input_failure` and is absent from the matrix;
- point-in-time membership and delisting history remain
  `rejected_leakage_risk`;
- adjusted-history vintage and the frozen historical roster remain
  `survivor_only_development`.

The missing/no-development names are recorded individually in
`runs/ml-restart/development/manifest.json`. ARM, FER, and GEHC loaded but
produced no eligible Track A row. Historical survivorship and possible adjusted
history revisions remain limitations, so these matrices are development
evidence only and never clean OOS evidence.

## Matrix construction

`src/sts/ml/data.py` and `scripts/build_ml_development_data.py` implement:

- predicate-filtered parquet reads and post-read wall refusal;
- the exact locked OHLCV/SPY features and six immutable Phase-3 detector flags;
- the 300-session, $5 close, $20M average-dollar-volume, next-open, geometry,
  and complete-label eligibility checks;
- next-session-open fixed-policy labels through the 15-session horizon;
- same-date Track A target normalization;
- the deduplicated eligible union of the six Track B detector streams;
- deterministic row identities, source/matrix hashes, row cardinality,
  missingness, and source dispositions.

Track B date adequacy is counted after Track A eligibility. A rule event that
cannot join one-to-one to an eligible Track A parent cannot inflate the Track B
same-date pool.

## Artifact results

The accepted artifact config hash is:

`4d5465d1bb5e5d56d79a2885e691c836842150a75bb2e11a3e2fd45bdb1e5db1`

The manifest records:

- Track A: 633,774 rows, 3,207 dates, 234 symbols, 2011-03-11 through
  2023-12-06;
- Track B: 29,200 rows, 2,796 dates, 234 symbols over the same date bounds;
- Track B primary-adequate: 27,601 rows;
- Track B `not_run_inadequate_track_cross_section`: 1,599 rows;
- duplicate Track A keys: zero;
- duplicate Track B keys: zero;
- Track B rows without an eligible Track A parent: zero;
- rows observed on or after 2024-01-01: zero.

Missing feature values remain missing, never zero. Track A contains 34 missing
feature cells across five volume/range features; Track B contains two. The
manifest records feature-level counts and row counts by date, symbol, and track.
It also records all 133,590 eligibility/build rejections by reason.

The versioned output is split into 13 deterministic yearly parquet shards per
track so no committed file exceeds ordinary Git hosting limits. Dataset hashes:

- Track A:
  `288c0b2facdbf2e0b69dcaceee442e169df455c2f0e7c29524984df154b0d8f6`;
- Track B:
  `514fd9d5dd29bd78fc3f84371d3d323f1db04f35ccd3bf20cad386b1de195ece`;
- manifest file:
  `585a49ee242cf804431d0fedd0ef109d74c2c52ee6a1e4571040fec32ab247c6`.

## Determinism and verification

The complete full-roster build ran twice. Before sharding, both independent
manifests and matrix parquets were byte-identical:

- Track A monolith:
  `e9bdc429e8e4c3ff0b1875f550550a2b89ea1d8338d1aea45fb50cb241de4ec5`;
- Track B monolith:
  `6eb832aee725bd5783795e8f3931d794f37dbd02eeb8e0fb581373689a990b30`.

The accepted matrices were then packaged twice independently into yearly
shards. The file sets, every shard, and both manifests were byte-identical.
Metadata reconciliation reproduced 633,774 Track A and 29,200 Track B rows.

- Focused Task 3/4 synthetic suite: `21 passed in 10.47s`.
- Full frozen-lock suite: `447 passed in 21.99s`.
- Task-scoped Ruff 0.16.0: passed.
- `git diff --check`: passed.

## Phase gate

Gate: **PASS**. Source limitations, missing inputs, vintage risk, survivorship,
duplicates, joins, completeness, missingness, and wall observations are
explicit. Matrix construction and packaging are deterministic. Zero row on or
after 2024-01-01 was observed, and no model was fitted on market data.
