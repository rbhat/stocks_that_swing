#!/usr/bin/env bash
# Shared local-port handling for dashboard deploy helpers.

port_pids() {
    local port="$1"
    ss -H -ltnp "sport = :${port}" 2>/dev/null |
        sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' |
        sort -u
}

process_args() {
    ps -o args= -p "$1" 2>/dev/null || true
}

process_cwd() {
    readlink "/proc/$1/cwd" 2>/dev/null || true
}

is_repo_dashboard_process() {
    local pid="$1" repo_root="$2" args cwd
    args="$(process_args "${pid}")"
    cwd="$(process_cwd "${pid}")"
    case "${args}" in
        *"scripts/run_swing_dashboard.py"*) ;;
        *) return 1 ;;
    esac
    case "${cwd}" in
        "${repo_root}" | "${repo_root}/"*) return 0 ;;
        *) return 1 ;;
    esac
}

is_project_tunnel_process() {
    local pid="$1" instance="$2" local_port="$3" remote_port="$4" args
    args="$(process_args "${pid}")"
    case "${args}" in
        *"${instance}"*"-L ${local_port}:127.0.0.1:${remote_port}"*) return 0 ;;
        *"start-iap-tunnel ${instance}"*) return 0 ;;
        *) return 1 ;;
    esac
}

wait_port_free() {
    local port="$1"
    for _ in $(seq 1 10); do
        if ! port_pids "${port}" | grep -q .; then
            return 0
        fi
        sleep 1
    done
    return 1
}

kill_process_group_or_pid() {
    local pid="$1"
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
}

kill_process_group_or_pid_hard() {
    local pid="$1"
    kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
}
