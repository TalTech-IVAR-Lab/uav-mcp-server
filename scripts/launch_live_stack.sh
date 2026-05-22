#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SIM_CLASSIC_WORLD_DIR="${SIM_CLASSIC_WORLD_DIR:-$REPO_ROOT/sim/gazebo-classic/worlds}"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/.run}"
LOG_DIR="${LOG_DIR:-$RUN_DIR/logs}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
HEADLESS_RAW="${HEADLESS-1}"
BACKEND_MODE="live"
SMOKE_MODE="${SMOKE_MODE:-connect}"
STARTUP_TIMEOUT_S="${STARTUP_TIMEOUT_S:-90}"
PX4_PREFLIGHT_AUTO_DISARM_S="${PX4_PREFLIGHT_AUTO_DISARM_S:-60}"
STRICT_SITL_CONFIGURE="${STRICT_SITL_CONFIGURE:-0}"
PX4_CONNECTION_STRING="${PX4_CONNECTION_STRING:-udpin://0.0.0.0:14540}"
SITL_SYSTEM_ADDRESS="${SITL_SYSTEM_ADDRESS:-udpin://0.0.0.0:14540}"
SITL_PID_FILE="$RUN_DIR/sitl.pid"
SITL_EXTRA_PIDS_FILE="$RUN_DIR/sitl-extra.pids"
SERVER_PID_FILE="$RUN_DIR/server.pid"
SITL_LOG="$LOG_DIR/sitl.log"
SERVER_LOG="$LOG_DIR/server.log"
DESKTOP_ENV_HELPER="$SCRIPT_DIR/resolve_desktop_session_env.py"
PX4_DIR_RAW="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
if [ -d "$PX4_DIR_RAW" ]; then
  PX4_DIR="$(cd "$PX4_DIR_RAW" && pwd)"
else
  PX4_DIR="$PX4_DIR_RAW"
fi

case "${HEADLESS_RAW,,}" in
  ""|0|false|no)
    HEADLESS=""
    ;;
  *)
    HEADLESS="1"
    ;;
esac

source "$SCRIPT_DIR/sitl_profile.sh"
EXPECTED_PX4_MODEL="$(sitl_resolve_px4_model "${PX4_MODEL:-}")"
SITL_RUNTIME="$(sitl_model_runtime "$EXPECTED_PX4_MODEL")"

mkdir -p "$LOG_DIR"

