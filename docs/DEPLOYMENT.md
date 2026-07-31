# Swing ranking forward deployment

## Host and isolation

The existing host is the GCP Compute Engine VM `sts-forward` in project
`stocks-that-move`, zone `us-west1-b`. The new application is deliberately
isolated from the legacy deployment:

| System | VM root | Dashboard port | Ledger |
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

Deploy and start the remote scheduler and read-only dashboard:

```bash
deploy/deploy.sh
```

The source context is sent through IAP and built by Docker on the VM, so
`deploy.sh` needs `gcloud` but does not require a local Docker daemon or Cloud
Build permissions.

The initial run is copied only when the remote run does not exist. Later
deployments preserve the remote run directory unchanged. The VM is the sole
writer once its scheduler is active.

Push the curated backtest subset the dashboard reads. It is not in the image
and not in the forward run, so this is a separate step from a machine holding
`runs/swing-ranking-v1`:

```bash
deploy/push_backtests.sh --dry-run   # list what would be sent
deploy/push_backtests.sh
```

It rsyncs ~54 MB across 38 files — manifests, protocols, rankings, metrics,
equity, trades, reports, and all of `oos-cohort-comparison-v1` and
`oos-seal-v1` — into `~/sts-swing-ranking-v1/runs/swing-ranking-v1/`, mounted
read-only. The 992 MB of raw per-revision detail (`candidates.jsonl`,
`events.jsonl`, `orders.jsonl`, `strategies/`) stays local; no view reads it.
The push adds and updates but never deletes remote files.

Because `strategies/` is not shipped, `scripts/export_strategy_names.py` writes
a compact `strategy_names.json` beside each window so revision identities still
resolve to strategy names on the VM. `push_backtests.sh` refreshes it first.

Open IAP tunnels to both dashboards:

```bash
deploy/open_remote.sh
deploy/open_remote.sh --stop
```

One `gcloud compute ssh` call carries two `-L` forwards, so a single command
opens the new dashboard on `http://127.0.0.1:8010` and the legacy one on
`http://127.0.0.1:8000`, and `--stop` reaps both. Readiness treats 8010 as
required and 8000 as best-effort: a stopped legacy container does not fail the
new dashboard.

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

## The dashboard

`docs/DASHBOARD_PLAN.md` covers what it shows and why the legacy dashboard is a
second tunnel rather than a reverse-proxied subpath. Operationally:

- It is read-only. `runs/` and `configs/` are mounted read-only; only `logs/` is
  writable, and only for the authentication audit trail. The scheduler remains
  the single writer, and `src/sts/swing_ranking/dashboard/` never imports the
  writing engine — a test asserts that on the import graph.
- It verifies each run's manifest content hashes on read. A mismatch renders as
  a banner over a still-usable degraded run, never as an exception.
- It requires login, as the legacy dashboard did: signed httponly session
  cookies, Google OAuth via authlib, and bcrypt password users.

### Access

The access list is `configs/dashboard_users.yaml`, which is **uncommitted**
because it holds password hashes; `configs/dashboard_users.example.yaml` shows
the shape. `deploy.sh` copies the whole `configs/` directory, so the real file
reaches the VM from the working tree without entering git.

Add or rotate a password user (always role `viewer`, enforced server-side),
then re-run `deploy/deploy.sh` to ship the change:

```bash
.venv/bin/python scripts/dashboard_user.py
```

For Google sign-in, add the account under `google:` with role `admin` or
`viewer`, put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the VM's
`~/sts-swing-ranking-v1/.env`, and register the callback on the Google
credential. Through an IAP tunnel the browser's host is whatever the operator
typed, and Google demands an exact match, so pin it:

```
DASHBOARD_OAUTH_REDIRECT_URI=http://127.0.0.1:8010/auth/google/callback
```

`DASHBOARD_SECRET` signs the session cookies. `deploy.sh` preserves the one
already on the VM and generates one only when none exists, so a deploy does not
invalidate everyone's cookies.

## Local deployment

Build the image and start only the local read-only dashboard:

```bash
deploy/deploy_local.sh
```

It sets `DASHBOARD_DEV=1`, which permits a known development signing secret.
Never set that on the VM.

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

The curated backtests pushed to `~/sts-swing-ranking-v1/runs/swing-ranking-v1/`
sit beside the forward run under the same `runs/` mount but are not part of it.
The dashboard reports OOS cohort equity and forward equity separately and
offers no endpoint that concatenates them; the charter forbids joining them.

## Durability still to add

The new run persists on the VM boot disk and is copied to its dedicated Drive
folder after manifest verification. Drive copy is non-destructive but not WORM;
retain the immutable session packages and consider bucket-level retention if a
stronger compliance boundary is needed.
