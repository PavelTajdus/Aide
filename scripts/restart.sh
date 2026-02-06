#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${1:-}
ENGINE_DIR=$(cd "$(dirname "$0")/.." && pwd)

# Update Claude Code if available
if command -v claude &>/dev/null; then
  echo "Updating Claude Code..."
  claude update 2>&1 || echo "Claude Code update skipped (already latest or offline)"
fi

"$ENGINE_DIR/scripts/stop.sh" "$WORKSPACE"
"$ENGINE_DIR/scripts/run.sh" "$WORKSPACE"
