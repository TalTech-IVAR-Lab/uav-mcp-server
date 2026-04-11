#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TRANSPORT="${TRANSPORT:-streamable-http}"
BACKEND_MODE="${BACKEND_MODE:-local}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [ "$TRANSPORT" = "http" ]; then
  TRANSPORT="streamable-http"
fi

if [ "$BACKEND_MODE" != "live" ] && [ "$BACKEND_MODE" != "local" ]; then
  echo "Unsupported BACKEND_MODE '$BACKEND_MODE'. Use 'live' or 'local'." >&2
  exit 1
fi

if [ "$BACKEND_MODE" = "live" ]; then
  export PX4_CONNECTION_STRING="${PX4_CONNECTION_STRING:-udpin://0.0.0.0:14540}"
fi

cd "$REPO_ROOT"
exec "$PYTHON_BIN" -m uav_mcp_server \
  --transport "$TRANSPORT" \
  --backend "$BACKEND_MODE" \
  --host "$HOST" \
  --port "$PORT"
