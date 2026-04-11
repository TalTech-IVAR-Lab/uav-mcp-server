#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/.run}"
LOG_DIR="${LOG_DIR:-$RUN_DIR/logs}"
LOG_FILE="$LOG_DIR/gzclient.log"
PID_FILE="$RUN_DIR/gzclient.pid"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
PX4_GAZEBO_BUILD_DIR="${PX4_GAZEBO_BUILD_DIR:-$PX4_DIR/build/px4_sitl_default/build_gazebo-classic}"
PX4_GAZEBO_MODEL_DIR="${PX4_GAZEBO_MODEL_DIR:-$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic/models}"
QT_QPA_PLATFORM_VALUE="${QT_QPA_PLATFORM_VALUE:-xcb}"
GDK_BACKEND_VALUE="${GDK_BACKEND_VALUE:-x11}"
GAZEBO_MASTER_URI_VALUE="${GAZEBO_MASTER_URI_VALUE:-http://127.0.0.1:11345}"

if [ -n "${LIBGL_ALWAYS_SOFTWARE_VALUE:-}" ]; then
  resolved_libgl_software="$LIBGL_ALWAYS_SOFTWARE_VALUE"
else
  # Prefer hardware rendering even on Wayland — the XCB/X11 overrides below
  # handle the display protocol; forcing software rendering on integrated GPUs
  # makes gzclient unresponsive.
  resolved_libgl_software="0"
fi

mkdir -p "$LOG_DIR"

if ! command -v gzclient >/dev/null 2>&1; then
  echo "gzclient is not installed." >&2
  exit 1
fi

if [ ! -d "$PX4_GAZEBO_BUILD_DIR" ] || [ ! -d "$PX4_GAZEBO_MODEL_DIR" ]; then
  echo "PX4 Gazebo Classic assets were not found." >&2
  echo "Expected build dir: $PX4_GAZEBO_BUILD_DIR" >&2
  echo "Expected model dir: $PX4_GAZEBO_MODEL_DIR" >&2
  exit 1
fi

if [ -f "$PID_FILE" ]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${existing_pid:-}" ] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Gazebo GUI is already running with pid $existing_pid"
    echo "Log: $LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if [ -z "${DISPLAY:-}" ]; then
  echo "DISPLAY is not set. Start this from your desktop session, not a headless shell." >&2
  exit 1
fi

echo "Starting Gazebo GUI"
echo "QT_QPA_PLATFORM=$QT_QPA_PLATFORM_VALUE"
echo "GDK_BACKEND=$GDK_BACKEND_VALUE"
echo "LIBGL_ALWAYS_SOFTWARE=$resolved_libgl_software"
echo "GAZEBO_MASTER_URI=$GAZEBO_MASTER_URI_VALUE"
echo "Log: $LOG_FILE"

env \
  -u WAYLAND_DISPLAY \
  QT_QPA_PLATFORM="$QT_QPA_PLATFORM_VALUE" \
  GDK_BACKEND="$GDK_BACKEND_VALUE" \
  LIBGL_ALWAYS_SOFTWARE="$resolved_libgl_software" \
  GAZEBO_MASTER_URI="$GAZEBO_MASTER_URI_VALUE" \
  GAZEBO_PLUGIN_PATH="$PX4_GAZEBO_BUILD_DIR${GAZEBO_PLUGIN_PATH:+:$GAZEBO_PLUGIN_PATH}" \
  GAZEBO_MODEL_PATH="$PX4_GAZEBO_MODEL_DIR${GAZEBO_MODEL_PATH:+:$GAZEBO_MODEL_PATH}" \
  LD_LIBRARY_PATH="$PX4_GAZEBO_BUILD_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  setsid gzclient --verbose >"$LOG_FILE" 2>&1 < /dev/null &
gui_pid="$!"
echo "$gui_pid" >"$PID_FILE"

sleep 4

if ! kill -0 "$gui_pid" 2>/dev/null; then
  echo "Gazebo GUI exited early. Check $LOG_FILE" >&2
  echo ""
  echo "If you see an X11/Wayland error, try:"
  echo "  LIBGL_ALWAYS_SOFTWARE_VALUE=1 $0"
  exit 1
fi

echo "Gazebo GUI started with pid $gui_pid"
