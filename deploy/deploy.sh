#!/usr/bin/env bash
# Build, push, and roll out the sts image to the provisioned VM. Idempotent:
# safe to re-run any time (re-deploy = re-run this script). Does NOT run
# gcloud auth and does NOT create the VM (that's provision.sh).
#
# Usage: deploy/deploy.sh
# Env overrides: STS_PROJECT STS_ZONE STS_INSTANCE
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"
REGION="us-central1"
REPO="sts"
REGISTRY_HOST="${REGION}-docker.pkg.dev"
REMOTE_TAG="${REGISTRY_HOST}/${PROJECT}/${REPO}/sts:latest"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== deploy.sh: project=${PROJECT} zone=${ZONE} instance=${INSTANCE} =="
echo "   image target: ${REMOTE_TAG}"

# ---------------------------------------------------------------- preflight
if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud CLI not found on PATH." >&2
    exit 1
fi

echo "-- checking project access --"
if ! gcloud projects describe "${PROJECT}" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: cannot access project '${PROJECT}' with the active gcloud account.
Active account: $(gcloud config get-value account 2>/dev/null || echo '(none)')

Fix:
  gcloud auth login
  gcloud config set account <the-account-that-owns-${PROJECT}>
  gcloud config set project ${PROJECT}
Then re-run: deploy/deploy.sh
EOF
    exit 1
fi
echo "   ok"

echo "-- checking instance ${INSTANCE} exists --"
if ! gcloud compute instances describe "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" >/dev/null 2>&1; then
    echo "ERROR: instance '${INSTANCE}' not found. Run deploy/provision.sh first." >&2
    exit 1
fi
echo "   ok"

vm_ssh() {
    gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" \
        --tunnel-through-iap --command "$1"
}

echo "-- checking docker on the VM --"
if ! vm_ssh "command -v docker && docker compose version" >/dev/null 2>&1; then
    echo "ERROR: docker/compose not found on ${INSTANCE}. Run deploy/provision.sh first." >&2
    exit 1
fi
echo "   ok"

# --------------------------------------------------------- build and push
echo "-- building image for linux/amd64 (VM is x86_64, this Mac is arm64) --"
docker build --platform linux/amd64 -t sts:amd64 "${REPO_ROOT}"
LOCAL_ID="$(docker image inspect sts:amd64 --format '{{.Id}}')"

echo "-- ensuring Artifact Registry API is enabled --"
if gcloud services list --enabled --project "${PROJECT}" \
        --filter "name:artifactregistry.googleapis.com" --format "value(name)" | grep -q .; then
    echo "   already enabled"
else
    echo "   enabling (one-time, ~1 min)"
    gcloud services enable artifactregistry.googleapis.com --project "${PROJECT}"
fi

echo "-- checking Artifact Registry repo '${REPO}' in ${REGION} --"
if gcloud artifacts repositories describe "${REPO}" \
        --project "${PROJECT}" --location "${REGION}" >/dev/null 2>&1; then
    echo "   already exists"
else
    echo "   creating"
    gcloud artifacts repositories create "${REPO}" \
        --project "${PROJECT}" --location "${REGION}" \
        --repository-format docker \
        --description "sts deploy images"
fi

echo "-- configuring docker auth for ${REGISTRY_HOST} --"
gcloud auth configure-docker "${REGISTRY_HOST}" --quiet >/dev/null

CACHE_DIR="${HOME}/.cache/sts-deploy"
DIGEST_MARKER="${CACHE_DIR}/last_push_image_id_${PROJECT}"
mkdir -p "${CACHE_DIR}"

PUSHED="no (unchanged since last push)"
if [ -f "${DIGEST_MARKER}" ] && [ "$(cat "${DIGEST_MARKER}")" = "${LOCAL_ID}" ] \
        && gcloud artifacts docker images describe "${REMOTE_TAG}" >/dev/null 2>&1; then
    echo "-- image unchanged since last push (best-effort check via local image id), skipping push --"
else
    echo "-- tagging and pushing ${REMOTE_TAG} --"
    docker tag sts:amd64 "${REMOTE_TAG}"
    docker push "${REMOTE_TAG}"
    echo "${LOCAL_ID}" > "${DIGEST_MARKER}"
    PUSHED="yes"
fi
echo "   pushed this run: ${PUSHED}"

# ------------------------------------------------------------- ship files
echo "-- staging remote directories --"
vm_ssh "mkdir -p ~/sts/secrets ~/sts/configs ~/sts/cache ~/sts/ledger ~/sts/logs ~/sts/runs ~/sts/docs/preregs"

echo "-- copying files to VM (.env, secrets, universe.yaml, configs/, docker-compose.yml) --"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/.env" "${INSTANCE}:~/sts/.env"

# Stage the VM rclone.conf: repo [gdrive-sa] remote + the operator's OAuth
# [gdrive] remote from ~/.config/rclone/rclone.conf. The OAuth remote is the
# one syncs use (STS_RCLONE_REMOTE below): service accounts have no My Drive
# storage quota, so SA uploads 403 on file CREATION; OAuth uploads own files
# as the operator and always work. Re-copied every deploy so the token on
# the VM stays fresh.
LOCAL_RCLONE_CONF="${HOME}/.config/rclone/rclone.conf"
if ! grep -q '^\[gdrive\]' "${LOCAL_RCLONE_CONF}" 2>/dev/null; then
    echo "ERROR: no [gdrive] OAuth remote in ${LOCAL_RCLONE_CONF}; run 'rclone config' first." >&2
    exit 1
