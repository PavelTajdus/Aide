#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

WORKSPACE=${1:-}
if [[ -z "$WORKSPACE" ]]; then
  echo "Usage: ./scripts/init.sh /path/to/workspace" >&2
  exit 1
fi

WORKSPACE=$($PYTHON_BIN -c "import os; print(os.path.abspath(os.path.expanduser('$WORKSPACE')))")
ENGINE_VERSION=$(cat "$ENGINE_DIR/VERSION")

mkdir -p "$WORKSPACE" \
  "$WORKSPACE/.claude/skills" \
  "$WORKSPACE/tools" \
  "$WORKSPACE/knowledge" \
  "$WORKSPACE/conversations" \
  "$WORKSPACE/data/projects" \
  "$WORKSPACE/data/logs" \
  "$WORKSPACE/inbox"

if [[ ! -f "$WORKSPACE/CLAUDE.md" ]]; then
  cp "$ENGINE_DIR/templates/CLAUDE.md" "$WORKSPACE/CLAUDE.md"
fi

if [[ ! -f "$WORKSPACE/.gitignore" ]]; then
  cp "$ENGINE_DIR/templates/workspace.gitignore" "$WORKSPACE/.gitignore"
fi

if [[ ! -f "$WORKSPACE/.env" ]]; then
  cat > "$WORKSPACE/.env" <<ENV
AIDE_WORKSPACE=$WORKSPACE
AIDE_ENGINE=$ENGINE_DIR
AIDE_TELEGRAM_ENABLED=1
TELEGRAM_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ALLOWED_USERS=
AIDE_DEFAULT_CHAT_ID=
AIDE_NOTIFY_PROVIDER=telegram
SLACK_BOT_TOKEN=YOUR_SLACK_BOT_TOKEN
SLACK_APP_TOKEN=YOUR_SLACK_APP_TOKEN
AIDE_SLACK_ENABLED=0
AIDE_SLACK_ALLOWED_USERS=
AIDE_SLACK_DEFAULT_TARGET=
AIDE_SLACK_DEFAULT_CHANNEL_ID=
AIDE_SLACK_DEFAULT_USER_ID=
AIDE_SLACK_DEFAULT_TARGET_TYPE=auto
AIDE_SLACK_PROGRESS=1
AIDE_SLACK_MAX_FILE_MB=10
AIDE_CLAUDE_SKIP_PERMISSIONS=1
AIDE_HEARTBEAT_SOON_HOURS=24
AIDE_HEARTBEAT_START_HOUR=8
AIDE_HEARTBEAT_END_HOUR=22
ENV
fi

# Symlink default skills into workspace
for skill in "$ENGINE_DIR/default_skills"/*.md; do
  name=$(basename "$skill")
  target="$WORKSPACE/.claude/skills/$name"
  ln -sfn "$skill" "$target"
done

if [[ ! -f "$WORKSPACE/data/sessions.json" ]]; then
  echo '{}' > "$WORKSPACE/data/sessions.json"
fi
if [[ ! -f "$WORKSPACE/data/sessions_slack.json" ]]; then
  echo '{}' > "$WORKSPACE/data/sessions_slack.json"
fi
if [[ ! -f "$WORKSPACE/data/cron.json" ]]; then
  echo '[]' > "$WORKSPACE/data/cron.json"
fi
if [[ ! -f "$WORKSPACE/data/tasks.json" ]]; then
  echo '[]' > "$WORKSPACE/data/tasks.json"
fi
if [[ ! -f "$WORKSPACE/data/projects.json" ]]; then
  echo '[]' > "$WORKSPACE/data/projects.json"
fi

echo "$ENGINE_VERSION" > "$WORKSPACE/data/engine_version"

# Ensure heartbeat cron job exists
$PYTHON_BIN - <<PY
import json
from datetime import datetime
from pathlib import Path

cron_path = Path("$WORKSPACE") / "data" / "cron.json"
try:
    jobs = json.loads(cron_path.read_text())
except Exception:
    jobs = []

if not any(j.get("id") == "heartbeat" for j in jobs):
    jobs.append({
        "id": "heartbeat",
        "schedule": "*/30 * * * *",
        "prompt": "Heartbeat check. Zkontroluj overdue tasky a blížící se deadliny. Buď stručný.",
        "enabled": True,
        "created": datetime.now().isoformat(),
        "last_run": None,
    })
    cron_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2))
PY

# Symlink core_tools into workspace
CORE_LINK="$WORKSPACE/core_tools"
if [[ -L "$CORE_LINK" ]]; then
  ln -sfn "$ENGINE_DIR/core_tools" "$CORE_LINK"
elif [[ -e "$CORE_LINK" ]]; then
  echo "core_tools exists and is not a symlink: $CORE_LINK" >&2
else
  ln -s "$ENGINE_DIR/core_tools" "$CORE_LINK"
fi

echo "Workspace initialized at $WORKSPACE"
