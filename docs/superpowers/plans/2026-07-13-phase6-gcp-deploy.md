# Phase-6 GCP Remote Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Phase-5 forward-paper pipeline (EOD / fill / monitor / sync) unattended on a GCP e2-micro VM, making the VM the single writer of the forward ledgers.

**Architecture:** Port the parent repo's (`~/dev/stocks_that_move/deploy/`) mechanical pattern: `provision.sh` (idempotent VM create + Docker install), `deploy.sh` (build amd64 image → Artifact Registry → scp configs/secrets → idempotent cron install), jobs run via `docker compose run --rm <service>`. Schedules and commands come from THIS repo (`docs/FORWARD_OPS.md`). Drive auth on the VM uses a dedicated GCP service account whose email is granted access to the two Drive folders; rclone on the VM reads `service_account_file` — no OAuth token copying.

**Tech Stack:** GCP (gcloud CLI, Compute Engine, Artifact Registry, IAP), Docker + compose plugin, Debian 12, rclone (Drive backend, service-account mode), cron, Python 3.12 slim image.

> **As-built deviations (executed 2026-07-13, commits eebf3a6..5ef3fc2):** VM zone is
> **`us-west1-b`**, not `us-central1-a` — every us-central1 zone was out of e2-micro
> capacity at provision time; the Artifact Registry image stays in us-central1
> (accepted cross-region pull). `lxml` was added to `pyproject.toml` during VM
> verification (yfinance earnings parsing needs it; the laptop venv had it only
> transitively). Zone references below are the original spec — the shipped scripts
> and `docs/FORWARD_OPS.md` use us-west1-b. Task 7 gate part 2 (first real cron EOD)
> pending 2026-07-13 17:30 PT.

## Global Constraints

- GCP project `stocks-that-move`, zone `us-central1-a`, instance `sts-forward` (confirmed by user 2026-07-13; second e2-micro on the billing account bills ~$7/mo — accepted).
- VM: e2-micro, Debian 12, 30GB pd-standard, IAP-tunneled SSH only (no SSH firewall exposure beyond IAP; parent pattern — ephemeral external IP retained for egress: yfinance + Discord + Drive need outbound, and Cloud NAT would cost more than the VM).
- Single-writer constraint: the VM is THE writer of forward ledgers. Laptop launchd agents stay uninstalled. Manual laptop runs are fallback-only when the VM is confirmed down — never concurrent (must be documented in `docs/FORWARD_OPS.md`).
- VM `ledger/` is seeded by the sync itself (remote is source of truth, merge-only) — never scp'd.
- Schedule (from `docs/FORWARD_OPS.md`, PT): EOD 17:30 weekdays; fill 06:31 weekdays; monitor 05:35 + hourly 06:35–12:35 + 13:35 weekdays. VM timezone is set to `America/Los_Angeles` so cron lines are written in PT directly and track DST (matches launchd-local-clock semantics the prereg assumed).
- Everything idempotent and re-runnable; `make test` stays green throughout (343 tests).
- All shell scripts: `set -euo pipefail`, pass `bash -n`, and every step checks-then-skips loudly (parent style).
- Progress ledger: `.superpowers/sdd/progress.md` — append one line per task completion.
- Do NOT commit secrets: `secrets/` is gitignored; `.env` already gitignored.

---

### Task 1: Dockerfile + .dockerignore + local image smoke test

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `.gitignore` (add `secrets/`)

