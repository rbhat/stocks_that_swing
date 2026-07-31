#!/usr/bin/env bash
# Build and run the dashboard locally. The writer is opt-in.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.yml"
IMAGE="${STS_IMAGE:-sts-swing-ranking-v1:local}"
ACTIVATE_WRITER=0

if [ "${1:-}" = "--activate-writer" ]; then
    ACTIVATE_WRITER=1
elif [ -n "${1:-}" ]; then
    echo "Usage: deploy/deploy_local.sh [--activate-writer]" >&2
    exit 2
fi

mkdir -p "${REPO_ROOT}/cache" "${REPO_ROOT}/logs" "${REPO_ROOT}/runs" "${REPO_ROOT}/secrets"
# The dashboard refuses to start without a session secret unless it is told it
# is a development instance; local runs are.
export DASHBOARD_DEV="${DASHBOARD_DEV:-1}"
# Only the writer copies to Drive; the read-only dashboard needs no credentials.
if [ "${ACTIVATE_WRITER}" -eq 1 ] && [ ! -f "${REPO_ROOT}/secrets/rclone.conf" ]; then
    echo "ERROR: secrets/rclone.conf is required for the forward Drive copy." >&2
    exit 1
fi
docker build -t "${IMAGE}" "${REPO_ROOT}"

export STS_ROOT="${REPO_ROOT}"
export STS_IMAGE="${IMAGE}"
export STS_UID="$(id -u)"
export STS_GID="$(id -g)"

docker compose -f "${COMPOSE_FILE}" up -d dashboard
if [ "${ACTIVATE_WRITER}" -eq 1 ]; then
    echo "Activating the local writer. Ensure the GCP scheduler is stopped."
    docker compose -f "${COMPOSE_FILE}" up -d scheduler
else
    echo "Local writer remains stopped (single-writer safety)."
fi
echo "Local dashboard: http://127.0.0.1:${STS_DASHBOARD_PORT:-8010}"
