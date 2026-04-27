#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
SIM_CLASSIC_ROOT="${SIM_CLASSIC_ROOT:-$REPO_ROOT/sim/gazebo-classic}"
SIM_CLASSIC_MODEL_DIR="${SIM_CLASSIC_MODEL_DIR:-$SIM_CLASSIC_ROOT/models}"
SIM_CLASSIC_WORLD_NAME="${SIM_CLASSIC_WORLD_NAME:-}"
SIM_CLASSIC_WORLD_PATH="${SIM_CLASSIC_WORLD_PATH:-}"

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

classic_spawn_pose_patch_applied() {
  local classic_run_file="$PX4_DIR/Tools/simulation/gazebo-classic/sitl_run.sh"

  [ -f "$classic_run_file" ] && grep -q 'PX4_GZ_MODEL_POSE_X' "$classic_run_file"
}

if [ -z "$SIM_CLASSIC_WORLD_NAME" ] && [ -z "$SIM_CLASSIC_WORLD_PATH" ]; then
  SIM_CLASSIC_WORLD_NAME="$(read_env_value SIM_CLASSIC_WORLD_NAME taltech_campus)"
fi

if [ -n "$SIM_CLASSIC_WORLD_NAME" ] && [ -z "$SIM_CLASSIC_WORLD_PATH" ]; then
  SIM_CLASSIC_WORLD_PATH="$SIM_CLASSIC_ROOT/worlds/${SIM_CLASSIC_WORLD_NAME}.world"
elif [ -z "$SIM_CLASSIC_WORLD_PATH" ]; then
  SIM_CLASSIC_WORLD_PATH="$SIM_CLASSIC_ROOT/worlds/taltech_campus.world"
fi

PX4_MODEL="$(sitl_resolve_px4_model "${PX4_MODEL:-}")"
SITL_RUNTIME="$(sitl_model_runtime "$PX4_MODEL")"
PX4_MAKE_TARGET="$(sitl_make_target "$PX4_MODEL")"
ROS_SETUP_SCRIPT="${ROS_SETUP_SCRIPT:-/opt/ros/humble/setup.bash}"

default_px4_home_lat="$(read_env_value GEOFENCE_CENTER_LAT 46.233326)"
default_px4_home_lon="$(read_env_value GEOFENCE_CENTER_LON 6.055164)"
export PX4_HOME_LAT="${PX4_HOME_LAT:-$(read_env_value PX4_HOME_LAT "$default_px4_home_lat")}"
export PX4_HOME_LON="${PX4_HOME_LON:-$(read_env_value PX4_HOME_LON "$default_px4_home_lon")}"

if [ -d "$SIM_CLASSIC_MODEL_DIR" ]; then
  export GAZEBO_MODEL_PATH="$SIM_CLASSIC_MODEL_DIR${GAZEBO_MODEL_PATH:+:$GAZEBO_MODEL_PATH}"
fi

if [ -d "$SIM_CLASSIC_ROOT" ]; then
  export GAZEBO_RESOURCE_PATH="$SIM_CLASSIC_ROOT${GAZEBO_RESOURCE_PATH:+:$GAZEBO_RESOURCE_PATH}"
fi

# Include the system-wide Gazebo media directory so that gzserver can find
# standard materials (gazebo.material, shaders, etc.).  Without this,
# RTShaderSystem fails and camera rendering may break.
GAZEBO_MEDIA_DIR="${GAZEBO_MEDIA_DIR:-/usr/share/gazebo-11}"
if [ -d "$GAZEBO_MEDIA_DIR" ]; then
  export GAZEBO_RESOURCE_PATH="${GAZEBO_MEDIA_DIR}${GAZEBO_RESOURCE_PATH:+:$GAZEBO_RESOURCE_PATH}"
  export OGRE_RESOURCE_PATH="${OGRE_RESOURCE_PATH:-/usr/lib/x86_64-linux-gnu/OGRE-1.9.0}"
