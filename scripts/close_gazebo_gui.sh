#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/.run}"
PID_FILE="$RUN_DIR/gzclient.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No repo-managed Gazebo GUI pid file found."
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
rm -f "$PID_FILE"

if [ -z "${pid:-}" ]; then
  echo "Gazebo GUI pid file was empty."
  exit 0
fi

if ! kill -0 "$pid" 2>/dev/null; then
  echo "Gazebo GUI process $pid is not running."
  exit 0
fi

echo "Stopping Gazebo GUI (pid $pid)"
kill -TERM "$pid" 2>/dev/null || true
