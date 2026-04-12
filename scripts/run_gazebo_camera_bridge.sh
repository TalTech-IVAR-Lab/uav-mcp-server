#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_FILE="$REPO_ROOT/tools/gazebo_camera_bridge.cpp"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/.run}"
BIN_DIR="$RUN_DIR/bin"
BINARY_PATH="$BIN_DIR/gazebo_camera_bridge"

if [ $# -ne 2 ] || [ "${1:-}" != "--topic" ] || [ -z "${2:-}" ]; then
  echo "Usage: $0 --topic <gazebo-topic>" >&2
  exit 2
fi

TOPIC="$2"

mkdir -p "$BIN_DIR"

if [ ! -x "$BINARY_PATH" ] || [ "$SOURCE_FILE" -nt "$BINARY_PATH" ]; then
  g++ \
    "$SOURCE_FILE" \
    -O2 \
    -std=c++17 \
    $(pkg-config --cflags --libs gazebo opencv4 protobuf) \
    -o "$BINARY_PATH"
fi

exec "$BINARY_PATH" --topic "$TOPIC"
