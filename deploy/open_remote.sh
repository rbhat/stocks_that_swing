#!/usr/bin/env bash
# Open an IAP tunnel to the dashboard on sts-forward.
#
# Usage:
#   deploy/open_remote.sh
#   deploy/open_remote.sh --stop
#
# Env overrides:
#   STS_PROJECT=stocks-that-move
#   STS_ZONE=us-west1-b
#   STS_INSTANCE=sts-forward
#   DASHBOARD_LOCAL_PORT=8000
#   DASHBOARD_REMOTE_PORT=8000
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"
LOCAL_PORT="${DASHBOARD_LOCAL_PORT:-8000}"
REMOTE_PORT="${DASHBOARD_REMOTE_PORT:-8000}"
REMOTE_HOST="localhost"

PIDFILE="${TMPDIR:-/tmp}/sts-open-remote-${PROJECT}-${INSTANCE}-${LOCAL_PORT}.pid"
LOGFILE="${TMPDIR:-/tmp}/sts-open-remote-${PROJECT}-${INSTANCE}-${LOCAL_PORT}.log"
URL="http://127.0.0.1:${LOCAL_PORT}"

usage() {
    cat <<EOF
Usage:
  deploy/open_remote.sh
  deploy/open_remote.sh --stop
EOF
}

stop_tunnel() {
    if [ -f "${PIDFILE}" ]; then
        pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
        if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
            kill "${pid}" >/dev/null 2>&1 || true
            for _ in $(seq 1 20); do
                if ! kill -0 "${pid}" >/dev/null 2>&1; then
                    break
                fi
                sleep 0.2
            done
        fi
        rm -f "${PIDFILE}"
        echo "Stopped tunnel recorded in ${PIDFILE}"
        return 0
    fi

    echo "No tunnel pidfile found at ${PIDFILE}"
    return 0
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

if [ "${1:-}" = "--stop" ]; then
    stop_tunnel
    exit 0
fi

if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud CLI not found on PATH." >&2
    exit 1
fi

if ! gcloud projects describe "${PROJECT}" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: cannot access project '${PROJECT}' with the active gcloud account.
Active account: $(gcloud config get-value account 2>/dev/null || echo '(none)')

Fix:
  gcloud auth login
  gcloud config set account <the-account-that-owns-${PROJECT}>
  gcloud config set project ${PROJECT}
Then re-run: deploy/open_remote.sh
EOF
    exit 1
fi

if ! gcloud compute instances describe "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" >/dev/null 2>&1; then
    echo "ERROR: instance '${INSTANCE}' not found in ${PROJECT}/${ZONE}. Run deploy/provision.sh first." >&2
    exit 1
fi

if [ -f "${PIDFILE}" ] && kill -0 "$(cat "${PIDFILE}" 2>/dev/null || true)" >/dev/null 2>&1; then
    echo "Tunnel already running for ${URL} (pid $(cat "${PIDFILE}"))"
else
    rm -f "${PIDFILE}"
    echo "-- starting tunnel to ${INSTANCE} --"
    : >"${LOGFILE}"
    nohup gcloud compute ssh "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        -- -N -L "${LOCAL_PORT}:${REMOTE_HOST}:${REMOTE_PORT}" \
        >>"${LOGFILE}" 2>&1 &
    echo $! >"${PIDFILE}"
fi

echo "-- waiting for ${URL}/healthz --"
ready=0
for i in $(seq 1 30); do
    if curl -fsS "${URL}/healthz" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 1
done

if [ "${ready}" -ne 1 ]; then
    cat <<EOF
Tunnel started, but ${URL}/healthz did not respond in time.
PID: $(cat "${PIDFILE}" 2>/dev/null || echo unknown)
Log: ${LOGFILE}
EOF
    exit 1
fi

echo "Dashboard URL: ${URL}"

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${URL}" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
    open "${URL}" >/dev/null 2>&1 || true
fi
