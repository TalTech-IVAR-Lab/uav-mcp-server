#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"

if [ -d "$REPO_ROOT/.venv312/bin" ]; then
  export PATH="$REPO_ROOT/.venv312/bin:$PATH"
elif [ -d "$REPO_ROOT/.venv/bin" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

read_env_value() {
  local key="$1"
  local default_value="$2"

  if [ -f "$ENV_FILE" ]; then
    local line
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
    if [ -n "$line" ]; then
      printf '%s\n' "${line#*=}"
      return
    fi
  fi

  printf '%s\n' "$default_value"
}

has_gz_harmonic_stack() {
  local packages

  packages="$(pkg-config --list-all 2>/dev/null || true)"
  grep -Eq '^gz-sim' <<<"$packages" \
    && grep -Eq '^gz-transport' <<<"$packages" \
    && grep -Eq '^gz-plugin' <<<"$packages" \
    && grep -Eq '^gz-sensors' <<<"$packages"
}

has_gazebo_classic_stack() {
  pkg-config --exists gazebo 2>/dev/null
}

resolve_px4_model() {
  if [ -n "${PX4_MODEL:-}" ]; then
    printf '%s\n' "$PX4_MODEL"
    return
  fi

  if has_gz_harmonic_stack; then
    printf '%s\n' "gz_x500"
    return
  fi

  if has_gazebo_classic_stack; then
    printf '%s\n' "gazebo-classic"
    return
  fi

  echo "No supported PX4 simulator stack detected." >&2
  echo "Install Gazebo Harmonic for gz_x500 or Gazebo Classic for the fallback path." >&2
  exit 1
}

PX4_MODEL="$(resolve_px4_model)"

if [[ "$PX4_MODEL" == gz_* ]] && ! has_gz_harmonic_stack; then
  echo "PX4 model '$PX4_MODEL' requires the Gazebo Harmonic development packages." >&2
  exit 1
fi

if [ "$PX4_MODEL" = "gazebo-classic" ] && ! has_gazebo_classic_stack; then
  echo "PX4 model 'gazebo-classic' requires Gazebo Classic to be installed." >&2
  exit 1
fi

export PX4_HOME_LAT="${PX4_HOME_LAT:-$(read_env_value GEOFENCE_CENTER_LAT 59.3948)}"
export PX4_HOME_LON="${PX4_HOME_LON:-$(read_env_value GEOFENCE_CENTER_LON 24.6614)}"

if [ ! -d "$PX4_DIR" ]; then
  echo "PX4 directory not found: $PX4_DIR"
  echo "Set PX4_DIR or clone PX4-Autopilot next to this repository."
  exit 1
fi

echo "Starting PX4 SITL from: $PX4_DIR"
echo "Model: $PX4_MODEL"
echo "Home: ${PX4_HOME_LAT}, ${PX4_HOME_LON}"

cd "$PX4_DIR"
exec make px4_sitl "$PX4_MODEL"
