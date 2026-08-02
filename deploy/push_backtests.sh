#!/usr/bin/env bash
# Push the curated backtest subset the dashboard reads to the VM.
#
# `runs/swing-ranking-v1` is ~992 MB locally and exists only on this machine;
# deploy.sh excludes runs/ from the build context, so the VM has no backtest
# artifacts at all. Almost all of that bulk is development/validation
# per-revision raw detail (candidates.jsonl 381 MB, events.jsonl 205 MB,
# orders.jsonl 97 MB, and the strategies/ geometries). The curated set below
# keeps compact window evidence plus the small OOS candidate/geometry files
# needed for report trade charts.
#
# It adds and updates; it never deletes remote files, matching the discipline
# in scripts/sync_swing_artifacts.py. The remote copy is read-only evidence:
# the scheduler writes only its own forward run.
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"
REMOTE_ROOT="sts-swing-ranking-v1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ROOT="${REPO_ROOT}/runs/swing-ranking-v1"
TUNNEL_PORT="${STS_RSYNC_PORT:-2222}"
DRY_RUN=0

# Per-window files the dashboard reads. Raw projections are deliberately absent.
WINDOW_FILES=(
    manifest.json
    protocol.json
    ranking.json
    metrics.jsonl
    equity.jsonl
    trades.jsonl
    report.md
    selection.json
    strategy_names.json
)
WINDOWS=(development-v1 validation-v1 oos-v1)
# Small enough to ship whole, and the chart-ready core of the evidence view.
WHOLE_DIRS=(oos-cohort-comparison-v1 oos-seal-v1)

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
elif [ -n "${1:-}" ]; then
    echo "Usage: deploy/push_backtests.sh [--dry-run]" >&2
    exit 2
fi

for command in gcloud rsync ssh; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "ERROR: ${command} is required." >&2
        exit 1
    }
done
test -d "${LOCAL_ROOT}" || {
    echo "ERROR: ${LOCAL_ROOT} is missing; run this from the machine holding the backtests." >&2
    exit 1
}

# `strategy_names.json` is generated, not part of any artifact's content set.
# Refresh it before the push so identities resolve to names on the VM, where
# the fat strategies/ directories are not present.
echo "-- refreshing the compact strategy-name indexes --"
PYTHON="${STS_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [ -x "${PYTHON}" ]; then
    "${PYTHON}" "${REPO_ROOT}/scripts/export_strategy_names.py" --runs-root "${LOCAL_ROOT}"
else
    echo "WARNING: ${PYTHON} not found; pushing whatever indexes already exist." >&2
fi

MANIFEST="$(mktemp)"
trap 'rm -f "${MANIFEST}"' EXIT
for window in "${WINDOWS[@]}"; do
    for name in "${WINDOW_FILES[@]}"; do
        test -f "${LOCAL_ROOT}/${window}/${name}" && printf '%s/%s\n' "${window}" "${name}"
    done
done >>"${MANIFEST}"
for dir in "${WHOLE_DIRS[@]}"; do
    test -d "${LOCAL_ROOT}/${dir}" && printf '%s/\n' "${dir}"
done >>"${MANIFEST}"
test -f "${LOCAL_ROOT}/oos-v1/candidates.jsonl" && printf '%s\n' "oos-v1/candidates.jsonl" >>"${MANIFEST}"
test -d "${LOCAL_ROOT}/oos-v1/strategies" && printf '%s/\n' "oos-v1/strategies" >>"${MANIFEST}"

FILE_COUNT="$(wc -l <"${MANIFEST}")"
BYTES="$(cd "${LOCAL_ROOT}" && du -cb $(sed 's:/$::' "${MANIFEST}") 2>/dev/null | tail -1 | cut -f1)"
echo "-- curated subset: ${FILE_COUNT} entries, $((BYTES / 1024 / 1024)) MB --"

if [ "${DRY_RUN}" -eq 1 ]; then
    sed 's/^/    /' "${MANIFEST}"
    exit 0
fi

gcloud compute instances describe "${INSTANCE}" \
    --project "${PROJECT}" --zone "${ZONE}" >/dev/null