if [ -x "$REPO_ROOT/.venv312/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv312/bin/python}"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

sitl_pid=""
server_pid=""

stop_process_group_by_pid() {
  local pid="$1"
  local label="$2"

  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    return
  fi

  echo "Stopping $label (pgid $pid)"
  kill -TERM "-$pid" 2>/dev/null || true

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return
    fi
    sleep 0.5
  done

  echo "$label did not stop cleanly; sending SIGKILL"
  kill -KILL "-$pid" 2>/dev/null || true
}

cleanup_on_failure() {
  local exit_code="$?"

  if [ "$exit_code" -ne 0 ]; then
    echo "Launch failed; stopping the partial stack."
    stop_process_group_by_pid "${server_pid:-}" "MCP server"
    stop_process_group_by_pid "${sitl_pid:-}" "PX4 SITL"
    "$SCRIPT_DIR/stop_live_stack.sh" --force || true
    echo "SITL log: $SITL_LOG"
    echo "Server log: $SERVER_LOG"
  fi

  exit "$exit_code"
}

wait_for_process() {
  local pid="$1"
  local label="$2"

  if kill -0 "$pid" 2>/dev/null; then
    return
  fi

  echo "$label exited early." >&2
  exit 1
}

has_px4_runtime() {
  if [ -d "$PX4_DIR" ] && pgrep -f "$PX4_DIR/build/px4_sitl_default/bin/px4" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

wait_for_udp_port() {
  local port="$1"
  local pid="$2"
  local timeout_s="$3"
  local label="$4"

  for _ in $(seq 1 "$timeout_s"); do
    if ss -lun | grep -q ":${port} "; then
      return
    fi
    if kill -0 "$pid" 2>/dev/null || has_px4_runtime; then
      sleep 1
      continue
    fi
    echo "$label exited early." >&2
    exit 1
  done

  if ss -lun | grep -q ":${port} "; then
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null && ! has_px4_runtime; then
    echo "$label exited before opening UDP port ${port}." >&2
    exit 1
  fi

  echo "Timed out waiting for UDP port ${port} from $label." >&2
  exit 1
}

wait_for_tcp_port() {
  local port="$1"
  local pid="$2"
  local timeout_s="$3"
  local label="$4"

  for _ in $(seq 1 "$timeout_s"); do
    if ss -ltn | grep -q ":${port} "; then
      return
    fi
    if kill -0 "$pid" 2>/dev/null; then
      sleep 1
      continue
    fi
    echo "$label exited early." >&2
    exit 1
  done

  if ss -ltn | grep -q ":${port} "; then
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$label exited before opening TCP port ${port}." >&2
    exit 1
  fi

  echo "Timed out waiting for TCP port ${port} from $label." >&2
  exit 1
}

ensure_port_free() {
  local proto="$1"
  local port="$2"
  local label="$3"

  if [ "$proto" = "tcp" ] && ss -ltn | grep -q ":${port} "; then
    echo "$label port ${port} is already in use." >&2
    exit 1
  fi

  if [ "$proto" = "udp" ] && ss -lun | grep -q ":${port} "; then
    echo "$label port ${port} is already in use." >&2
    exit 1
  fi
}

purge_stale_artifacts() {
  if [ "${SKIP_CLEAN:-0}" = "1" ]; then
    return
  fi

  local freed_kb=0
  local size_kb

  local px4_log_dir="$PX4_DIR/build/px4_sitl_default/rootfs/log"
  if [ -d "$px4_log_dir" ]; then
    size_kb="$(du -sk "$px4_log_dir" 2>/dev/null | awk '{print $1}')"
    rm -rf "$px4_log_dir"/* 2>/dev/null || true
    freed_kb=$((freed_kb + ${size_kb:-0}))
  fi

  if [ -d "$LOG_DIR" ]; then
    size_kb="$(du -sk "$LOG_DIR" 2>/dev/null | awk '{print $1}')"
    find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -delete 2>/dev/null || true
    freed_kb=$((freed_kb + ${size_kb:-0}))
  fi

  if [ "$freed_kb" -gt 0 ]; then
    printf 'Purged stale logs (%.1f MiB freed). Set SKIP_CLEAN=1 to skip.\n' \
      "$(awk -v k="$freed_kb" 'BEGIN{printf "%.1f", k/1024}')"
  fi
}

ensure_no_orphaned_simulator_processes() {
  if [ ! -d "$PX4_DIR" ]; then
    return
  fi

  if [ "$SITL_RUNTIME" = "classic" ] \
    && pgrep -f "$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic" >/dev/null 2>&1; then
    echo "A repo-scoped Gazebo Classic simulator process is still running." >&2
    echo "Run 'scripts/stop_live_stack.sh --force' before relaunching." >&2
    exit 1
  fi

  if [ "$SITL_RUNTIME" = "classic" ] \
    && pgrep -f "$SIM_CLASSIC_WORLD_DIR/" >/dev/null 2>&1; then
    echo "A repo-local Gazebo Classic world process is still running." >&2
    echo "Run 'scripts/stop_live_stack.sh --force' before relaunching." >&2
    exit 1
  fi

  if [ "$SITL_RUNTIME" = "harmonic" ] \
    && pgrep -f "$PX4_DIR/Tools/simulation/gz/" >/dev/null 2>&1; then
    echo "A repo-scoped Gazebo Harmonic simulator process is still running." >&2
    echo "Run 'scripts/stop_live_stack.sh --force' before relaunching." >&2
    exit 1
  fi
}

record_sitl_runtime_pids() {
  : >"$SITL_EXTRA_PIDS_FILE"

  if [ ! -d "$PX4_DIR" ]; then
    return
  fi

  {
    pgrep -f "$PX4_DIR/build/px4_sitl_default/bin/px4" || true
    if [ "$SITL_RUNTIME" = "classic" ]; then
      pgrep -f "$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic" || true
      pgrep -f "$SIM_CLASSIC_WORLD_DIR/" || true
    fi
    if [ "$SITL_RUNTIME" = "harmonic" ]; then
      pgrep -f "$PX4_DIR/Tools/simulation/gz/" || true
    fi
  } | awk 'NF && !seen[$0]++' >"$SITL_EXTRA_PIDS_FILE"
}

resolve_desktop_gui_env() {
  if [ -n "$HEADLESS" ] || [ -n "${DISPLAY:-}" ] || [ ! -f "$DESKTOP_ENV_HELPER" ]; then
    return
  fi

  local discovered
  if ! discovered="$("$PYTHON_BIN" "$DESKTOP_ENV_HELPER" 2>/dev/null)"; then
    echo "No desktop display detected for GUI mode; continuing without GUI session env." >&2
    return
  fi

  while IFS='=' read -r key value; do
    [ -n "${key:-}" ] || continue
    export "$key=$value"
  done <<<"$discovered"

  : "${QT_QPA_PLATFORM:=xcb}"
  : "${GDK_BACKEND:=x11}"
  export QT_QPA_PLATFORM GDK_BACKEND

  echo "Using desktop session DISPLAY=${DISPLAY} for Gazebo GUI."
}

trap cleanup_on_failure EXIT

"$SCRIPT_DIR/stop_live_stack.sh" || true
purge_stale_artifacts
ensure_port_free udp 14580 "PX4 SITL"
ensure_port_free tcp "$PORT" "MCP server"
ensure_no_orphaned_simulator_processes
resolve_desktop_gui_env

echo "Starting PX4 SITL"
setsid bash -lc \
  "cd '$REPO_ROOT' && export HEADLESS='$HEADLESS' PX4_MODEL='$EXPECTED_PX4_MODEL' && scripts/start_sitl.sh" \
  >"$SITL_LOG" 2>&1 &
sitl_pid="$!"
echo "$sitl_pid" >"$SITL_PID_FILE"
wait_for_udp_port 14580 "$sitl_pid" "$STARTUP_TIMEOUT_S" "PX4 SITL"
record_sitl_runtime_pids

echo "Configuring PX4 SITL parameters"
if ! "$PYTHON_BIN" "$SCRIPT_DIR/configure_sitl_params.py" \
  --system-address "${SITL_SYSTEM_ADDRESS}" \
  --preflight-auto-disarm-s "$PX4_PREFLIGHT_AUTO_DISARM_S" \
  --timeout-s "$STARTUP_TIMEOUT_S"; then
  if [ "$STRICT_SITL_CONFIGURE" = "1" ]; then
    echo "Failed to configure PX4 SITL parameters and STRICT_SITL_CONFIGURE=1." >&2
    exit 1
  fi

  echo "Warning: failed to configure PX4 SITL parameters; continuing without COM_DISARM_PRFLT override." >&2
fi

echo "Starting MCP server"
setsid bash -lc \
  "cd '$REPO_ROOT' && export HOST='$HOST' PORT='$PORT' BACKEND_MODE='live' PX4_CONNECTION_STRING='$PX4_CONNECTION_STRING' PX4_MODEL='$EXPECTED_PX4_MODEL' && scripts/run_demo.sh http live" \
  >"$SERVER_LOG" 2>&1 &
server_pid="$!"
echo "$server_pid" >"$SERVER_PID_FILE"
wait_for_tcp_port "$PORT" "$server_pid" "$STARTUP_TIMEOUT_S" "MCP server"

echo "Running smoke check: $SMOKE_MODE"
"$PYTHON_BIN" "$SCRIPT_DIR/smoke_http.py" \
  --url "http://$HOST:$PORT/mcp" \
  --mode "$SMOKE_MODE" \
  --timeout "$STARTUP_TIMEOUT_S"

trap - EXIT

echo "Live stack is running."
echo "HTTP endpoint: http://$HOST:$PORT/mcp"
echo "SITL log: $SITL_LOG"
echo "Server log: $SERVER_LOG"
