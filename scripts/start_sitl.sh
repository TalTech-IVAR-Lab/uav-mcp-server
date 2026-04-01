#!/usr/bin/env zsh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
PX4_MODEL="${PX4_MODEL:-gz_x500}"

export PX4_HOME_LAT="${PX4_HOME_LAT:-59.3948}"
export PX4_HOME_LON="${PX4_HOME_LON:-24.6614}"

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
