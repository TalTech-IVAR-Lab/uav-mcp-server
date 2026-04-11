#!/usr/bin/env bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRANSPORT="${1:-stdio}"
BACKEND_MODE="${2:-${BACKEND_MODE:-live}}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
DEFAULT_PX4_CONNECTION_STRING="${DEFAULT_PX4_CONNECTION_STRING:-udpin://0.0.0.0:14540}"

if [ "$TRANSPORT" = "http" ]; then
  TRANSPORT="streamable-http"
fi

if [ -x "$REPO_ROOT/.venv312/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv312/bin/python}"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [ "$BACKEND_MODE" = "live" ]; then
  export PX4_CONNECTION_STRING="${PX4_CONNECTION_STRING:-$DEFAULT_PX4_CONNECTION_STRING}"
fi

echo "Starting UAV MCP server"
echo "Transport: $TRANSPORT"
echo "Backend: $BACKEND_MODE"
echo "Python: $PYTHON_BIN"
if [ "$BACKEND_MODE" = "live" ]; then
  echo "PX4 connection: $PX4_CONNECTION_STRING"
fi
if [ "$TRANSPORT" = "streamable-http" ]; then
  echo "Endpoint: http://$HOST:$PORT/mcp"
fi

cd "$REPO_ROOT"
exec "$PYTHON_BIN" -m uav_mcp_server \
  --transport "$TRANSPORT" \
  --backend "$BACKEND_MODE" \
  --host "$HOST" \
  --port "$PORT"
