# Forward-Paper Operations Runbook

Phase-5 forward-paper pipeline: nightly EOD signal generation, morning fill
capture, hourly advisory monitoring, and daily Drive sync. This doc is the
day-2 operational reference — see `docs/PLAN.md` (Phase-5 section) and
`.superpowers/sdd/task-*-brief.md` for design rationale.

## Schedule (launchd, weekdays, assumes machine tz = America/Los_Angeles)

| Job              | Time (PT)         | Script                       | Make target       |
|------------------|--------------------|-------------------------------|--------------------|
| `forward-eod`    | 17:30              | `scripts/forward_eod.py`      | `make forward-eod` |
| `forward-fill`   | 06:31              | `scripts/forward_fill.py`     | `make forward-fill`|
| `forward-monitor`| 05:35 (pre-market), hourly 06:35–12:35 (RTH), 13:35 (post-market) | `scripts/forward_monitor.py`  | `make forward-monitor` |
| `forward-sync`   | run as step 6 of `forward-eod` (not scheduled standalone) | `scripts/forward_sync.py` | `make forward-sync` |

The monitor fires once pre-market (05:35 PT, before the 06:30 open), hourly
during regular trading hours (06:35–12:35 PT), and once post-market
(13:35 PT, after the 13:00 close), per prereg. Which alert types fire at
each check is governed by the monitor script's `_is_rth` gate, not by the
schedule — the schedule just guarantees the required check cadence.

launchd has no native timezone concept — `StartCalendarInterval` fires
against the machine's **local** clock. The plists in `deploy/launchd/` were
authored assuming this Mac's local timezone is `America/Los_Angeles`. If
that ever changes, regenerate the `Hour` values in the plists accordingly.

## Install / uninstall

```sh
deploy/launchd/install.sh        # idempotent install (bootout old, bootstrap new)
deploy/launchd/install.sh -u     # uninstall all three agents
```

The script substitutes `__REPO__` in each plist with `git rev-parse
--show-toplevel`, copies to `~/Library/LaunchAgents/`, and creates
`logs/forward/` for stdout/stderr capture. Safe to re-run any time (each
`launchctl bootout` failure, e.g. "not currently loaded," is ignored before
`bootstrap`).

## Remote deployment (GCP VM — the production writer)

The pipeline runs unattended on `sts-forward` (e2-micro, Debian 12 + Docker,
project `stocks-that-move`, zone `us-central1-a`, IAP-tunneled SSH). The VM's
timezone is `America/Los_Angeles`, so its cron matches the PT schedule above:

| Job | VM cron (PT local) | Command |
|-----|--------------------|---------|
| eod     | `30 17 * * 1-5` | `docker compose run --rm eod` |
| fill    | `31 6 * * 1-5`  | `docker compose run --rm fill` |
| monitor | `35 5,6,...,13 * * 1-5` | `docker compose run --rm monitor` |

Setup / redeploy (idempotent, re-run any time):

    deploy/provision.sh   # create VM + Docker + timezone (once)
    deploy/deploy.sh      # build+push image, ship .env/secrets/configs, install cron

Logs live on the VM under `~/sts/logs/{eod,fill,monitor}.log`:

    gcloud compute ssh sts-forward --project stocks-that-move \
      --zone us-central1-a --tunnel-through-iap \
      --command "tail -50 ~/sts/logs/eod.log"

Drive auth on the VM uses the dedicated service account
`sts-drive-sync@stocks-that-move.iam.gserviceaccount.com` (rclone remote
`gdrive-sa:`, key at `~/sts/secrets/sts-drive-sa.json`), which is shared
into both Drive folders as Editor. The laptop keeps its own OAuth remote
`gdrive:` — the two never share credentials.

### Single-writer policy (CRITICAL)

**The VM is THE writer of the forward ledgers.** The laptop launchd agents
in `deploy/launchd/` must stay uninstalled while the VM is live
(`deploy/launchd/install.sh -u` to remove if ever re-added). Manual laptop
runs (`make forward-eod` etc.) are a fallback ONLY when the VM is confirmed
down (e.g. `gcloud compute instances describe sts-forward` shows not
RUNNING, or SSH fails) — never run them concurrently with a live VM: the
Drive merge is append-safe but two writers in the same session can both
pass the size-then-check fill gate and double-enter positions. The VM's
`ledger/` is seeded by the merge-only sync itself on first run — remote
Drive state is the source of truth; never scp a ledger to the VM.

