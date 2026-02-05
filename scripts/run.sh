#!/usr/bin/env bash
set -euo pipefail

ENGINE_DIR=$(cd "$(dirname "$0")/.." && pwd)
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
  echo "Usage: ./scripts/run.sh /path/to/workspace" >&2
  exit 1
fi

LOG_DIR="$WORKSPACE/data/logs"
PID_DIR="$WORKSPACE/data/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

start_proc () {
  local name=$1
  local cmd=$2
  local pid_file="$PID_DIR/$name.pid"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file" || true)
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$name already running (pid $pid)"
      return
    fi
  fi

  echo "Starting $name..."
  nohup bash -lc "$cmd" > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$pid_file"
  echo "$name started (pid $(cat "$pid_file"))"
}

telegram_enabled=$(grep -E "^AIDE_TELEGRAM_ENABLED=" "$WORKSPACE/.env" | cut -d= -f2- || true)
telegram_token=$(grep -E "^TELEGRAM_TOKEN=" "$WORKSPACE/.env" | cut -d= -f2- || true)

if [[ "${telegram_enabled,,}" != "0" && "${telegram_enabled,,}" != "false" && "${telegram_enabled,,}" != "no" ]]; then
  if [[ -n "$telegram_token" && "$telegram_token" != "YOUR_TELEGRAM_BOT_TOKEN" ]]; then
    start_proc "bot" "$PYTHON_BIN \"$ENGINE_DIR/main.py\" --workspace \"$WORKSPACE\""
  else
    echo "Telegram not configured (missing TELEGRAM_TOKEN); skipping telegram bot."
  fi
fi

slack_enabled=$(grep -E "^AIDE_SLACK_ENABLED=" "$WORKSPACE/.env" | cut -d= -f2- || true)
slack_token=$(grep -E "^SLACK_BOT_TOKEN=" "$WORKSPACE/.env" | cut -d= -f2- || true)
slack_app_token=$(grep -E "^SLACK_APP_TOKEN=" "$WORKSPACE/.env" | cut -d= -f2- || true)

if [[ "${slack_enabled,,}" != "0" && "${slack_enabled,,}" != "false" && "${slack_enabled,,}" != "no" ]]; then
  if [[ -n "$slack_token" && "$slack_token" != "YOUR_SLACK_BOT_TOKEN" && -n "$slack_app_token" && "$slack_app_token" != "YOUR_SLACK_APP_TOKEN" ]]; then
    start_proc "slack" "$PYTHON_BIN \"$ENGINE_DIR/slack_bot.py\" --workspace \"$WORKSPACE\""
  else
    echo "Slack not configured (missing SLACK_BOT_TOKEN/SLACK_APP_TOKEN); skipping slack bot."
  fi
fi

start_proc "scheduler" "$PYTHON_BIN \"$ENGINE_DIR/scheduler.py\" --workspace \"$WORKSPACE\""

echo "Logs: $LOG_DIR/bot.log, $LOG_DIR/slack.log, $LOG_DIR/scheduler.log"
