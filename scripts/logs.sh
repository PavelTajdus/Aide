#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

TARGET=${2:-all}

if is_systemd_mode; then
  case "$TARGET" in
    bot)       exec journalctl -u aide-bot -f ;;
    slack)     exec journalctl -u aide-slack -f ;;
    scheduler) exec journalctl -u aide-scheduler -f ;;
    *)         exec journalctl -u 'aide-*' -f ;;
  esac
fi

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/logs.sh [/path/to/workspace] [bot|slack|scheduler]" >&2
  exit 1
fi

LOG_DIR="$WORKSPACE/data/logs"

if [[ "$TARGET" == "bot" ]]; then
  tail -f "$LOG_DIR/bot.log"
elif [[ "$TARGET" == "slack" ]]; then
  tail -f "$LOG_DIR/slack.log"
elif [[ "$TARGET" == "scheduler" ]]; then
  tail -f "$LOG_DIR/scheduler.log"
else
  tail -f "$LOG_DIR/bot.log" "$LOG_DIR/slack.log" "$LOG_DIR/scheduler.log"
fi
