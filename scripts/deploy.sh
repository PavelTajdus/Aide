#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/common.sh"

WORKSPACE=$(resolve_workspace "${1:-}")

echo "=== Aide deploy ==="
echo "Engine:    $ENGINE_DIR"
echo "Workspace: $WORKSPACE"

# 1. Pull latest engine code
echo ""
echo "--- git pull ---"
git -C "$ENGINE_DIR" pull

# 2. Install/upgrade Python dependencies
echo ""
echo "--- pip install ---"
if [[ -d "$ENGINE_DIR/../venv" ]]; then
  "$ENGINE_DIR/../venv/bin/pip" install -r "$ENGINE_DIR/requirements.txt"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  pip install -r "$ENGINE_DIR/requirements.txt"
else
  $PYTHON_BIN -m pip install -r "$ENGINE_DIR/requirements.txt"
fi

# 3. Update workspace (symlinks, skills, version)
echo ""
echo "--- update workspace ---"
"$ENGINE_DIR/scripts/update.sh" "$WORKSPACE"

# 4. Claude Code update + restart services
echo ""
echo "--- restart ---"
"$ENGINE_DIR/scripts/restart.sh" "$WORKSPACE"

echo ""
echo "=== Deploy complete ==="
