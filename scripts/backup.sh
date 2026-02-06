#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

WORKSPACE=$(resolve_workspace "${1:-}")

if [[ ! -d "$WORKSPACE" ]]; then
  echo "Workspace not found: $WORKSPACE" >&2
  echo "Usage: ./scripts/backup.sh [/path/to/workspace] [--push]" >&2
  exit 1
fi

if [[ ! -d "$WORKSPACE/.git" ]]; then
  echo "Workspace is not a git repo: $WORKSPACE" >&2
  echo "Initialize it with: git -C \"$WORKSPACE\" init" >&2
  exit 1
fi

push_flag=${2:-}
timestamp=$(date +"%Y-%m-%d %H:%M:%S")

git -C "$WORKSPACE" add -A

if git -C "$WORKSPACE" diff --cached --quiet; then
  echo "No changes to backup."
  exit 0
fi

git -C "$WORKSPACE" commit -m "backup: $timestamp"

if [[ "$push_flag" == "--push" ]]; then
  git -C "$WORKSPACE" push
  echo "Backup pushed."
else
  echo "Backup committed. Use --push to push to remote."
fi
