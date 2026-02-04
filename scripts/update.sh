#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${1:-}
if [[ -z "$WORKSPACE" ]]; then
  echo "Usage: ./scripts/update.sh /path/to/workspace" >&2
  exit 1
fi

ENGINE_DIR=$(cd "$(dirname "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
WORKSPACE=$($PYTHON_BIN - <<PY
import os
print(os.path.abspath(os.path.expanduser("$WORKSPACE")))
PY
)

ENGINE_VERSION=$(cat "$ENGINE_DIR/VERSION")
WORKSPACE_VERSION_FILE="$WORKSPACE/data/engine_version"
WORKSPACE_VERSION=""
if [[ -f "$WORKSPACE_VERSION_FILE" ]]; then
  WORKSPACE_VERSION=$(cat "$WORKSPACE_VERSION_FILE")
fi

echo "Engine version: $ENGINE_VERSION"
if [[ -n "$WORKSPACE_VERSION" ]]; then
  echo "Workspace version: $WORKSPACE_VERSION"
fi

# Refresh core_tools symlink
CORE_LINK="$WORKSPACE/core_tools"
if [[ -L "$CORE_LINK" ]]; then
  ln -sfn "$ENGINE_DIR/core_tools" "$CORE_LINK"
elif [[ -e "$CORE_LINK" ]]; then
  echo "core_tools exists and is not a symlink: $CORE_LINK" >&2
else
  ln -s "$ENGINE_DIR/core_tools" "$CORE_LINK"
fi

# Offer new default skills as *.new
mkdir -p "$WORKSPACE/.claude/skills"
for skill in "$ENGINE_DIR/default_skills"/*.md; do
  name=$(basename "$skill")
  target="$WORKSPACE/.claude/skills/$name"
  if [[ ! -f "$target" ]]; then
    cp "$skill" "$target.new"
  fi
done

mkdir -p "$WORKSPACE/data"
echo "$ENGINE_VERSION" > "$WORKSPACE_VERSION_FILE"

echo "Update completed."