**Interfaces:**
- Produces: image `sts:latest` with the `sts` package + `scripts/` + `configs/` + `universe.yaml` at `/app`, rclone binary on PATH, `CMD` unset-equivalent (each compose service supplies its command). Later tasks run `docker compose run --rm eod|fill|monitor|sync`.

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# rclone is invoked by sts.forward.sync via subprocess; curl only for the install step.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL https://rclone.org/install.sh | bash \
    && apt-get purge -y -qq curl unzip \
    && apt-get autoremove -y -qq \
    && rm -rf /var/lib/apt/lists/*

# Third-party deps first, keyed on pyproject.toml alone (parent pattern):
# editing src/ doesn't bust this layer.
COPY pyproject.toml ./
COPY src/sts/__init__.py ./src/sts/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip pip install .

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

COPY scripts ./scripts
COPY configs ./configs
COPY universe.yaml ./

# Jobs read .env from CWD (sts.env.load default "./.env" — bind-mounted),
# write ledger/, cache/, logs/ — all bind mounts; container runs as the
# host user (compose `user:`), so no useradd needed here.
CMD ["python", "scripts/forward_eod.py", "--help"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.git
.venv
.scratch
.superpowers
.agents
.claude
agent
cache
ledger
logs
runs
tests
docs
deploy
secrets
codex_review.md
*.log
__pycache__
```

- [ ] **Step 3: Add `secrets/` to `.gitignore`** (append line `secrets/` if absent).

- [ ] **Step 4: Build and smoke-test**

Run:
```bash
docker build --platform linux/amd64 -t sts:amd64 .
docker run --rm --platform linux/amd64 sts:amd64 python -c "import sts.forward.sync, sts.forward.alerts, sts.catalyst, sts.data.fetch; print('imports ok')"
docker run --rm --platform linux/amd64 sts:amd64 rclone version
docker run --rm --platform linux/amd64 sts:amd64 python scripts/forward_eod.py --help
```
Expected: `imports ok`, an rclone version banner, and the eod usage text — all exit 0.

- [ ] **Step 5: `make test` still green** (no src changes expected, but verify): `make test` → 343 passed.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore .gitignore
git commit -m "feat(deploy): Dockerfile for forward-paper jobs (python3.12-slim + rclone)"
```

---

### Task 2: deploy/docker-compose.yml

**Files:**
- Create: `deploy/docker-compose.yml`

**Interfaces:**
- Consumes: image tag via `STS_IMAGE` env (default `sts:latest`), host uid/gid via `STS_UID`/`STS_GID`.
- Produces: services `eod`, `fill`, `monitor`, `sync` — all one-shot via `docker compose run --rm <svc>`, sharing one volume anchor. Task 4's cron lines and the Task 7 gate invoke exactly these names.

- [ ] **Step 1: Write `deploy/docker-compose.yml`**

```yaml
# Used on the GCP VM (deploy.sh ships it to ~/sts/docker-compose.yml).
# All services are one-shot: `docker compose run --rm <svc>` from cron —
# never `up`. No `restart:` anywhere.
#
# User: services run as STS_UID:STS_GID (exported by deploy.sh from the
# VM user's id) so bind mounts keep host ownership and chmod-600 secrets
# stay readable (parent-repo pattern).
#
# NOTE: docker creates a directory for a bind-mounted host path that does
# not exist. deploy.sh mkdir/touches every path below before first run.

services:
  eod:
    image: ${STS_IMAGE:-sts:latest}
    command: ["python", "scripts/forward_eod.py"]
    user: "${STS_UID:-1000}:${STS_GID:-1000}"
    env_file: .env
    environment:
      - RCLONE_CONFIG=/app/secrets/rclone.conf
    volumes: &state_volumes
      - ./ledger:/app/ledger
      - ./cache:/app/cache
      - ./logs:/app/logs
      - ./runs:/app/runs
      - ./.env:/app/.env:ro
      - ./secrets:/app/secrets:ro

  fill:
    image: ${STS_IMAGE:-sts:latest}
    command: ["python", "scripts/forward_fill.py"]
    user: "${STS_UID:-1000}:${STS_GID:-1000}"
    env_file: .env
    environment:
      - RCLONE_CONFIG=/app/secrets/rclone.conf
    volumes: *state_volumes

  monitor:
    image: ${STS_IMAGE:-sts:latest}
    command: ["python", "scripts/forward_monitor.py"]
    user: "${STS_UID:-1000}:${STS_GID:-1000}"
    env_file: .env
    environment:
      - RCLONE_CONFIG=/app/secrets/rclone.conf
    volumes: *state_volumes

  sync:
    image: ${STS_IMAGE:-sts:latest}
    command: ["python", "scripts/forward_sync.py"]
    user: "${STS_UID:-1000}:${STS_GID:-1000}"
    env_file: .env
    environment:
      - RCLONE_CONFIG=/app/secrets/rclone.conf
    volumes: *state_volumes
```

- [ ] **Step 2: Validate**

Run: `docker compose -f deploy/docker-compose.yml config -q`
Expected: exit 0, no output. (Backtest push on the VM: `runs/` is mounted and will usually be empty there — `sync.py` copies whatever exists; `docs/preregs` is not shipped to the VM, so the VM sync runs with `--no-backtest` in cron (Task 4) and backtest artifacts keep being pushed from the laptop.)

Wait — `forward_eod.py` step 6 calls sync internally including backtest push. Check `scripts/forward_eod.py` for a flag or graceful handling of a missing `docs/preregs` dir; if `sync.push_backtest_artifacts` raises on missing dirs, it is caught/alerted per sync.py's design ("caught, alerted, and recorded"). To avoid a nightly false alert, ALSO bind-mount empty stubs: add `- ./docs:/app/docs` to `&state_volumes` and have deploy.sh `mkdir -p ~/sts/docs/preregs runs`. Verify against `sts/forward/sync.py::push_backtest_artifacts` behavior for a missing local dir (it iterates configured local dirs; if it skips non-existent dirs silently, the stub mkdir suffices; if it errors, stubs still suffice — empty dir → rclone copy no-op). Include the `./docs` mount in the file above (add to the anchor list) — implementer: add `- ./docs:/app/docs:ro` as the last volume line in the anchor.

- [ ] **Step 3: Commit**

```bash
git add deploy/docker-compose.yml
git commit -m "feat(deploy): compose services for eod/fill/monitor/sync (one-shot run --rm)"
```

---

### Task 3: deploy/provision.sh

**Files:**
- Create: `deploy/provision.sh` (chmod +x)

**Interfaces:**
- Consumes: env overrides `STS_PROJECT` (default `stocks-that-move`), `STS_ZONE` (default `us-central1-a`), `STS_INSTANCE` (default `sts-forward`).
- Produces: a running Debian-12 e2-micro with Docker + compose plugin, VM timezone `America/Los_Angeles`, Artifact Registry read for the VM's service account, IAP SSH reachable. Task 7 runs it.

- [ ] **Step 1: Write `deploy/provision.sh`** — port `~/dev/stocks_that_move/deploy/provision.sh` verbatim in structure with these substitutions:

1. Header comment names this repo; defaults `PROJECT="${STS_PROJECT:-stocks-that-move}"`, `ZONE="${STS_ZONE:-us-central1-a}"`, `INSTANCE="${STS_INSTANCE:-sts-forward}"`.
2. Identical blocks, in order: gcloud presence check → project access check (with the fix-it heredoc) → enable `compute.googleapis.com` → create instance if absent (`e2-micro`, `debian-12`, `30GB pd-standard`, `--scopes cloud-platform`) → grant `roles/artifactregistry.reader` to the instance SA → wait-for-SSH loop (20 × 10s, `--tunnel-through-iap`) → Docker install block (same apt-get commands).
3. NEW block after Docker install — set the VM timezone (idempotent):

```bash
echo "-- setting VM timezone to America/Los_Angeles (cron lines are written in PT) --"
if gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command "timedatectl show -p Timezone --value" 2>/dev/null | grep -q "America/Los_Angeles"; then
    echo "   already set"
else
    gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command "sudo timedatectl set-timezone America/Los_Angeles && sudo systemctl restart cron"
    echo "   set (cron restarted to pick up the new tz)"
fi
```

4. Closing banner: `Next: deploy/deploy.sh`.

- [ ] **Step 2: Lint**

Run: `bash -n deploy/provision.sh && chmod +x deploy/provision.sh`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add deploy/provision.sh
git commit -m "feat(deploy): idempotent GCP provision script for sts-forward VM"
```

---

### Task 4: deploy/deploy.sh

**Files:**
- Create: `deploy/deploy.sh` (chmod +x)

**Interfaces:**
- Consumes: image `sts:amd64` built from repo root (Task 1); compose file (Task 2); secrets `secrets/rclone.conf` + `secrets/sts-drive-sa.json` (Task 5); `.env` at repo root.
- Produces: image at `us-central1-docker.pkg.dev/stocks-that-move/sts/sts:latest`; VM dir `~/sts/` fully staged; cron entries installed. Task 7 runs it.

- [ ] **Step 1: Write `deploy/deploy.sh`** — port the parent's `deploy.sh` structure with these substitutions:

1. Vars: `PROJECT="${STS_PROJECT:-stocks-that-move}"`, `ZONE`, `INSTANCE="${STS_INSTANCE:-sts-forward}"`, `REGION=us-central1`, `REPO=sts`, `REMOTE_TAG="us-central1-docker.pkg.dev/${PROJECT}/sts/sts:latest"`.
2. Same preflight: gcloud check, project access, instance exists, `vm_ssh` helper, docker-on-VM check.
3. Same build/push: `docker build --platform linux/amd64 -t sts:amd64 "${REPO_ROOT}"`, ensure AR API + repo `sts` exist, `gcloud auth configure-docker`, digest-marker skip cache at `~/.cache/sts-deploy/last_push_image_id_${PROJECT}`, push.
4. Staging (replaces parent's):

```bash
echo "-- staging remote directories --"
vm_ssh "mkdir -p ~/sts/secrets ~/sts/configs ~/sts/cache ~/sts/ledger ~/sts/logs ~/sts/runs ~/sts/docs/preregs"

echo "-- copying files to VM (.env, secrets, universe.yaml, configs/, docker-compose.yml) --"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/.env" "${INSTANCE}:~/sts/.env"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/secrets/rclone.conf" "${INSTANCE}:~/sts/secrets/rclone.conf"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/secrets/sts-drive-sa.json" "${INSTANCE}:~/sts/secrets/sts-drive-sa.json"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/universe.yaml" "${INSTANCE}:~/sts/universe.yaml"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap --recurse \
    "${REPO_ROOT}/configs" "${INSTANCE}:~/sts/"

# STS_RCLONE_REMOTE must name the VM's service-account remote; pin idempotently.
vm_ssh "grep -v '^STS_RCLONE_REMOTE=' ~/sts/.env > ~/sts/.env.tmp || true; \
     mv ~/sts/.env.tmp ~/sts/.env; \
     echo 'STS_RCLONE_REMOTE=gdrive-sa:' >> ~/sts/.env"

echo "-- locking down secrets (chmod 600) --"
vm_ssh "chmod 600 ~/sts/.env ~/sts/secrets/rclone.conf ~/sts/secrets/sts-drive-sa.json"

gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/deploy/docker-compose.yml" "${INSTANCE}:~/sts/docker-compose.yml"
```

NOTE: the compose file mounts `./secrets` at `/app/secrets` and sets `RCLONE_CONFIG=/app/secrets/rclone.conf`; `secrets/rclone.conf` (Task 5) must reference the key by its **container** path `/app/secrets/sts-drive-sa.json`.

5. Cache seed (first deploy only — the roster is ~2M bars; refetching from scratch on an e2-micro is slow). tar-pipe, parent pattern, skipped when the VM already has a cache:

```bash
echo "-- seeding bar cache (first deploy only) --"
if vm_ssh "test -n \"\$(ls -A ~/sts/cache 2>/dev/null)\"" >/dev/null 2>&1; then
    echo "   VM cache non-empty, skipping seed"
else
    tar -C "${REPO_ROOT}" -czf - cache | vm_ssh "cd ~/sts && tar -xzf -"
    echo "   seeded from local cache/"
fi
```

6. Ledger: do NOT copy. Print one line: `echo "-- ledger/ NOT copied: seeded by merge-only Drive sync (remote is source of truth) --"`.
7. Image pull + docker registry auth on VM (same as parent, host `us-central1-docker.pkg.dev`), capture `STS_UID`/`STS_GID` from `id -u`/`id -g`, then `docker compose pull` (no `up` — nothing long-running).
8. Cron install — idempotent per entry, parent's grep-then-append pattern. VM local time is PT (Task 3), so lines are the FORWARD_OPS schedule verbatim. `--no-backtest` on the sync inside EOD is not a flag on eod, so eod runs as-is (docs stub mount handles it); standalone sync is not scheduled (EOD step 6 covers it):

```bash
ENVLINE="cd ~/sts && STS_IMAGE=${REMOTE_TAG} STS_UID=${STS_UID} STS_GID=${STS_GID}"
CRON_EOD="30 17 * * 1-5 ${ENVLINE} docker compose run --rm eod >> logs/eod.log 2>&1"
CRON_FILL="31 6 * * 1-5 ${ENVLINE} docker compose run --rm fill >> logs/fill.log 2>&1"
CRON_MONITOR="35 5,6,7,8,9,10,11,12,13 * * 1-5 ${ENVLINE} docker compose run --rm monitor >> logs/monitor.log 2>&1"
```

Install each with: `vm_ssh "(crontab -l 2>/dev/null | grep -qF 'run --rm eod' && echo 'eod cron present') || ((crontab -l 2>/dev/null; echo \"${CRON_EOD}\") | crontab - && echo 'eod cron installed')"` (and the analogous grep keys `run --rm fill`, `run --rm monitor`).

9. Closing banner prints the log-tail command:
`gcloud compute ssh sts-forward --project stocks-that-move --zone us-central1-a --tunnel-through-iap --command "tail -f ~/sts/logs/eod.log"`.

- [ ] **Step 2: Lint**

Run: `bash -n deploy/deploy.sh && chmod +x deploy/deploy.sh`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add deploy/deploy.sh
git commit -m "feat(deploy): deploy script — AR image push, secrets/config ship, PT cron install"
```

---

### Task 5: Drive service-account auth (HAS A USER-ONLY STEP)

**Files:**
- Create: `secrets/rclone.conf` (gitignored — NEVER committed)
- Create: `secrets/sts-drive-sa.json` (gitignored — NEVER committed)
- Create: `deploy/rclone.conf.example` (committed, no secrets)

**Interfaces:**
- Produces: rclone remote name `gdrive-sa:` usable with `--drive-root-folder-id` exactly as `sts.forward.sync` invokes it; `deploy.sh` (Task 4) ships both secret files.

- [ ] **Step 1: Create the service account + key (gcloud only, idempotent)**

```bash
gcloud iam service-accounts describe sts-drive-sync@stocks-that-move.iam.gserviceaccount.com >/dev/null 2>&1 \
  || gcloud iam service-accounts create sts-drive-sync \
       --project stocks-that-move --display-name "sts forward Drive sync"
test -f secrets/sts-drive-sa.json \
  || gcloud iam service-accounts keys create secrets/sts-drive-sa.json \
       --iam-account sts-drive-sync@stocks-that-move.iam.gserviceaccount.com
chmod 600 secrets/sts-drive-sa.json
```

No Drive API enablement is needed in the GCP project for rclone SA auth against user-shared folders — but enabling it is harmless and avoids edge cases: `gcloud services enable drive.googleapis.com --project stocks-that-move`.

- [ ] **Step 2: Write `secrets/rclone.conf`** (container path in `service_account_file` — this file is used INSIDE the container where secrets mount at `/app/secrets`):

```ini
[gdrive-sa]
type = drive
scope = drive
service_account_file = /app/secrets/sts-drive-sa.json
```

Also write `deploy/rclone.conf.example` with identical content plus a header comment: `# Copy to secrets/rclone.conf; pair with secrets/sts-drive-sa.json (gcloud iam service-accounts keys create). See docs/FORWARD_OPS.md.`

- [ ] **Step 3: USER STEP — share the Drive folders (STOP and wait for the user)**

Tell the user exactly:
> In Google Drive (as rajeevmbhatphone@gmail.com), share BOTH folders with `sts-drive-sync@stocks-that-move.iam.gserviceaccount.com` as **Editor**:
> 1. Forward folder: https://drive.google.com/drive/folders/1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5 → Share → add the SA email → Editor.
> 2. Backtest folder: https://drive.google.com/drive/folders/1i11V4ooDMRQbbVSkwzwbFr7lKlOoNcEQ → same.
> Untick "Notify people" if offered. Reply when done.

Do not proceed until confirmed.

- [ ] **Step 4: Verify access locally** (use a local-path copy of the conf so `service_account_file` resolves — the checked-in one uses the container path):

```bash
sed 's|/app/secrets/|'"$PWD"'/secrets/|' secrets/rclone.conf > .scratch/rclone-local.conf
RCLONE_CONFIG=.scratch/rclone-local.conf rclone lsd gdrive-sa: --drive-root-folder-id 1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5
RCLONE_CONFIG=.scratch/rclone-local.conf rclone lsf gdrive-sa: --drive-root-folder-id 1i11V4ooDMRQbbVSkwzwbFr7lKlOoNcEQ --max-depth 1
```

Expected: both exit 0 and list the folders' contents (forward folder should show the ledger jsonl files synced from the laptop; backtest folder shows runs/preregs). A 404/permission error means the share hasn't propagated — wait a minute and retry once, then re-check the share with the user.

- [ ] **Step 5: Confirm neither secret is tracked**

Run: `git status --porcelain secrets/` → empty (gitignored via Task 1's `.gitignore` line).

- [ ] **Step 6: Commit**

```bash
git add deploy/rclone.conf.example
git commit -m "feat(deploy): rclone service-account config template for VM Drive sync"
```

---

### Task 6: Documentation — remote runbook + single-writer policy

**Files:**
- Modify: `docs/FORWARD_OPS.md`
- Modify: `docs/PLAN.md` (Phase-6 section: mark remote deploy shipped, one line)

**Interfaces:**
- Consumes: script names/paths from Tasks 3–5, cron schedule from Task 4.

- [ ] **Step 1: Add a `## Remote deployment (GCP VM — the production writer)` section to `docs/FORWARD_OPS.md`** after the "Install / uninstall" section, containing:

```markdown
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
```

- [ ] **Step 2: In `docs/PLAN.md` Phase-6 remote-deploy paragraph**, append: `Shipped 2026-07 — see docs/FORWARD_OPS.md "Remote deployment".`

- [ ] **Step 3: Commit**

```bash
git add docs/FORWARD_OPS.md docs/PLAN.md
git commit -m "docs(forward): remote VM runbook + single-writer ledger policy"
```

---

### Task 7: Provision, deploy, in-container verification, and the go-live gate

This task is LIVE OPS (billable-adjacent; user already confirmed project/zone). Run from the repo root on the laptop. Each step's evidence goes in the progress ledger.

**Files:** none (execution only; fixes discovered here loop back into Tasks 1–5 files).

- [ ] **Step 1: Provision** — `deploy/provision.sh` → ends with "SSH reachable" + docker installed + tz set. Re-run must be a clean all-skip pass (idempotency check).

- [ ] **Step 2: Deploy** — `deploy/deploy.sh` → image pushed, files staged, cache seeded, 3 cron entries installed. Re-run: "already present" on all cron lines, push skipped (idempotency check).

- [ ] **Step 3: In-container connectivity tests ON the VM** (before trusting cron):

```bash
VMRUN='cd ~/sts && STS_IMAGE=us-central1-docker.pkg.dev/stocks-that-move/sts/sts:latest STS_UID=$(id -u) STS_GID=$(id -g) docker compose run --rm'
# yfinance fetch works from the VM:
gcloud compute ssh sts-forward --project stocks-that-move --zone us-central1-a --tunnel-through-iap \
  --command "$VMRUN eod python -c \"from sts.data.fetch import fetch_daily; df = fetch_daily('AAPL', start='2026-07-01'); print(len(df), 'rows')\""
# earnings refresh works:
gcloud compute ssh ... --command "$VMRUN eod python -c \"from sts.catalyst import refresh_earnings; print('earnings refresh callable')\""   # then invoke it for one symbol per its signature (read sts/catalyst.py first)
# Discord reachable from the container (proves .env is mounted):
gcloud compute ssh ... --command "$VMRUN eod python -c \"from sts import env; env.load(); from sts.forward.alerts import send; print(send('sts-forward VM: container connectivity test'))\""
# Drive reachable with the SA:
gcloud compute ssh ... --command "$VMRUN eod rclone lsd gdrive-sa: --drive-root-folder-id 1DIk5ZC-pHq5BGShgjXIqZ_O1nZ636gi5"
```

Expected: bar rows > 0; `True` from send (and the message visible in Discord); rclone lists the forward folder. Any failure: fix (Task 1–5 files), redeploy, retest.

- [ ] **Step 4: GATE part 1 — dry-run EOD on the VM:**

```bash
$VMRUN eod python scripts/forward_eod.py --no-fetch --dry-run
```

Expected: completes exit 0; ledger dir on VM untouched or scratch-consistent with the dry-run contract (no Discord, no sync, cached bars only — the seeded cache makes `--no-fetch` viable).

- [ ] **Step 5: GATE part 2 — real EOD run on the VM** (after market close, ≥17:30 PT, or next session):

```bash
$VMRUN eod
```

Expected, all three verified and pasted into the ledger:
1. Job exits 0; `~/sts/logs/` shows the 6 stages; VM `~/sts/ledger/` now contains the merged ledgers (seeded from Drive).
2. Discord shows the run's alerts (book status / any signals).
3. The Drive forward folder's ledger files' modified time is the run time (`rclone lsl` or Drive UI) — the VM wrote them.

If timing doesn't allow a real run in-session, install cron anyway (already done), verify the next morning's automatic run, and note the pending gate in the ledger before closing out.

- [ ] **Step 6: `make test` green locally** (343 passed) and final progress-ledger entry.

- [ ] **Step 7: Commit any fixes** made during verification with descriptive messages.

---

## Self-Review notes

- Spec coverage: webhook precondition (done pre-plan, fixed + committed eebf3a6); parent pattern port (T3/T4); schedules from FORWARD_OPS (T4 step 8); single-writer docs (T6); SA-first Drive auth with user console step + wait (T5); yfinance/earnings tested in container (T7.3); idempotency (T7.1/2 re-run checks); gate (T7.4–5); make test green (T1.5, T7.6).
- Open verification points flagged inline for implementers: `push_backtest_artifacts` behavior on empty dirs (T2.2), `refresh_earnings` signature (T7.3) — both are read-the-source checks, not TBDs.
