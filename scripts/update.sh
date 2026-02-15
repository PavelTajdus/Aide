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

# Ensure modular context structure exists (migration for older workspaces)
mkdir -p "$WORKSPACE/.claude/rules/auto"
ln -sfn "$ENGINE_DIR/templates/context/tools.md" "$WORKSPACE/.claude/rules/tools.md"

# Copy-once: user-owned context files (never overwrite existing)
if [[ ! -f "$WORKSPACE/.claude/rules/soul.md" ]]; then
  cp "$ENGINE_DIR/templates/context/soul.md" "$WORKSPACE/.claude/rules/soul.md"
fi
if [[ ! -f "$WORKSPACE/.claude/rules/user.md" ]]; then
  cp "$ENGINE_DIR/templates/context/user.md" "$WORKSPACE/.claude/rules/user.md"
fi
if [[ ! -f "$WORKSPACE/.claude/rules/channel.md" ]]; then
  cp "$ENGINE_DIR/templates/context/channel.example.md" "$WORKSPACE/.claude/rules/channel.md"
fi

# Symlink default skills into workspace (overwrite copies with symlinks)
mkdir -p "$WORKSPACE/.claude/skills"
for skill in "$ENGINE_DIR/default_skills"/*.md; do
  name=$(basename "$skill")
  target="$WORKSPACE/.claude/skills/$name"
  ln -sfn "$skill" "$target"
done

# Remove broken skill symlinks (deleted from engine)
for link in "$WORKSPACE/.claude/skills"/*.md; do
  [[ -L "$link" ]] && [[ ! -e "$link" ]] && rm "$link"
done

mkdir -p "$WORKSPACE/data"
echo "$ENGINE_VERSION" > "$WORKSPACE_VERSION_FILE"

update_cli_if_installed() {
  local title="$1"
  local binary_name="$2"
  local fallback_path="$3"
  local update_args="$4"
  local bin_path=""

  if command -v "$binary_name" &>/dev/null; then
    bin_path="$binary_name"
  elif [[ -x "$fallback_path" ]]; then
    bin_path="$fallback_path"
  else
    return 0
  fi

  echo ""
  echo "--- $title update ---"
  # shellcheck disable=SC2086
  "$bin_path" $update_args 2>&1 || echo "$title update skipped (failed or already up to date)"
}

update_cli_if_installed "Claude Code" "claude" "$HOME/.local/bin/claude" "update"
update_cli_if_installed "Codex" "codex" "$HOME/.local/bin/codex" "update"

echo "Update completed."
