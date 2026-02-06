#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

if is_systemd_mode; then
  for svc in aide-bot aide-slack aide-scheduler; do
    state=$(systemctl is-active "$svc" 2>/dev/null || true)
    echo "$svc: $state"
  done
  exit 0
fi

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/status.sh [/path/to/workspace]" >&2
  exit 1
fi

PID_DIR="$WORKSPACE/data/pids"

status_proc () {
  local name=$1
  local pid_file="$PID_DIR/$name.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name: stopped"
    return
  fi

  local pid
  pid=$(cat "$pid_file" || true)
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$name: running (pid $pid)"
  else
    echo "$name: stopped (stale pid file)"
  fi
}

status_proc "bot"
status_proc "slack"
status_proc "scheduler"
