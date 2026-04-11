#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="${RUN_DIR:-$REPO_ROOT/.run}"
PX4_DIR_RAW="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
if [ -d "$PX4_DIR_RAW" ]; then
  PX4_DIR="$(cd "$PX4_DIR_RAW" && pwd)"
else
  PX4_DIR="$PX4_DIR_RAW"
fi
SITL_PID_FILE="$RUN_DIR/sitl.pid"
SERVER_PID_FILE="$RUN_DIR/server.pid"
SITL_EXTRA_PIDS_FILE="$RUN_DIR/sitl-extra.pids"
FORCE_CLEAN=0

if [ "${1:-}" = "--force" ]; then
  FORCE_CLEAN=1
  shift
fi

if [ "$#" -ne 0 ]; then
  echo "Usage: $0 [--force]" >&2
  exit 2
fi

stop_process_group() {
  local label="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    return
  fi

  local pid
  pid="$(cat "$pid_file")"

  if [ -z "$pid" ]; then
    rm -f "$pid_file"
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    return
  fi

  echo "Stopping $label (pgid $pid)"
  kill -TERM "-$pid" 2>/dev/null || true

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      return
    fi
    sleep 0.5
  done

  echo "$label did not stop cleanly; sending SIGKILL"
  kill -KILL "-$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

stop_process_group "MCP server" "$SERVER_PID_FILE"
stop_process_group "PX4 SITL" "$SITL_PID_FILE"

stop_tracked_pids() {
  local label="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    return
  fi

  while IFS= read -r pid; do
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      continue
    fi

    echo "Stopping tracked $label pid $pid"
    kill -TERM "$pid" 2>/dev/null || true

    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "Tracked $label pid $pid did not stop cleanly; sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done <"$pid_file"

  rm -f "$pid_file"
}

stop_tracked_pids "SITL runtime" "$SITL_EXTRA_PIDS_FILE"

stop_port_processes() {
  local label="$1"
  local protocol="$2"
  shift 2

  declare -A seen_pids=()
  local port
  local pid

  for port in "$@"; do
    while IFS= read -r pid; do
      if [ -n "$pid" ]; then
        seen_pids["$pid"]=1
      fi
    done < <(
      if [ "$protocol" = "tcp" ]; then
        lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
      else
        lsof -t -nP -iUDP:"$port" 2>/dev/null || true
      fi
    )
  done

  if [ "${#seen_pids[@]}" -eq 0 ]; then
    return
  fi

  for pid in "${!seen_pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      continue
    fi

    if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
      continue
    fi

    echo "Stopping $label pid $pid owning ${protocol^^} ports $*"
    kill -TERM "$pid" 2>/dev/null || true

    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "$label pid $pid did not stop cleanly; sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

stop_matching_processes() {
  local label="$1"
  local pattern="$2"
  local pid

  while IFS= read -r pid; do
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      continue
    fi

    echo "Stopping $label pid $pid matching '$pattern'"
    kill -TERM "$pid" 2>/dev/null || true

    for _ in $(seq 1 20); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "$label pid $pid did not stop cleanly; sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

if [ "$FORCE_CLEAN" -eq 1 ]; then
  stop_port_processes "MCP server" tcp 8000
  stop_port_processes "PX4 SITL" udp 14540 14580 18570

  if [ -d "$PX4_DIR" ]; then
    stop_matching_processes "Gazebo Classic SITL" "$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic"
    stop_matching_processes "Gazebo Classic model spawner" "--spawn-file=$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic"
    stop_matching_processes "Gazebo Harmonic simulator" "$PX4_DIR/Tools/simulation/gz/"
  fi
fi