fi

if [ "$SITL_RUNTIME" = "classic" ] && [ -f "$SIM_CLASSIC_WORLD_PATH" ] && [ -z "${PX4_SITL_WORLD:-}" ]; then
  export PX4_SITL_WORLD="$SIM_CLASSIC_WORLD_PATH"
fi

if [ "$SITL_RUNTIME" = "classic" ]; then
  export PX4_GZ_MODEL_POSE_X="${PX4_GZ_MODEL_POSE_X:-$(read_env_value SIM_CLASSIC_SPAWN_X_M 1.01)}"
  export PX4_GZ_MODEL_POSE_Y="${PX4_GZ_MODEL_POSE_Y:-$(read_env_value SIM_CLASSIC_SPAWN_Y_M 0.98)}"
  export PX4_GZ_MODEL_POSE_Z="${PX4_GZ_MODEL_POSE_Z:-$(read_env_value SIM_CLASSIC_SPAWN_Z_M 0.83)}"
  export PX4_GZ_MODEL_POSE_YAW="${PX4_GZ_MODEL_POSE_YAW:-$(read_env_value SIM_CLASSIC_SPAWN_YAW_RAD 0.6716839273)}"
fi

if [ "$SITL_RUNTIME" = "classic" ] && [ -f "$ROS_SETUP_SCRIPT" ]; then
  # Gazebo Classic camera plugins depend on the ROS environment being present.
  set +u
  # shellcheck disable=SC1090
  source "$ROS_SETUP_SCRIPT"
  set -u
  # setup_gazebo.bash only appends the PX4 build dir to GAZEBO_PLUGIN_PATH.
  # libgazebo_ros_camera.so lives in the ROS2 lib directory and Gazebo will
  # not find it unless we include it here, before make runs setup_gazebo.bash.
  # dirname of setup.bash is the ROS2 prefix (e.g. /opt/ros/humble), so lib
  # is a direct subdirectory of that prefix.
  ROS_LIB_DIR="$(dirname "$ROS_SETUP_SCRIPT")/lib"
  ROS_LIB_DIR="$(cd "$ROS_LIB_DIR" 2>/dev/null && pwd || echo "")"
  if [ -n "$ROS_LIB_DIR" ] && [ -d "$ROS_LIB_DIR" ]; then
    export GAZEBO_PLUGIN_PATH="${ROS_LIB_DIR}${GAZEBO_PLUGIN_PATH:+:$GAZEBO_PLUGIN_PATH}"
  fi
fi

if [ ! -d "$PX4_DIR" ]; then
  echo "PX4 directory not found: $PX4_DIR"
  echo "Set PX4_DIR or clone PX4-Autopilot next to this repository."
  exit 1
fi

if [ "$SITL_RUNTIME" = "classic" ] && ! classic_spawn_pose_patch_applied; then
  echo "The PX4 Gazebo Classic checkout is missing spawn-pose override support." >&2
  echo "Run scripts/prepare_px4_classic_fallback.sh against PX4_DIR=$PX4_DIR and rebuild PX4 SITL." >&2
  exit 1
fi

echo "Starting PX4 SITL from: $PX4_DIR"
echo "Runtime: $SITL_RUNTIME"
echo "Model: $PX4_MODEL"
echo "Make target: $PX4_MAKE_TARGET"
echo "Home: ${PX4_HOME_LAT}, ${PX4_HOME_LON}"
echo "World: ${PX4_SITL_WORLD:-default}"
if [ "$SITL_RUNTIME" = "classic" ]; then
  echo "Spawn pose: x=${PX4_GZ_MODEL_POSE_X} y=${PX4_GZ_MODEL_POSE_Y} z=${PX4_GZ_MODEL_POSE_Z} yaw=${PX4_GZ_MODEL_POSE_YAW}"
fi

cd "$PX4_DIR"
exec make px4_sitl "$PX4_MAKE_TARGET"
