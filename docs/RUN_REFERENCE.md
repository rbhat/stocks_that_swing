# Swing ranking run reference

## Boundary

`swing-ranking-v1` has one implementation path:

`strict JSON configuration → read-only preflight → causal candidates and geometry → event simulator → metrics and independent rankings → atomic artifacts`

There is no default strategy, candidate grammar, data path, output path, cost,
or execution flag. Synthetic fixtures are refused below any `runs/` path.

## Required inputs

- A study-bundle JSON matching `sts.swing_ranking.config.load_study_bundle`.
  It fixes the protocol, charter, exact XNYS-session 60/20/20 split, both
  21-entry-session purge windows, selected evidence window, source facts,
  limitations, candidate grammar members, readable strategy revisions, and
  geometry before performance is read.
- A preflight-paths JSON matching
  `sts.swing_ranking.config.load_preflight_paths`.
- Complete permanent-ID security master and symbol history, point-in-time
  earnings events, XNYS sessions, corporate-action coverage, source hashes,
  and exactly one validated parquet per roster member.

Historical earnings report sessions/results come from custom-date queries to
<https://www.investing.com/earnings-calendar>. Raw responses and normalized
rows must be archived and hashed. Upcoming earnings schedules are append-only
daily snapshots so the first-known session is preserved.

The checked development bundle is
`configs/swing_ranking_v1/study_bundle.json`; its paths document is
`configs/swing_ranking_v1/preflight_paths.json`. It contains 144 exact
strategy/geometry members derived without reading performance. Its 300-session
evaluation range reserves a separate 21-session outcome buffer after June 9,
2026, and its selected evidence window exposes development only.

Historical rows do not reconstruct when a report was scheduled before the
event. They become known on the report session, and the two-session historical
blackout is therefore not represented as known in advance. The bundle records
this limitation. `upcoming_earnings_calendar.json` is a separate current
schedule input and is not admitted to retrospective evaluation.

## Rebuilding frozen inputs

Permanent IDs and cache-symbol intervals:

```bash
.venv/bin/python scripts/build_security_inputs.py \
  --roster configs/study_roster.yaml \
  --roster-manifest configs/study_roster_manifest.json \
  --raw-output cache/swing_ranking_inputs/raw/openfigi/2026-07-29.json \
  --security-master-output configs/swing_ranking_v1/security_master.json \
  --symbol-history-output configs/swing_ranking_v1/symbol_history.json \
  --coverage-end-exclusive 2026-07-10
```

Earnings collection is resumable per symbol. Use separate output directories
for historical results and each upcoming daily snapshot:

```bash
.venv/bin/python scripts/build_earnings_inputs.py \
  --security-master configs/swing_ranking_v1/security_master.json \
  --raw-dir cache/swing_ranking_inputs/raw/investing \
  --snapshot-output <append-only-snapshot.json> \
  --calendar-output <consolidated-calendar.json> \
  --coverage-start <YYYY-MM-DD> \
  --coverage-end-exclusive <YYYY-MM-DD> \
  --snapshot-date <YYYY-MM-DD>
```

Regenerate only the derived bundle and supporting source facts:

```bash
.venv/bin/python scripts/build_swing_study_bundle.py \
  --roster configs/study_roster.yaml \
  --roster-manifest configs/study_roster_manifest.json \
  --security-master configs/swing_ranking_v1/security_master.json \
  --symbol-history configs/swing_ranking_v1/symbol_history.json \
  --earnings-calendar configs/swing_ranking_v1/earnings_calendar.json \
  --parquet-root cache/study_frames \
  --output-dir configs/swing_ranking_v1 \
  --data-cutoff 2026-07-09
```

Derived outputs are append-only by default; pass `--replace` only after
deliberately changing a frozen input.

## Guarded commands

Read-only preflight:

```bash
.venv/bin/python scripts/run_swing_ranking.py \
  --real-cache --dry-run \
  --bundle configs/swing_ranking_v1/study_bundle.json \
  --paths configs/swing_ranking_v1/preflight_paths.json
```

Execution is a separate opt-in after reviewing preflight:

```bash
.venv/bin/python scripts/run_swing_ranking.py \
  --real-cache --execute \
  --bundle configs/swing_ranking_v1/study_bundle.json \
  --paths configs/swing_ranking_v1/preflight_paths.json \
  --output <artifact-directory>
```

## Current pause point

All 250 roster parquets, permanent-ID mappings, source facts, historical
earnings rows, upcoming schedule snapshot, and derived bundle files are
present. Repository tests and non-performance bundle validation pass. The
guarded real-cache preflight passed with protocol identity
`2efa2dc1035cd84774702acbf4880b6116f92940a662993b95cbbb2858c24be8`
and resolved-inputs identity
`d636616107d93670bde1d7b327f4aaa1d499e8e9ba2c218851a217cca146938b`.
It resolved 250 securities and 144 strategies with development as the selected
evidence window.

The first development run is complete at
`runs/swing-ranking-v1/development-v1`, with artifact identity
`0a3d7a1a04bac3800af4ed663267d0c210784bb82aab1f0e37c1f6b9b1551340`.
All manifest content hashes and record counts reconcile. The artifact contains
144 strategy metrics, 313,404 candidates/orders, 19,241 closed trades, 43,200
daily equity records, and 375,845 events. See `DEVELOPMENT_RESULTS.md` for the
three development leaderboards.

The initial execution attempt stopped before artifact publication because
feature-only prehistory contained sub-quality-tolerance adjusted-OHLC
rounding. The runner now creates strict simulator bars only from the evaluation
start while retaining full prehistory for causal feature construction.
Validation and study OOS remain closed.
