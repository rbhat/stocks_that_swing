#!/usr/bin/env zsh
# Install/uninstall the STS forward-paper launchd agents.
#
# ASSUMPTION: launchd has no native timezone support -- StartCalendarInterval
# fires against the machine's LOCAL timezone. All schedules in this
# directory are authored assuming the machine's local tz is
# America/Los_Angeles. If this Mac is ever set to a different tz, the
# plists must be regenerated with adjusted Hour values.
#
# Usage:
#   ./install.sh        install/reinstall all agents (idempotent)
#   ./install.sh -u      uninstall all agents
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
DEST_DIR="$HOME/Library/LaunchAgents"
LABELS=(com.sts.forward-eod com.sts.forward-fill com.sts.forward-monitor)

UNINSTALL=0
while getopts "u" opt; do
  case "$opt" in
    u) UNINSTALL=1 ;;
    *) echo "usage: $0 [-u]" >&2; exit 1 ;;
  esac
done

mkdir -p "$DEST_DIR"
mkdir -p "$REPO_ROOT/logs/forward"

for label in "${LABELS[@]}"; do
  plist_name="${label}.plist"
  dest_plist="$DEST_DIR/$plist_name"

  echo "-> launchctl bootout gui/$UID/$label (ignore failure if not loaded)"
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true

  if [[ "$UNINSTALL" -eq 1 ]]; then
    rm -f "$dest_plist"
    echo "-> removed $dest_plist"
    continue
  fi

  src_plist="$SCRIPT_DIR/$plist_name"
  if [[ ! -f "$src_plist" ]]; then
    echo "ERROR: missing $src_plist" >&2
    exit 1
  fi

  sed "s|__REPO__|$REPO_ROOT|g" "$src_plist" > "$dest_plist"
  echo "-> wrote $dest_plist (REPO=$REPO_ROOT)"

  launchctl bootstrap "gui/$UID" "$dest_plist"
  echo "-> bootstrapped $label"
done

if [[ "$UNINSTALL" -eq 1 ]]; then
  echo "Uninstalled all STS forward-paper launchd agents."
else
  echo "Installed all STS forward-paper launchd agents. Logs: $REPO_ROOT/logs/forward/"
fi
