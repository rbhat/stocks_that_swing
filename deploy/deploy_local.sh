#!/usr/bin/env bash
# Build and run the dashboard locally. The writer is opt-in.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker-compose.yml"
IMAGE="${STS_IMAGE:-sts-swing-ranking-v1:local}"
LOCAL_PORT="${STS_DASHBOARD_PORT:-8010}"
ACTIVATE_WRITER=0

# shellcheck source=deploy/port_utils.sh
. "${REPO_ROOT}/deploy/port_utils.sh"

if [ "${1:-}" = "--activate-writer" ]; then
    ACTIVATE_WRITER=1
elif [ -n "${1:-}" ]; then
    echo "Usage: deploy/deploy_local.sh [--activate-writer]" >&2
    exit 2
fi

mkdir -p "${REPO_ROOT}/cache" "${REPO_ROOT}/logs" "${REPO_ROOT}/runs" "${REPO_ROOT}/secrets"
LEGACY_ROOT="${STS_LEGACY_ROOT:-${REPO_ROOT}/.scratch/legacy-dashboard}"
mkdir -p "${LEGACY_ROOT}/ledger" "${LEGACY_ROOT}/runs" "${LEGACY_ROOT}/runs-summary" \
    "${LEGACY_ROOT}/logs" "${LEGACY_ROOT}/configs"
touch "${LEGACY_ROOT}/universe.yaml" "${REPO_ROOT}/legacy-env.redacted"
# The dashboard refuses to start without a session secret unless it is told it
# is a development instance; local runs are.
export DASHBOARD_DEV="${DASHBOARD_DEV:-1}"
# Only the writer copies to Drive; the read-only dashboard needs no credentials.
if [ "${ACTIVATE_WRITER}" -eq 1 ] && [ ! -f "${REPO_ROOT}/secrets/rclone.conf" ]; then
    echo "ERROR: secrets/rclone.conf is required for the forward Drive copy." >&2
    exit 1
fi

reclaim_local_dashboard_port() {
    local pid found=0
    for pid in $(port_pids "${LOCAL_PORT}"); do
        if is_repo_dashboard_process "${pid}" "${REPO_ROOT}"; then
            echo "Stopping existing local dashboard on port ${LOCAL_PORT} (pid ${pid})."
            kill_process_group_or_pid "${pid}"
            found=1
        fi
    done
    if [ "${found}" -eq 0 ]; then
        return 0
    fi
    if wait_port_free "${LOCAL_PORT}"; then
        return 0
    fi
    for pid in $(port_pids "${LOCAL_PORT}"); do
        if is_repo_dashboard_process "${pid}" "${REPO_ROOT}"; then
            kill_process_group_or_pid_hard "${pid}"
        fi
    done
    wait_port_free "${LOCAL_PORT}"
}

if ! reclaim_local_dashboard_port; then
    echo "ERROR: port ${LOCAL_PORT} is still held by a local dashboard process." >&2
    exit 1
fi

docker build -t "${IMAGE}" "${REPO_ROOT}"

export STS_ROOT="${REPO_ROOT}"
export STS_IMAGE="${IMAGE}"
export STS_UID="$(id -u)"
export STS_GID="$(id -g)"
export STS_LEGACY_ROOT="${LEGACY_ROOT}"
export STS_LEGACY_ADMIN_RUNNER="${REPO_ROOT}/scripts/run_legacy_admin_runner.py"
export STS_DASHBOARD_CACHE_ROOT="${REPO_ROOT}/cache"

docker compose -f "${COMPOSE_FILE}" up -d dashboard
if [ "${ACTIVATE_WRITER}" -eq 1 ]; then
    echo "Activating the local writer. Ensure the GCP scheduler is stopped."
    docker compose -f "${COMPOSE_FILE}" up -d scheduler
else
    echo "Local writer remains stopped (single-writer safety)."
fi
echo "Local dashboard: http://127.0.0.1:${LOCAL_PORT}"