fi
STAGED_RCLONE_CONF="$(mktemp)"
trap 'rm -f "${STAGED_RCLONE_CONF}"' EXIT
cat "${REPO_ROOT}/secrets/rclone.conf" > "${STAGED_RCLONE_CONF}"
printf '\n' >> "${STAGED_RCLONE_CONF}"
awk '/^\[gdrive\]$/{f=1} f&&/^\[/&&!/^\[gdrive\]$/{f=0} f' \
    "${LOCAL_RCLONE_CONF}" >> "${STAGED_RCLONE_CONF}"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${STAGED_RCLONE_CONF}" "${INSTANCE}:~/sts/secrets/rclone.conf"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/secrets/sts-drive-sa.json" "${INSTANCE}:~/sts/secrets/sts-drive-sa.json"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/universe.yaml" "${INSTANCE}:~/sts/universe.yaml"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap --recurse \
    "${REPO_ROOT}/configs" "${INSTANCE}:~/sts/"

# STS_RCLONE_REMOTE must name the OAuth remote (see staging note above);
# pin idempotently.
vm_ssh "grep -v '^STS_RCLONE_REMOTE=' ~/sts/.env > ~/sts/.env.tmp || true; \
     mv ~/sts/.env.tmp ~/sts/.env; \
     echo 'STS_RCLONE_REMOTE=gdrive:' >> ~/sts/.env"

echo "-- locking down secrets (chmod 600) --"
vm_ssh "chmod 600 ~/sts/.env ~/sts/secrets/rclone.conf ~/sts/secrets/sts-drive-sa.json"

gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/deploy/docker-compose.yml" "${INSTANCE}:~/sts/docker-compose.yml"

# ------------------------------------------------------------ seed cache
echo "-- seeding bar cache (first deploy only) --"
if vm_ssh "test -n \"\$(ls -A ~/sts/cache 2>/dev/null)\"" >/dev/null 2>&1; then
    echo "   VM cache non-empty, skipping seed"
else
    tar -C "${REPO_ROOT}" -czf - cache | vm_ssh "cd ~/sts && tar -xzf -"
    echo "   seeded from local cache/"
fi

echo "-- ledger/ NOT copied: seeded by merge-only Drive sync (remote is source of truth) --"

# ------------------------------------------------------------- pull + cron
echo "-- pulling image on the VM --"
REMOTE_UID_GID="$(vm_ssh "id -u && id -g" | tr '\n' ' ')"
STS_UID="$(echo "${REMOTE_UID_GID}" | awk '{print $1}')"
STS_GID="$(echo "${REMOTE_UID_GID}" | awk '{print $2}')"
echo "   remote user: ${STS_UID}:${STS_GID}"

# The VM's docker needs the gcloud credential helper once so it can present
# the instance service account's token to Artifact Registry (requires the
# cloud-platform scope + artifactregistry.reader role — provision.sh sets both).
vm_ssh "grep -q 'us-central1-docker.pkg.dev' ~/.docker/config.json 2>/dev/null \
     && echo 'docker registry auth already configured' \
     || gcloud auth configure-docker us-central1-docker.pkg.dev --quiet"

vm_ssh "cd ~/sts && \
     export STS_IMAGE='${REMOTE_TAG}' STS_UID=${STS_UID} STS_GID=${STS_GID} && \
     docker compose pull"

echo "-- installing cron entries (idempotent, VM local time is PT) --"
ENVLINE="cd ~/sts && STS_IMAGE=${REMOTE_TAG} STS_UID=${STS_UID} STS_GID=${STS_GID}"
CRON_EOD="30 17 * * 1-5 ${ENVLINE} docker compose run --rm eod >> logs/eod.log 2>&1"
CRON_FILL="31 6 * * 1-5 ${ENVLINE} docker compose run --rm fill >> logs/fill.log 2>&1"
CRON_MONITOR="35 5,6,7,8,9,10,11,12,13 * * 1-5 ${ENVLINE} docker compose run --rm monitor >> logs/monitor.log 2>&1"

vm_ssh "(crontab -l 2>/dev/null | grep -qF 'run --rm eod' && echo 'eod cron present') || \
     ( (crontab -l 2>/dev/null; echo \"${CRON_EOD}\") | crontab - && echo 'eod cron installed' )"
vm_ssh "(crontab -l 2>/dev/null | grep -qF 'run --rm fill' && echo 'fill cron present') || \
     ( (crontab -l 2>/dev/null; echo \"${CRON_FILL}\") | crontab - && echo 'fill cron installed' )"
vm_ssh "(crontab -l 2>/dev/null | grep -qF 'run --rm monitor' && echo 'monitor cron present') || \
     ( (crontab -l 2>/dev/null; echo \"${CRON_MONITOR}\") | crontab - && echo 'monitor cron installed' )"

echo "-- status --"
vm_ssh "cd ~/sts && docker compose ps"

echo ""
echo "== deploy.sh done =="
echo ""

cat <<EOF
Tail logs with:
  gcloud compute ssh sts-forward --project stocks-that-move --zone us-west1-b --tunnel-through-iap --command "tail -f ~/sts/logs/eod.log"
EOF
