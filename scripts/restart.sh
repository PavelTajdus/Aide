#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

# Update Claude Code if available
if command -v claude &>/dev/null; then
  echo "Updating Claude Code..."
  claude update 2>&1 || echo "Claude Code update skipped (already latest or offline)"
fi

if is_systemd_mode; then
  WORKSPACE=$(resolve_workspace "${1:-}")

  # Kill any orphan processes from manual runs
  kill_stray_aide_processes

  echo "Restarting Aide services (systemd)..."

  # Scheduler always runs
  sudo systemctl restart aide-scheduler
  echo "aide-scheduler restarted"

  if telegram_configured "$WORKSPACE/.env"; then
    sudo systemctl restart aide-bot
    echo "aide-bot restarted"
  else
    sudo systemctl stop aide-bot 2>/dev/null || true
    echo "aide-bot stopped (telegram not configured)"
  fi

  if slack_configured "$WORKSPACE/.env"; then
    sudo systemctl restart aide-slack
    echo "aide-slack restarted"
  else
    sudo systemctl stop aide-slack 2>/dev/null || true
    echo "aide-slack stopped (slack not configured)"
  fi
else
  "$ENGINE_DIR/scripts/stop.sh" "${1:-}"
  "$ENGINE_DIR/scripts/run.sh" "${1:-}"
fi
