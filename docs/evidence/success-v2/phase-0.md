# Success-v2 Phase 0 — freeze and baseline

- Completed: 2026-07-26 (America/Los_Angeles)
- Restart-plan commit: `3e32603f8b52899d8070e805a16ed877436907ab`
- Starting code baseline (the restart commit's parent): `26d4b46`
- Initial `git status --short`: empty
- Clean OOS wall: 2026-07-27

## Local baseline

- No local forward process, user crontab, relevant systemd timer, Docker
  container, ledger root, forward log root, or launchd plist was active/present.
- Full suite before Phase-0 code changes: `366 passed in 11.23s`.
- Repository lint before changes: `ruff check .` failed with 152 existing
  findings (117 automatically fixable); `git diff --check` passed. This is a
  recorded pre-existing lint baseline, not evidence produced by the restart.
- Price cache: 240 readable parquet files for a 250-symbol roster, 1,908,689
  rows total. All 240 ended on 2026-07-23. The missing/failing symbols were
  `AEP, BA, CAT, CNP, CVX, DIS, DTE, ED, GD, GE`.
- Catalyst inputs: both `cache/catalysts/earnings.json` and `catalysts.yaml`
  were absent locally. This is an input failure and must not be interpreted as
  zero catalyst events.
- No local price bar on or after the 2026-07-27 wall was read.

## Production read-only inventory

- VM: `sts-forward`, project `stocks-that-move`, zone `us-west1-b`, status
  `RUNNING`; last start 2026-07-13 09:32:59 PT.
- Legacy ledger root: `~/sts/ledger`; legacy Drive root is the existing
  `FORWARD_FOLDER_ID` namespace used by `sts.forward.sync`. No success-v2
  namespace exists or was written.
- Image:
  `us-central1-docker.pkg.dev/stocks-that-move/sts/sts@sha256:54b03027023180681050b6a93d9da6f8cab888321d78292186a5c6e399ac40e6`.
- The only running container was the read-only dashboard
  `sts-dashboard-1`; one-shot EOD/fill/monitor containers were not running.
- Legacy family ledgers were empty (`h1.jsonl` and `h2.jsonl`: zero rows).
  `signals.jsonl` had 11 upkeep markers and zero candidate rows.
  `equity.jsonl` had 22 snapshots, all with `open_count=0`.
- Last completed upkeep, signal scan, and sync: 2026-07-24. That run reported
  240 price updates, 10 failures, zero closes, zero queued candidates, and a
  successful append-only sync.
- Production price cache had 250 parquet files. The earnings cache existed
  (163,021 bytes; modified 2026-07-21 17:36:37 PT).

## Freeze action and append-only proof

- Saved the original production crontab as
  `~/sts/crontab.pre-success-v2-freeze-20260726.txt`
  (SHA-256 `e4af6145137474e042f16718c2dd930e0b22a32e390eafe73bc65ed387b8850a`).
- Removed only the legacy `eod` and `fill` cron entries. The advisory monitor
  remains scheduled; with no open positions it is a read-only no-op.
- Added a local fail-closed wall: legacy EOD continues price loading, upkeep,
  exit notification, completion journaling, and sync, but skips all legacy
  detectors on/after 2026-07-27. Legacy fill refuses all queued candidates at
  or beyond that wall before loading market data.
- No production ledger file was edited. Post-freeze SHA-256:
  - `equity.jsonl`: `49b6e6e34a6d323607fa51054fe065cfb613875577deee0cd8bf44e1de9a1caf`
  - `h1.jsonl`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
  - `h2.jsonl`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
  - `signals.jsonl`: `9a928f40926274485bb01eb8ebdbd44844ef384e5ff1f2e8145cd337f6b5bb13`

## Phase gate

- Focused legacy freeze tests: `18 passed in 5.04s`.
- Full suite after Phase-0 changes: `368 passed in 10.67s`.
- Repository lint remained exactly at the recorded baseline of 152 findings;
  the new freeze module passed `ruff check` independently.
- `git diff --check` passed.
- Gate: **PASS**. Baseline evidence is committed with a fail-closed entry
  wall, the empty legacy book cannot gain a new entry, no ledger was
  truncated or rewritten, and the upkeep path remains active in code for any
  legacy position discovered later through append-only sync.
