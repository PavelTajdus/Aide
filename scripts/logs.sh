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
  echo "Usage: ./scripts/logs.sh /path/to/workspace [bot|scheduler]" >&2
  exit 1
fi

LOG_DIR="$WORKSPACE/data/logs"
TARGET=${2:-all}

if [[ "$TARGET" == "bot" ]]; then
  tail -f "$LOG_DIR/bot.log"
elif [[ "$TARGET" == "scheduler" ]]; then
  tail -f "$LOG_DIR/scheduler.log"
else
  tail -f "$LOG_DIR/bot.log" "$LOG_DIR/scheduler.log"
fi
