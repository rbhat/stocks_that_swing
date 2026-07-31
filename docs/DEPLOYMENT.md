# Swing ranking forward deployment

## Host and isolation

The existing host is the GCP Compute Engine VM `sts-forward` in project
`stocks-that-move`, zone `us-west1-b`. The new application is deliberately
isolated from the legacy deployment:

| System | VM root | Viewer port | Ledger |
|---|---|---:|---|
| Legacy | `~/sts` | 8000 | `~/sts/ledger` plus its existing Drive namespace |
| Swing ranking v1 | `~/sts-swing-ranking-v1` | 8010 | `~/sts-swing-ranking-v1/runs/swing-ranking-v1-forward-01` |

The deployment scripts never delete, truncate, copy over, or synchronize the
legacy ledger. Rename/archive the old Drive files independently.

The new destinations are fixed in `scripts/sync_swing_artifacts.py`:

- forward test: Drive folder `1VHPM0pz_BW-48tR6vs9PFJmPJ1YGy87R`;
- backtests: Drive folder `1sQ6LdAmvsD2-nH9kBO-s9nJrsMChHwBy`.

Uploads use `rclone copy` followed by `rclone check --one-way`. They update
changed files and add new files but never delete extra remote objects. The
forward source is hash-verified from its run/session manifests before upload.

## Deploy from this checkout

Stage the image, configuration, and the initialized empty run without starting
containers:

```bash
deploy/deploy.sh --stage-only
```

Deploy and start the remote scheduler and read-only ledger viewer:

```bash
deploy/deploy.sh
```

The source context is sent through IAP and built by Docker on the VM, so
`deploy.sh` needs `gcloud` but does not require a local Docker daemon or Cloud
Build permissions.

The initial run is copied only when the remote run does not exist. Later
deployments preserve the remote run directory unchanged. The VM is the sole
writer once its scheduler is active.

Open an IAP tunnel to the read-only file viewer:

```bash
deploy/open_remote.sh
deploy/open_remote.sh --stop
```

Inspect the remote service and logs directly:

```bash
gcloud compute ssh sts-forward \
  --project stocks-that-move --zone us-west1-b --tunnel-through-iap \
  --command 'cd ~/sts-swing-ranking-v1 && docker compose ps && docker compose logs --tail 100 scheduler'
```

Stop only the new writer without affecting the legacy deployment:

```bash
gcloud compute ssh sts-forward \
  --project stocks-that-move --zone us-west1-b --tunnel-through-iap \
  --command 'cd ~/sts-swing-ranking-v1 && docker compose stop scheduler'
```

## Local deployment

Build the image and start only the local read-only viewer:

```bash
deploy/deploy_local.sh
```

Starting a local writer is an explicit fallback operation:

```bash
deploy/deploy_local.sh --activate-writer
```

Never run the local and GCP schedulers concurrently. Stop and verify the GCP
scheduler first. The file lock prevents two writers inside one host namespace;
it cannot coordinate two different machines.

## Cadence and data-feed boundary

The scheduler wakes hourly so outages are retried promptly. It does not make
hourly trading decisions. On each wake it compares the latest completed XNYS
session with the exact next session in `state.json`:

- before the expected session closes: no-op;
- exact expected completed session: collect immutable inputs and advance once;
- later than expected: fail closed because the charter prohibits backfill.

Signals are still formed from completed daily bars and enter at the following
session's open. Changing signal evaluation to hourly bars would be a new
strategy and would break comparability with the sealed OOS evidence.

After each successful daily advance—and on pre-session no-op retries—the
coordinator verifies and copies the forward run to the dedicated forward-test
Drive folder. Backtests are intentionally not uploaded hourly. Upload them
from a machine that holds `runs/swing-ranking-v1` with:

```bash
RCLONE_CONFIG=<rclone.conf> .venv/bin/python scripts/sync_swing_artifacts.py --backtest-only
```

`fetch_swing_forward_prices.py` (Yahoo) and `build_earnings_inputs.py`
(Investing.com) remain transitional collectors. The remote runtime and ledger
layout are ready, but a production-grade paid market-data and point-in-time
earnings adapter must replace those collectors before this is called a proper
feed. Provider credentials belong in the uncommitted `.env`; do not bake them
into the image.

## How the forward ledger works

The authoritative forward ledger is the complete run directory, not a single
JSONL file:

```text
runs/swing-ranking-v1-forward-01/
├── charter.json
├── state.json
├── manifest.json
├── candidates.jsonl
├── orders.jsonl
├── trades.jsonl
├── equity.jsonl
├── events.jsonl
└── sessions/YYYY-MM-DD/
    ├── source.json
    ├── next_state.json
    ├── manifest.json
    └── records/*.jsonl
```

- `charter.json` fixes the run identity, sealed selection, nine strategy
  revisions, first eligible session, no-backfill rule, and evidence thresholds.
- `state.json` is the current checkpoint: cash, open positions, pending
  next-open candidates, event-chain head, trade counts, drawdown, turnover,
  and the exact next eligible session for each strategy book.
- The five top-level JSONL files are append-only projections across all
  processed sessions. Every row carries its strategy revision identity and a
  deterministic record identity.
- `sessions/YYYY-MM-DD` is the immutable audit package for one advance. It
  hashes the exact 250 price parquets, same-day earnings snapshot, prior state,
  per-session records, and next state.
- `manifest.json` binds the run identity to current content hashes, record
  counts, and every immutable session artifact.

For a session, pending candidates are evaluated at the open, positions are
advanced through the daily bar, exits and equity are recorded, and new signals
at the close become candidates for the next session. The engine writes the
immutable per-session package before extending the aggregate projections and
updating state/manifest. A repeated completed run is a no-op; changed inputs,
missing sessions, altered strategy identities, or divergent hashes fail
closed.

The current initialized ledger contains zero candidate, order, trade, equity,
and event rows. Its first eligible signal session is `2026-08-03`. Historical
development, validation, OOS artifacts, and the legacy `~/sts/ledger` are not
part of this forward ledger.

## Durability still to add

The new run persists on the VM boot disk and is copied to its dedicated Drive
folder after manifest verification. Drive copy is non-destructive but not WORM;
retain the immutable session packages and consider bucket-level retention if a
stronger compliance boundary is needed.