## Manual commands

```sh
# EOD job for a specific session (defaults to last_completed_session())
.venv/bin/python scripts/forward_eod.py --asof 2026-07-09

# Fill job for a specific session (defaults to today)
.venv/bin/python scripts/forward_fill.py --asof 2026-07-10

# Advisory monitor (defaults to today)
.venv/bin/python scripts/forward_monitor.py

# Daily sync only (also runs as EOD step 6)
.venv/bin/python scripts/forward_sync.py

# Rehearsal / dry run against a scratch ledger, no side effects
.venv/bin/python scripts/forward_eod.py --asof 2026-07-09 \
  --ledger-root .scratch/ledger-rehearsal --no-sync --no-discord --no-fetch
```

### Flags (common across scripts)

- `--asof YYYY-MM-DD` — override the target session (default varies per script; see script docstring).
- `--dry-run` — no Discord, no sync, no fetch (cached bars only); shorthand for the three `--no-*` flags on `forward_eod.py`.
- `--no-sync` / `--no-discord` / `--no-fetch` — disable individual side effects.
- `--ledger-root PATH` — point at an alternate ledger directory (default `ledger/`, gitignored).
- `--max-wait-min N` (forward_fill.py only) — how long to poll for today's open before giving up.
- `--no-backtest` (forward_sync.py only) — skip pushing backtest artifacts.

## Ledger locations

- Production ledger: `ledger/` (repo-relative, gitignored — never committed).
  Contains `signals.jsonl`, `equity.jsonl`, per-family ledgers (`h1.jsonl`,
  `h2.jsonl`), etc.
- Rehearsal/scratch ledgers: `.scratch/ledger-rehearsal/` (or any
  `--ledger-root` override) — safe to delete/regenerate.
- Logs: `logs/forward/<job-name>.log` (gitignored via the repo-wide `*.log`
  pattern).

## Drive folders (sync)

`forward_sync.py` uses `rclone` to merge-only sync ledgers and backtest
artifacts to the configured Google Drive remote (see `sts.forward.sync` /
`.env` for remote name and target paths). Sync is **merge-only** — it never
deletes or overwrites remote history with a shorter local file; it appends
missing rows in either direction and always re-uploads the union.

## Failure & recovery

- **Missed session (EOD job didn't run / cron didn't fire)**: the next
  `forward_eod.py` invocation runs `detect_missed_sessions()` (stage 5),
  which posts a Discord warning for any gap. Re-run `forward_eod.py
  --asof <missed-date>` manually to backfill; it is idempotent (ledger
  `upkeep_done` + signals rows are the source of truth — a re-run for an
  already-processed `asof` skips stages 1–5 and only re-runs sync).
- **Sync failure**: nonfatal. `forward_eod.py` step 6 (sync) is wrapped so a
  sync exception does not fail the whole job; an alert is sent and the next
  run's sync retries the merge. Ledger state itself is never blocked on
  sync succeeding.
- **Fill job runs before today's bar exists** (e.g. machine woke late):
  `forward_fill.py --max-wait-min N` polls for the open print; on timeout it
  logs candidates as "unavailable" for this run without corrupting state —
  re-run later in the day once the bar is cached.
- **Discord webhook down/misconfigured**: `alerts.send()` never raises; it
  retries 3x then logs a warning and returns `False`. All ledger-side
  effects still happen — Discord is a notification layer only, not part of
  the state machine.
- **Re-running idempotently**: every script keys off `--asof` + ledger
  content. Re-running any job for a date that's already fully processed is
  a safe no-op (verified in the Task 10 rehearsal — see
  `.superpowers/sdd/task-10-report.md`).

## Verification

- `make test` — full suite (343 tests as of Task 10).
- End-to-end rehearsal transcript: `.superpowers/sdd/task-10-report.md`.
