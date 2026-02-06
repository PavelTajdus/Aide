#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

if is_systemd_mode; then
  for svc in aide-bot aide-slack aide-scheduler; do
    systemctl status --no-pager "$svc" 2>/dev/null || true
    echo
  done
  exit 0
fi

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/ps.sh [/path/to/workspace]" >&2
  exit 1
fi

PID_DIR="$WORKSPACE/data/pids"

show_proc () {
  local name=$1
  local pid_file="$PID_DIR/$name.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: stopped"
    return
  fi
  local pid
  pid=$(cat "$pid_file" || true)
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    ps -p "$pid" -o pid,ppid,command=
  else
    echo "$name: stopped (stale pid file)"
  fi
}

show_proc "bot"
show_proc "slack"
show_proc "scheduler"
