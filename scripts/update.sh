#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/update.sh [/path/to/workspace]" >&2
  exit 1
fi

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

# Symlink default skills into workspace (overwrite copies with symlinks)
mkdir -p "$WORKSPACE/.claude/skills"
for skill in "$ENGINE_DIR/default_skills"/*.md; do
  name=$(basename "$skill")
  target="$WORKSPACE/.claude/skills/$name"
  ln -sfn "$skill" "$target"
done

mkdir -p "$WORKSPACE/data"
echo "$ENGINE_VERSION" > "$WORKSPACE_VERSION_FILE"

echo "Update completed."
