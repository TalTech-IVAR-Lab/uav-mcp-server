#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

source "$SCRIPT_DIR/sitl_profile.sh"

# Pick up PX4_MODEL (and PX4_GZ_WORLD) from .env when not already in the env.
# Without this, the model defined in .env is silently ignored and the launcher
# falls back to whichever stack pkg-config detects first — losing camera/world
# selections the operator pinned in .env.
if [ -f "$ENV_FILE" ]; then
  for env_key in PX4_MODEL PX4_GZ_WORLD SIM_GZ_WORLD_NAME \
                 SIM_GZ_SPAWN_X_M SIM_GZ_SPAWN_Y_M SIM_GZ_SPAWN_Z_M SIM_GZ_SPAWN_YAW_RAD; do
    if [ -z "${!env_key:-}" ]; then
      env_line="$(grep -E "^${env_key}=" "$ENV_FILE" | tail -n 1 || true)"
      if [ -n "$env_line" ]; then
        export "$env_key=${env_line#*=}"
      fi
    fi
  done
fi

# Resolve runtime early so we can pick the correct GPS origin and world check.
RESOLVED_MODEL="$(sitl_resolve_px4_model "${PX4_MODEL:-}")"
RESOLVED_RUNTIME="$(sitl_model_runtime "$RESOLVED_MODEL")"

# Pin the resolved model so downstream scripts don't re-run auto-detection and
# diverge from what was resolved here.
export PX4_MODEL="$RESOLVED_MODEL"

if [ "$RESOLVED_RUNTIME" = "harmonic" ]; then
  # Harmonic world origin: spherical_coordinates in sim/gz/worlds/taltech_campus.world
  export GEOFENCE_CENTER_LAT="${GEOFENCE_CENTER_LAT:-59.395868}"
  export GEOFENCE_CENTER_LON="${GEOFENCE_CENTER_LON:-24.666542}"
  export SIM_GZ_WORLD_NAME="${SIM_GZ_WORLD_NAME:-taltech_campus}"

  if [ ! -f "$REPO_ROOT/sim/gz/worlds/${SIM_GZ_WORLD_NAME}.world" ]; then
    echo "TalTech Harmonic world not found: sim/gz/worlds/${SIM_GZ_WORLD_NAME}.world" >&2
    exit 1
  fi
else
  # Classic fallback: the generated taltech_campus world has a different GPS origin.
  export GEOFENCE_CENTER_LAT="${GEOFENCE_CENTER_LAT:-59.3949741}"
  export GEOFENCE_CENTER_LON="${GEOFENCE_CENTER_LON:-24.6676189}"
  export SIM_CLASSIC_WORLD_NAME="${SIM_CLASSIC_WORLD_NAME:-taltech_campus}"

  if [ ! -f "$REPO_ROOT/sim/gazebo-classic/worlds/${SIM_CLASSIC_WORLD_NAME}.world" ]; then
    echo "TalTech Classic world is missing. Generate it first with:" >&2
    echo "  scripts/import_gazebo_terrain.py --model-name ${SIM_CLASSIC_WORLD_NAME} --force" >&2
    exit 1
  fi
fi

export PX4_HOME_LAT="${PX4_HOME_LAT:-$GEOFENCE_CENTER_LAT}"
export PX4_HOME_LON="${PX4_HOME_LON:-$GEOFENCE_CENTER_LON}"

# Spawn pose for the Harmonic / gz launch. X=Y=0 maps to the world's
# spherical_coordinates GPS origin (the GeoJSON tile center).
#
# Z must put the drone clearly *above* the heightmap surface. Landing it onto
# a sloped patch of terrain causes DART/Bullet contact micro-jitter that EKF2
# mis-attributes as a steady gyro signal (Preflight Fail: High Gyro Bias,
# heading estimate not stable) — and the drone often arms "airborne" while
# physically wedged on the slope. Spawning a few metres up lets it freefall
# into a clean landed contact; EKF2 then converges in ~30 s.
#
# PX4 path quirk: the Classic SITL patch reads PX4_GZ_MODEL_POSE_X/_Y/_Z
# directly, but stock PX4 px4-rc.gzsim for Harmonic reads a comma-separated
# PX4_GZ_MODEL_POSE="x,y,z". We export both forms so either path picks it up.
SPAWN_X="${PX4_GZ_MODEL_POSE_X:-${SIM_GZ_SPAWN_X_M:-0.0}}"
SPAWN_Y="${PX4_GZ_MODEL_POSE_Y:-${SIM_GZ_SPAWN_Y_M:-0.0}}"
SPAWN_Z="${PX4_GZ_MODEL_POSE_Z:-${SIM_GZ_SPAWN_Z_M:-5.0}}"
SPAWN_YAW="${PX4_GZ_MODEL_POSE_YAW:-${SIM_GZ_SPAWN_YAW_RAD:-0.0}}"

export PX4_GZ_MODEL_POSE_X="$SPAWN_X"
export PX4_GZ_MODEL_POSE_Y="$SPAWN_Y"
export PX4_GZ_MODEL_POSE_Z="$SPAWN_Z"
export PX4_GZ_MODEL_POSE_YAW="$SPAWN_YAW"
export PX4_GZ_MODEL_POSE="${SPAWN_X},${SPAWN_Y},${SPAWN_Z}"
export HEADLESS="${HEADLESS-0}"

exec "$SCRIPT_DIR/launch_live_stack.sh"
