#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

if is_systemd_mode; then
  echo "Aide services managed by systemd. Use: scripts/restart.sh" >&2
  exit 1
fi

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/run.sh [/path/to/workspace]" >&2
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
    # Stale PID file — process is dead
    rm -f "$pid_file"
    echo "$name: removed stale pid file"
  fi

  echo "Starting $name..."
  nohup bash -lc "$cmd" > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$pid_file"
  echo "$name started (pid $(cat "$pid_file"))"
}

if telegram_configured "$WORKSPACE/.env"; then
  start_proc "bot" "$PYTHON_BIN \"$ENGINE_DIR/main.py\" --workspace \"$WORKSPACE\""
else
  echo "Telegram not configured; skipping telegram bot."
fi

if slack_configured "$WORKSPACE/.env"; then
  start_proc "slack" "$PYTHON_BIN \"$ENGINE_DIR/slack_bot.py\" --workspace \"$WORKSPACE\""
else
  echo "Slack not configured; skipping slack bot."
fi

start_proc "scheduler" "$PYTHON_BIN \"$ENGINE_DIR/scheduler.py\" --workspace \"$WORKSPACE\""

echo "Logs: $LOG_DIR/bot.log, $LOG_DIR/slack.log, $LOG_DIR/scheduler.log"