# rsync needs a plain ssh it can invoke per-file, but `gcloud compute ssh`
# wraps ssh in a quoted ProxyCommand that rsync's -e cannot parse (it splits
# on whitespace and does not honour quotes). So open the IAP tunnel to port 22
# ourselves and point a plain ssh at it. The identity, host-key alias, and
# login name are taken from gcloud's own --dry-run so host-key verification
# stays on and matches the key gcloud already trusts.
SSH_LINE="$(gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" \
    --tunnel-through-iap --dry-run)"
IDENTITY="$(printf '%s\n' "${SSH_LINE}" | sed -n 's/.* -i \([^ ]*\).*/\1/p')"
HOST_ALIAS="$(printf '%s\n' "${SSH_LINE}" | sed -n 's/.*HostKeyAlias=\([^ ]*\).*/\1/p')"
KNOWN_HOSTS="$(printf '%s\n' "${SSH_LINE}" | sed -n 's/.*UserKnownHostsFile=\([^ ]*\).*/\1/p')"
REMOTE_USER="$(printf '%s\n' "${SSH_LINE}" | sed -n 's/.* \([^ @]*\)@[^ ]*$/\1/p')"
if [ -z "${IDENTITY}" ] || [ -z "${HOST_ALIAS}" ] || [ -z "${REMOTE_USER}" ]; then
    echo "ERROR: could not derive the ssh parameters from gcloud." >&2
    echo "gcloud printed: ${SSH_LINE}" >&2
    exit 1
fi

TUNNEL_LOG="${TMPDIR:-/tmp}/sts-push-backtests-${TUNNEL_PORT}.log"
setsid gcloud compute start-iap-tunnel "${INSTANCE}" 22 \
    --project "${PROJECT}" --zone "${ZONE}" \
    --local-host-port="localhost:${TUNNEL_PORT}" >"${TUNNEL_LOG}" 2>&1 &
TUNNEL_PID=$!
# gcloud spawns children, so signal the whole process group like open_remote.sh.
cleanup() {
    kill -- "-${TUNNEL_PID}" 2>/dev/null || kill "${TUNNEL_PID}" 2>/dev/null || true
    rm -f "${MANIFEST}"
}
trap cleanup EXIT

for _ in $(seq 1 30); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${TUNNEL_PORT}") 2>/dev/null; then
        exec 3>&- 3<&-
        break
    fi
    if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
        echo "ERROR: the IAP tunnel exited. Last log lines:" >&2
        tail -n 20 "${TUNNEL_LOG}" >&2 || true
        exit 1
    fi
    sleep 1
done

RSH="ssh -p ${TUNNEL_PORT} -i ${IDENTITY} -o IdentitiesOnly=yes -o CheckHostIP=no"
RSH="${RSH} -o HostKeyAlias=${HOST_ALIAS} -o StrictHostKeyChecking=yes"
test -n "${KNOWN_HOSTS}" && RSH="${RSH} -o UserKnownHostsFile=${KNOWN_HOSTS}"

REMOTE_DIR="${REMOTE_ROOT}/runs/swing-ranking-v1"
# rsync must exist on both ends; the VM image does not ship it.
if ! ${RSH} "${REMOTE_USER}@127.0.0.1" "command -v rsync >/dev/null 2>&1"; then
    echo "-- installing rsync on ${INSTANCE} --"
    ${RSH} "${REMOTE_USER}@127.0.0.1" \
        "sudo apt-get update -qq && sudo apt-get install -y -qq rsync" || {
        echo "ERROR: rsync is missing on ${INSTANCE} and could not be installed." >&2
        exit 1
    }
fi
${RSH} "${REMOTE_USER}@127.0.0.1" "mkdir -p ~/${REMOTE_DIR}"

echo "-- rsyncing to ${INSTANCE}:~/${REMOTE_DIR} --"
rsync -rlptz --human-readable --progress \
    --files-from="${MANIFEST}" \
    -e "${RSH}" \
    "${LOCAL_ROOT}/" "${REMOTE_USER}@127.0.0.1:${REMOTE_DIR}/"

echo "-- verifying --"
${RSH} "${REMOTE_USER}@127.0.0.1" \
    "cd ~/${REMOTE_DIR} && du -sh . && find . -type f | wc -l"

echo "Backtests pushed. The forward run and the legacy deployment were not touched."
