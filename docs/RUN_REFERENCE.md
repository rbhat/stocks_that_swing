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
- For an evidence window other than the bundle's development selection, an
  evidence-selection JSON matching
  `sts.swing_ranking.config.load_selected_study`. It binds the selected window
  to the exact study-bundle SHA-256 before performance is read.
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

The checked validation selection is
`configs/swing_ranking_v1/validation_selection.json`. It binds validation to
the frozen development bundle hash without changing the protocol, grammar, or
strategy revisions.

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

For validation, add the explicit selection:

```bash
.venv/bin/python scripts/run_swing_ranking.py \
  --real-cache --dry-run \
  --bundle configs/swing_ranking_v1/study_bundle.json \
  --selection configs/swing_ranking_v1/validation_selection.json \
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

The validation execution uses the same command with `--execute`, the checked
validation selection, and an explicit immutable output directory.

## Current pause point

Resume verification started from clean commit `86f55b8`, aligned with
`origin/main`. All 250 roster parquets, permanent-ID mappings, source facts,
historical earnings rows, upcoming schedule snapshot, and derived bundle files
are present. All 80 repository tests pass. The guarded real-cache preflight
passes for both authorized evidence selections with protocol identity
`2efa2dc1035cd84774702acbf4880b6116f92940a662993b95cbbb2858c24be8`
and resolved-inputs identity
`d636616107d93670bde1d7b327f4aaa1d499e8e9ba2c218851a217cca146938b`.
Each resolves 250 securities and 144 strategies. The development window
identity is
`74cb71782e4caae06a92289c5a41d894a464985ac0b032bf543691e867492a83`;
the validation window identity is
`2917c3f0f65ceb97639718401211c8e7f71f1dae2896b2042b0ae92d881eadd8`.

The first development run is complete at
`runs/swing-ranking-v1/development-v1`, with artifact identity
`0a3d7a1a04bac3800af4ed663267d0c210784bb82aab1f0e37c1f6b9b1551340`.
All manifest content hashes and record counts reconcile. The artifact contains
144 strategy metrics, 313,404 candidates/orders, 19,241 closed trades, 43,200
daily equity records, and 375,845 events. See `DEVELOPMENT_RESULTS.md` for the
three development leaderboards.

The initial execution attempt stopped before artifact publication because
feature-only prehistory contained sub-quality-tolerance adjusted-OHLC
rounding. The runner now creates strict simulator bars only from the selected
evidence start through its outcome purge while retaining only earlier
prehistory for causal feature construction.

An independent re-audit verified the development content hashes, record
identities, event chains, accounting, metrics, and rankings. It also found
that artifact v1 equity-marked all 300 evaluation sessions after development
positions were closed. No validation/OOS candidates, orders, or trades entered
the development results, so the reported performance is unchanged. Artifact
v2 now records and enforces the selected evidence and outcome boundaries.

The validation run is complete at `runs/swing-ranking-v1/validation-v1`, with
artifact identity
`25157f4ee3a913f066d49cd4287e1b5090f84bed5201ae7e7bca602944ebb98e`.
All 154 manifest hashes and record counts reconcile. The artifact contains 144
strategy metrics, 79,056 candidates/orders, 5,993 closed trades, 8,640 daily
equity records, and 93,689 events. Every strategy has exactly 60 equity
sessions and no record reaches the 2026-03-13 study-OOS start. See
`VALIDATION_RESULTS.md`.

Revision selection is pending. Study OOS remains closed and no forward-paper
work has started.

The cross-window audit joins the same 144 revisions by immutable identity and
recomputes the three study rankings from each artifact's metric records. The
development/validation Spearman rank correlations are `-0.1855` for profit,
`-0.1642` for drawdown, and `-0.2260` for profit/drawdown. No metric shares a
top-10 revision; top-20 overlaps are two, three, and one respectively. See
`VALIDATION_RESULTS.md` for the revision-level comparison. These are
diagnostics only.

The clean pause contains only `development-v1` and `validation-v1` under the
study run directory. There is no study-OOS selection document or artifact
directory and no forward-paper path. The next authorized action is
user-directed revision selection only.
