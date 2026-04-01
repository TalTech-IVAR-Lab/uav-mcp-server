#!/usr/bin/env zsh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRANSPORT="${1:-stdio}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ "$TRANSPORT" = "http" ]; then
  TRANSPORT="streamable-http"
fi

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting UAV MCP server"
echo "Transport: $TRANSPORT"
echo "Python: $PYTHON_BIN"
if [ "$TRANSPORT" = "streamable-http" ]; then
  echo "Endpoint: http://$HOST:$PORT/mcp"
fi

cd "$REPO_ROOT"
exec "$PYTHON_BIN" -m uav_mcp_server --transport "$TRANSPORT" --host "$HOST" --port "$PORT"
