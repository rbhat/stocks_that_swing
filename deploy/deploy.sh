#!/usr/bin/env bash
# Build, push, and deploy swing-ranking-v1 beside (not over) the legacy VM app.
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"
REMOTE_ROOT="sts-swing-ranking-v1"
IMAGE="sts-swing-ranking-v1:deployed"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORWARD_RUN="runs/swing-ranking-v1-forward-01"
STAGE_ONLY=0

if [ "${1:-}" = "--stage-only" ]; then
    STAGE_ONLY=1
elif [ -n "${1:-}" ]; then
    echo "Usage: deploy/deploy.sh [--stage-only]" >&2
    exit 2
fi

for command in gcloud; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "ERROR: ${command} is required." >&2
        exit 1
    }
done
test -f "${REPO_ROOT}/${FORWARD_RUN}/manifest.json" || {
    echo "ERROR: initialized forward run is missing: ${FORWARD_RUN}" >&2
    exit 1
}
gcloud compute instances describe "${INSTANCE}" \
    --project "${PROJECT}" --zone "${ZONE}" >/dev/null

vm_ssh() {
    gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" \
        --tunnel-through-iap --command "$1"
}

echo "-- building ${IMAGE} directly on ${INSTANCE} --"
tar -C "${REPO_ROOT}" \
    --exclude=.git --exclude=.venv --exclude=.scratch --exclude=cache \
    --exclude=logs --exclude=runs --exclude=reports --exclude=tests \
    --exclude=.env --exclude=secrets \
    -czf - . | vm_ssh "build_dir=\$(mktemp -d ~/${REMOTE_ROOT}-build.XXXXXX) && \
        trap 'rm -rf \"\${build_dir}\"' EXIT && tar -xzf - -C \"\${build_dir}\" && \
        docker build -t ${IMAGE} \"\${build_dir}\""

echo "-- staging isolated remote root ~/${REMOTE_ROOT} --"
vm_ssh "mkdir -p ~/${REMOTE_ROOT}/cache ~/${REMOTE_ROOT}/configs ~/${REMOTE_ROOT}/logs ~/${REMOTE_ROOT}/runs ~/${REMOTE_ROOT}/secrets"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
    "${REPO_ROOT}/deploy/docker-compose.yml" "${INSTANCE}:~/${REMOTE_ROOT}/docker-compose.yml"
gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap --recurse \
    "${REPO_ROOT}/configs" "${INSTANCE}:~/${REMOTE_ROOT}/"
if [ -f "${REPO_ROOT}/.env" ]; then
    gcloud compute scp --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        "${REPO_ROOT}/.env" "${INSTANCE}:~/${REMOTE_ROOT}/.env"
    vm_ssh "chmod 600 ~/${REMOTE_ROOT}/.env"
fi
if vm_ssh "test -f ~/${REMOTE_ROOT}/secrets/rclone.conf"; then
    echo "-- preserving the new deployment's rclone credentials --"
elif vm_ssh "test -f ~/sts/secrets/rclone.conf"; then
    echo "-- copying credentials only from the legacy deployment (not its ledger) --"
    vm_ssh "cp ~/sts/secrets/rclone.conf ~/${REMOTE_ROOT}/secrets/rclone.conf && chmod 600 ~/${REMOTE_ROOT}/secrets/rclone.conf"
else
    echo "ERROR: no VM rclone configuration is available." >&2
    exit 1
fi

if vm_ssh "test -e ~/${REMOTE_ROOT}/${FORWARD_RUN}/manifest.json"; then
    echo "-- remote forward run already exists; preserving it unchanged --"
else
    echo "-- seeding the initialized, empty forward run once --"
    tar -C "${REPO_ROOT}" -czf - "${FORWARD_RUN}" | \
        vm_ssh "cd ~/${REMOTE_ROOT} && tar -xzf -"
fi

REMOTE_IDS="$(vm_ssh "id -u; id -g")"
STS_UID="$(printf '%s\n' "${REMOTE_IDS}" | sed -n '1p')"
STS_GID="$(printf '%s\n' "${REMOTE_IDS}" | sed -n '2p')"
if [ "${STAGE_ONLY}" -eq 1 ]; then
    echo "Deployment staged; scheduler and viewer were not started."
else
    vm_ssh "cd ~/${REMOTE_ROOT} && STS_ROOT=. STS_IMAGE=${IMAGE} STS_UID=${STS_UID} STS_GID=${STS_GID} \
        docker compose up -d viewer scheduler"
    echo "Deployment active. Open it with deploy/open_remote.sh"
fi

echo "Legacy ~/sts and its Drive ledger were not modified."
