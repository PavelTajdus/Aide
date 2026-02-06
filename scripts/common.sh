#!/usr/bin/env bash
# Shared library for Aide scripts. Source this, don't execute.
# Usage: source "$(cd "$(dirname "$0")" && pwd)/common.sh"

# Prevent double-sourcing
[[ -n "${_AIDE_COMMON_LOADED:-}" ]] && return 0
_AIDE_COMMON_LOADED=1

ENGINE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

resolve_workspace () {
  local arg=${1:-}

  # 1. Explicit argument
  if [[ -n "$arg" ]]; then
    $PYTHON_BIN -c "import os; print(os.path.abspath(os.path.expanduser('$arg')))"
    return
  fi

  # 2. AIDE_WORKSPACE env var
  if [[ -n "${AIDE_WORKSPACE:-}" ]]; then
    $PYTHON_BIN -c "import os; print(os.path.abspath(os.path.expanduser('${AIDE_WORKSPACE}')))"
    return
  fi

  # 3. Standard layout: engine + workspace side by side
  if [[ -d "$ENGINE_DIR/../workspace" ]]; then
    $PYTHON_BIN -c "import os; print(os.path.abspath(os.path.expanduser('$ENGINE_DIR/../workspace')))"
    return
  fi

  # 4. CWD looks like a workspace
  if [[ -f "CLAUDE.md" || -d "data" ]]; then
    pwd
    return
  fi

  # 5. Last resort fallback
  $PYTHON_BIN -c "import os; print(os.path.abspath(os.path.expanduser('~/aide-workspace')))"
}

is_systemd_mode () {
  # Returns 0 (true) if aide systemd services are installed
  command -v systemctl &>/dev/null \
    && systemctl list-unit-files 'aide-*.service' &>/dev/null \
    && [[ $(systemctl list-unit-files 'aide-*.service' 2>/dev/null | grep -c 'aide-') -gt 0 ]]
}

telegram_configured () {
  local env_file="${1:-.env}"
  [[ -f "$env_file" ]] || return 1
  local enabled token allowed
  enabled=$(grep -E "^AIDE_TELEGRAM_ENABLED=" "$env_file" | cut -d= -f2- | tr '[:upper:]' '[:lower:]' || true)
  # If explicitly disabled, not configured
  if [[ "$enabled" == "0" || "$enabled" == "false" || "$enabled" == "no" ]]; then
    return 1
  fi
  token=$(grep -E "^TELEGRAM_TOKEN=" "$env_file" | cut -d= -f2- || true)
  allowed=$(grep -E "^ALLOWED_USERS=" "$env_file" | cut -d= -f2- || true)
  [[ -n "$token" && "$token" != "YOUR_TELEGRAM_BOT_TOKEN" && -n "$allowed" ]]
}

kill_stray_aide_processes () {
  # Kill any orphan Aide Python processes not managed by systemd.
  # This prevents duplicate processes after manual runs from terminal.
  local scripts=("main.py" "slack_bot.py" "scheduler.py")
  local killed=0
  for script in "${scripts[@]}"; do
    local pids
    pids=$(pgrep -f "python.*${script}.*--workspace" 2>/dev/null || true)
    for pid in $pids; do
      # Skip if managed by systemd (ppid=1 with systemd unit)
      local service_pid
      service_pid=$(systemctl show "aide-${script%%.*}" --property=MainPID --value 2>/dev/null || echo "0")
      # Map script name to service: main.py→aide-bot, slack_bot.py→aide-slack, scheduler.py→aide-scheduler
      case "$script" in
        main.py)       service_pid=$(systemctl show aide-bot --property=MainPID --value 2>/dev/null || echo "0") ;;
        slack_bot.py)  service_pid=$(systemctl show aide-slack --property=MainPID --value 2>/dev/null || echo "0") ;;
        scheduler.py)  service_pid=$(systemctl show aide-scheduler --property=MainPID --value 2>/dev/null || echo "0") ;;
      esac
      if [[ "$pid" != "$service_pid" ]]; then
        echo "Killing stray $script (pid $pid)"
        kill "$pid" 2>/dev/null || true
        killed=$((killed + 1))
      fi
    done
  done
  if [[ $killed -gt 0 ]]; then
    sleep 1
  fi
}

slack_configured () {
  local env_file="${1:-.env}"
  [[ -f "$env_file" ]] || return 1
  local enabled bot_token app_token
  enabled=$(grep -E "^AIDE_SLACK_ENABLED=" "$env_file" | cut -d= -f2- | tr '[:upper:]' '[:lower:]' || true)
  if [[ "$enabled" == "0" || "$enabled" == "false" || "$enabled" == "no" ]]; then
    return 1
  fi
  bot_token=$(grep -E "^SLACK_BOT_TOKEN=" "$env_file" | cut -d= -f2- || true)
  app_token=$(grep -E "^SLACK_APP_TOKEN=" "$env_file" | cut -d= -f2- || true)
  [[ -n "$bot_token" && "$bot_token" != "YOUR_SLACK_BOT_TOKEN" \
    && -n "$app_token" && "$app_token" != "YOUR_SLACK_APP_TOKEN" ]]
}
