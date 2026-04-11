#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"

source "$SCRIPT_DIR/sitl_profile.sh"

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
PX4_MODEL="$(sitl_resolve_px4_model "${PX4_MODEL:-}")"
SITL_RUNTIME="$(sitl_model_runtime "$PX4_MODEL")"

export PX4_HOME_LAT="${PX4_HOME_LAT:-$(read_env_value GEOFENCE_CENTER_LAT 59.3948)}"
export PX4_HOME_LON="${PX4_HOME_LON:-$(read_env_value GEOFENCE_CENTER_LON 24.6614)}"

if [ ! -d "$PX4_DIR" ]; then
  echo "PX4 directory not found: $PX4_DIR"
  echo "Set PX4_DIR or clone PX4-Autopilot next to this repository."
  exit 1
fi

echo "Starting PX4 SITL from: $PX4_DIR"
echo "Runtime: $SITL_RUNTIME"
echo "Model: $PX4_MODEL"
echo "Home: ${PX4_HOME_LAT}, ${PX4_HOME_LON}"

cd "$PX4_DIR"
exec make px4_sitl "$PX4_MODEL"
