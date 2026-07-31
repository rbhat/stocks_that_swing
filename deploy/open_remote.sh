#!/usr/bin/env bash
# Open an IAP tunnel to the swing-ranking-v1 dashboard on sts-forward, and to
# the legacy dashboard beside it.
#
# One ssh invocation carries both forwards. The new dashboard links to the
# legacy one as plain markup rather than reverse-proxying it: the legacy app
# does Google OAuth through authlib, sets signed cookies at `/`, and
# 303-redirects unauthenticated requests, all of which break under a subpath.
# Two -L forwards in one process group means --stop still reaps both.
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"
LOCAL_PORT="${STS_DASHBOARD_LOCAL_PORT:-8010}"
REMOTE_PORT="${STS_DASHBOARD_REMOTE_PORT:-8010}"
LEGACY_LOCAL_PORT="${STS_LEGACY_LOCAL_PORT:-8000}"
LEGACY_REMOTE_PORT="${STS_LEGACY_REMOTE_PORT:-8000}"
PIDFILE="${TMPDIR:-/tmp}/sts-swing-ranking-dashboard-${LOCAL_PORT}.pid"
LOGFILE="${TMPDIR:-/tmp}/sts-swing-ranking-dashboard-${LOCAL_PORT}.log"
URL="http://127.0.0.1:${LOCAL_PORT}"
LEGACY_URL="http://127.0.0.1:${LEGACY_LOCAL_PORT}"

# /healthz answers without a session on both apps; / redirects to a login page.
probe() {
    curl -fsS --max-time 5 "$1/healthz" >/dev/null 2>&1
}

tunnel_pid() {
    test -f "${PIDFILE}" || return 1
    local pid
    pid="$(sed -n '1p' "${PIDFILE}")"
    case "${pid}" in
        "" | *[!0-9]*) return 1 ;;
    esac
    kill -0 "${pid}" 2>/dev/null || return 1
    printf '%s\n' "${pid}"
}

# gcloud runs ssh as a child process, so the whole process group must be
# signalled. Killing only the recorded pid orphans ssh and leaks both ports.
stop_tunnel() {
    local pid
    if pid="$(tunnel_pid)"; then
        kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
        for _ in $(seq 1 10); do
            kill -0 "${pid}" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "${pid}" 2>/dev/null; then
            kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
        fi
    fi
    rm -f "${PIDFILE}"
}

if [ "${1:-}" = "--stop" ]; then
    stop_tunnel
    echo "Remote dashboard tunnels stopped."
    exit 0
elif [ -n "${1:-}" ]; then
    echo "Usage: deploy/open_remote.sh [--stop]" >&2
    exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud CLI not found." >&2
    exit 1
fi
if ! gcloud compute instances describe "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" >/dev/null 2>&1; then
    echo "ERROR: cannot find ${PROJECT}/${ZONE}/${INSTANCE}." >&2
    exit 1
fi

if tunnel_pid >/dev/null; then
    echo "Tunnel already running."
else
    # A dead pidfile may still have left ssh bound to either port.
    rm -f "${PIDFILE}"
    for port in "${LOCAL_PORT}" "${LEGACY_LOCAL_PORT}"; do
        if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
            exec 3>&- 3<&-
            echo "ERROR: port ${port} is already held by an untracked process." >&2
            echo "Stop whatever owns it, then retry." >&2
            exit 1
        fi
    done
    # setsid puts the tunnel in its own process group so --stop can signal
    # gcloud and its ssh child together.
    setsid gcloud compute ssh "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        -- -N \
        -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
        -L "${LEGACY_LOCAL_PORT}:127.0.0.1:${LEGACY_REMOTE_PORT}" \
        >"${LOGFILE}" 2>&1 &
    echo $! >"${PIDFILE}"
fi

# 8010 is required; 8000 is best-effort, so a stopped legacy container never
# fails the new dashboard.
for _ in $(seq 1 30); do
    if probe "${URL}"; then
        echo "Swing ranking dashboard: ${URL}"
        if probe "${LEGACY_URL}"; then
            echo "Legacy dashboard:          ${LEGACY_URL}"
        else
            echo "Legacy dashboard:          not answering on ${LEGACY_URL} (tunnel is open)." >&2
        fi
        exit 0
    fi
    if ! tunnel_pid >/dev/null; then
        echo "ERROR: the tunnel process exited. Last log lines:" >&2
        tail -n 20 "${LOGFILE}" >&2 || true
        rm -f "${PIDFILE}"
        exit 1
    fi
    sleep 1
done
echo "Tunnel is up but the dashboard did not respond on port ${REMOTE_PORT}." >&2
echo "Confirm the remote service is running:" >&2
echo "  gcloud compute ssh ${INSTANCE} --project ${PROJECT} --zone ${ZONE} \\" >&2
echo "    --tunnel-through-iap --command 'cd ~/sts-swing-ranking-v1 && docker compose ps'" >&2
echo "See ${LOGFILE}." >&2
exit 1
