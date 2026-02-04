#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${1:-}
ENGINE_DIR=$(cd "$(dirname "$0")/.." && pwd)

"$ENGINE_DIR/scripts/stop.sh" "$WORKSPACE"
"$ENGINE_DIR/scripts/run.sh" "$WORKSPACE"
