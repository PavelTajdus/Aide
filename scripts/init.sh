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
  sed -e "s|__WORKSPACE__|$WORKSPACE|g" -e "s|__ENGINE_DIR__|$ENGINE_DIR|g" \
    "$ENGINE_DIR/templates/env.template" > "$WORKSPACE/.env"
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
        "prompt": "Heartbeat check. Review overdue tasks and upcoming deadlines. Be concise.",
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
