# Swing ranking run reference

## Boundary

`swing-ranking-v1` has one implementation path:

`strict JSON configuration → read-only preflight → causal candidates and geometry → event simulator → metrics and independent rankings → atomic artifacts`

There is no default strategy, candidate grammar, data path, output path, cost,
or execution flag. Synthetic fixtures are refused below any `runs/` path.

## Required inputs

- A study-bundle JSON matching `sts.swing_ranking.config.load_study_bundle`.
  It fixes the protocol, charter, source facts, limitations, candidate
  grammar members, readable strategy revisions, and geometry before
  performance is read.
- A preflight-paths JSON matching
  `sts.swing_ranking.config.load_preflight_paths`.
- Complete permanent-ID security master and symbol history, point-in-time
  earnings events, XNYS sessions, corporate-action coverage, source hashes,
  and exactly one validated parquet per roster member.

No study bundle is checked in because choosing its grammar and strategies is
the next research decision, not an implementation default.

## Guarded commands

Read-only preflight:

```bash
.venv/bin/python scripts/run_swing_ranking.py \
  --real-cache --dry-run \
  --bundle <study-bundle.json> \
  --paths <preflight-paths.json>
```

Execution is a separate opt-in after reviewing preflight:

```bash
.venv/bin/python scripts/run_swing_ranking.py \
  --real-cache --execute \
  --bundle <study-bundle.json> \
  --paths <preflight-paths.json> \
  --output <artifact-directory>
```

## Current local blockers

The readiness audit found no permanent-ID security-master/symbol-history
inputs, no point-in-time earnings cache, and 240 parquet files for a
250-symbol roster. The absent symbols are `AEP`, `BA`, `CAT`, `CNP`, `CVX`,
`DIS`, `DTE`, `ED`, `GD`, and `GE`. Preflight is expected to fail closed until
those inputs are supplied and their hashes are frozen into the study bundle.
