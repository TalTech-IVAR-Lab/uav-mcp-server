#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export SIM_CLASSIC_WORLD_NAME="${SIM_CLASSIC_WORLD_NAME:-taltech_campus}"
export PX4_MODEL="${PX4_MODEL:-gazebo-classic}"
export GEOFENCE_CENTER_LAT="${GEOFENCE_CENTER_LAT:-59.3949741}"
export GEOFENCE_CENTER_LON="${GEOFENCE_CENTER_LON:-24.6676189}"
export PX4_HOME_LAT="${PX4_HOME_LAT:-$GEOFENCE_CENTER_LAT}"
export PX4_HOME_LON="${PX4_HOME_LON:-$GEOFENCE_CENTER_LON}"
export PX4_GZ_MODEL_POSE_X="${PX4_GZ_MODEL_POSE_X:-0.0}"
export PX4_GZ_MODEL_POSE_Y="${PX4_GZ_MODEL_POSE_Y:-0.0}"
export PX4_GZ_MODEL_POSE_Z="${PX4_GZ_MODEL_POSE_Z:-1.0}"
export PX4_GZ_MODEL_POSE_YAW="${PX4_GZ_MODEL_POSE_YAW:-0.0}"
export HEADLESS="${HEADLESS-0}"

if [ ! -f "$REPO_ROOT/sim/gazebo-classic/worlds/${SIM_CLASSIC_WORLD_NAME}.world" ]; then
  echo "TalTech world is missing. Generate it first with:" >&2
  echo "  scripts/import_gazebo_terrain.py --model-name ${SIM_CLASSIC_WORLD_NAME} --force" >&2
  exit 1
fi

exec "$SCRIPT_DIR/launch_live_stack.sh"
