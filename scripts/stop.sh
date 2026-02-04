#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=${PYTHON_BIN:-python3}

resolve_workspace () {
  local arg=${1:-}
  if [[ -n "$arg" ]]; then
    $PYTHON_BIN - <<PY
import os
print(os.path.abspath(os.path.expanduser("$arg")))
PY
    return
  fi

  if [[ -n "${AIDE_WORKSPACE:-}" ]]; then
    $PYTHON_BIN - <<PY
import os
print(os.path.abspath(os.path.expanduser("${AIDE_WORKSPACE}")))
PY
    return
  fi

  if [[ -f "CLAUDE.md" || -d "data" ]]; then
    pwd
    return
  fi

  $PYTHON_BIN - <<PY
import os
print(os.path.abspath(os.path.expanduser("~/aide-workspace")))
PY
}

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/stop.sh /path/to/workspace" >&2
  exit 1
fi

PID_DIR="$WORKSPACE/data/pids"

stop_proc () {
  local name=$1
  local pid_file="$PID_DIR/$name.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running"
    return
  fi

  local pid
  pid=$(cat "$pid_file" || true)
  if [[ -z "${pid:-}" ]]; then
    rm -f "$pid_file"
    echo "$name not running"
    return
  fi

  if kill -0 "$pid" 2>/dev/null; then
    echo "Stopping $name (pid $pid)..."
    kill "$pid" || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" || true
    fi
  fi

  rm -f "$pid_file"
  echo "$name stopped"
}

stop_proc "bot"
stop_proc "scheduler"
