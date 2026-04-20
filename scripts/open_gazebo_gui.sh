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
CUSTOM_GAZEBO_ROOT="${CUSTOM_GAZEBO_ROOT:-$REPO_ROOT/sim/gazebo-classic}"
CUSTOM_GAZEBO_MODEL_DIR="${CUSTOM_GAZEBO_MODEL_DIR:-$CUSTOM_GAZEBO_ROOT/models}"
QT_QPA_PLATFORM_VALUE="${QT_QPA_PLATFORM_VALUE:-xcb}"
GDK_BACKEND_VALUE="${GDK_BACKEND_VALUE:-x11}"
GAZEBO_MASTER_URI_VALUE="${GAZEBO_MASTER_URI_VALUE:-http://127.0.0.1:11345}"
GAZEBO_SETUP_SH_VALUE="${GAZEBO_SETUP_SH_VALUE:-}"
DESKTOP_ENV_HELPER="$SCRIPT_DIR/resolve_desktop_session_env.py"

prepend_path_entry() {
  local entry="$1"
  local current_value="${2:-}"

  if [ -z "$entry" ]; then
    printf '%s\n' "$current_value"
    return
  fi

  if [ -n "$current_value" ]; then
    printf '%s:%s\n' "$entry" "$current_value"
    return
  fi

  printf '%s\n' "$entry"
}

find_gazebo_setup_script() {
  if [ -n "$GAZEBO_SETUP_SH_VALUE" ]; then
    if [ -f "$GAZEBO_SETUP_SH_VALUE" ]; then
      printf '%s\n' "$GAZEBO_SETUP_SH_VALUE"
      return 0
    fi

    echo "Configured Gazebo setup script was not found: $GAZEBO_SETUP_SH_VALUE" >&2
    return 1
  fi

  local candidate
  for candidate in /usr/share/gazebo/setup.sh /usr/share/gazebo-11/setup.sh; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 0
}

source_gazebo_setup() {
  local setup_script
  local had_nounset=0
  setup_script="$(find_gazebo_setup_script)"

  if [ -z "$setup_script" ]; then
    return 0
  fi

  case $- in
    *u*)
      had_nounset=1
      set +u
      ;;
  esac

  # shellcheck source=/dev/null
  . "$setup_script"

  if [ "$had_nounset" -eq 1 ]; then
    set -u
  fi
}

resolve_gazebo_gui_env() {
  source_gazebo_setup

  printf 'GAZEBO_PLUGIN_PATH=%s\n' "$(prepend_path_entry "$PX4_GAZEBO_BUILD_DIR" "${GAZEBO_PLUGIN_PATH:-}")"
  printf 'GAZEBO_MODEL_PATH=%s\n' "$(prepend_path_entry "$CUSTOM_GAZEBO_MODEL_DIR" "$(prepend_path_entry "$PX4_GAZEBO_MODEL_DIR" "${GAZEBO_MODEL_PATH:-}")")"
  printf 'GAZEBO_RESOURCE_PATH=%s\n' "$(prepend_path_entry "$CUSTOM_GAZEBO_ROOT" "${GAZEBO_RESOURCE_PATH:-}")"
  printf 'LD_LIBRARY_PATH=%s\n' "$(prepend_path_entry "$PX4_GAZEBO_BUILD_DIR" "${LD_LIBRARY_PATH:-}")"
}

resolve_desktop_gui_session() {
  if [ -n "${DISPLAY:-}" ] || [ ! -f "$DESKTOP_ENV_HELPER" ]; then
    return
  fi

  local python_bin="python3"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    return
  fi

  local discovered
  if ! discovered="$("$python_bin" "$DESKTOP_ENV_HELPER" 2>/dev/null)"; then
    return
  fi

  while IFS='=' read -r key value; do
    [ -n "${key:-}" ] || continue
    export "$key=$value"
  done <<<"$discovered"
}

if [ -n "${LIBGL_ALWAYS_SOFTWARE_VALUE:-}" ]; then
  resolved_libgl_software="$LIBGL_ALWAYS_SOFTWARE_VALUE"
else
  # Prefer hardware rendering even on Wayland — the XCB/X11 overrides below
  # handle the display protocol; forcing software rendering on integrated GPUs
  # makes gzclient unresponsive.
  resolved_libgl_software="0"
fi

main() {
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

  resolve_desktop_gui_session

  if [ -z "${DISPLAY:-}" ]; then
    echo "DISPLAY is not set. Start this from your desktop session, not a headless shell." >&2
    exit 1
  fi

  source_gazebo_setup

  resolved_gazebo_plugin_path="$(prepend_path_entry "$PX4_GAZEBO_BUILD_DIR" "${GAZEBO_PLUGIN_PATH:-}")"
  resolved_gazebo_model_path="$(prepend_path_entry "$CUSTOM_GAZEBO_MODEL_DIR" "$(prepend_path_entry "$PX4_GAZEBO_MODEL_DIR" "${GAZEBO_MODEL_PATH:-}")")"
  resolved_gazebo_resource_path="$(prepend_path_entry "$CUSTOM_GAZEBO_ROOT" "${GAZEBO_RESOURCE_PATH:-}")"
  resolved_ld_library_path="$(prepend_path_entry "$PX4_GAZEBO_BUILD_DIR" "${LD_LIBRARY_PATH:-}")"

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
    GAZEBO_PLUGIN_PATH="$resolved_gazebo_plugin_path" \
    GAZEBO_MODEL_PATH="$resolved_gazebo_model_path" \
    GAZEBO_RESOURCE_PATH="$resolved_gazebo_resource_path" \
    LD_LIBRARY_PATH="$resolved_ld_library_path" \
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
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
