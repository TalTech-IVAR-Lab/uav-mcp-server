#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PX4_DIR="${PX4_DIR:-$REPO_ROOT/../PX4-Autopilot}"
PX4_CMAKE_FILE="$PX4_DIR/src/modules/simulation/simulator_mavlink/sitl_targets_gazebo-classic.cmake"
GAZEBO_SUBMODULE_CMAKE_FILE="$PX4_DIR/Tools/simulation/gazebo-classic/sitl_gazebo-classic/CMakeLists.txt"
GAZEBO_CLASSIC_RUN_FILE="$PX4_DIR/Tools/simulation/gazebo-classic/sitl_run.sh"

if [ ! -f "$PX4_CMAKE_FILE" ]; then
  echo "PX4 file not found: $PX4_CMAKE_FILE" >&2
  exit 1
fi

if [ ! -f "$GAZEBO_SUBMODULE_CMAKE_FILE" ]; then
  echo "Gazebo Classic submodule file not found: $GAZEBO_SUBMODULE_CMAKE_FILE" >&2
  echo "Did you clone PX4 with --recursive?" >&2
  exit 1
fi

if [ ! -f "$GAZEBO_CLASSIC_RUN_FILE" ]; then
  echo "Gazebo Classic launcher file not found: $GAZEBO_CLASSIC_RUN_FILE" >&2
  exit 1
fi

python3 - "$PX4_CMAKE_FILE" "$GAZEBO_SUBMODULE_CMAKE_FILE" "$GAZEBO_CLASSIC_RUN_FILE" <<'PY'
from pathlib import Path
import sys


def patch_px4_cmake(path: Path) -> bool:
    old = """\t\tCMAKE_ARGS\n\t\t\t-DCMAKE_INSTALL_PREFIX=${CMAKE_INSTALL_PREFIX}\n\t\t\t-DSEND_ODOMETRY_DATA=ON\n"""
    new = """\t\tCMAKE_ARGS\n\t\t\t-DCMAKE_INSTALL_PREFIX=${CMAKE_INSTALL_PREFIX}\n\t\t\t-DBUILD_GSTREAMER_PLUGIN=OFF\n\t\t\t-DSEND_ODOMETRY_DATA=ON\n"""
    text = path.read_text()
    if "-DBUILD_GSTREAMER_PLUGIN=OFF" in text:
        return False
    if old not in text:
        raise RuntimeError(f"Could not find expected block in {path}")
    path.write_text(text.replace(old, new))
    return True


def patch_gazebo_cmake(path: Path) -> bool:
    old = """QT5_WRAP_CPP(headers_MOC2 include/gazebo_user_camera_plugin.h)\nadd_library(gazebo_user_camera_plugin SHARED ${headers_MOC2} src/gazebo_user_camera_plugin.cpp)\ntarget_link_libraries(gazebo_user_camera_plugin ${GAZEBO_LIBRARIES} ${Qt5Core_LIBRARIES} ${Qt5Widgets_LIBRARIES} ${Qt5Test_LIBRARIES})\nset(plugins\n  ${plugins}\n  gazebo_user_camera_plugin\n)\n"""
    new = """if (BUILD_GSTREAMER_PLUGIN)\n  QT5_WRAP_CPP(headers_MOC2 include/gazebo_user_camera_plugin.h)\n  add_library(gazebo_user_camera_plugin SHARED ${headers_MOC2} src/gazebo_user_camera_plugin.cpp)\n  target_link_libraries(gazebo_user_camera_plugin ${GAZEBO_LIBRARIES} ${Qt5Core_LIBRARIES} ${Qt5Widgets_LIBRARIES} ${Qt5Test_LIBRARIES})\n  set(plugins\n    ${plugins}\n    gazebo_user_camera_plugin\n  )\nendif()\n"""
    text = path.read_text()
    if "if (BUILD_GSTREAMER_PLUGIN)" in text:
        return False
    if old not in text:
        raise RuntimeError(f"Could not find expected block in {path}")
    path.write_text(text.replace(old, new))
    return True


def patch_classic_spawn_pose(path: Path) -> bool:
    old = """\twhile gz model --verbose --spawn-file="${modelpath}/${model}/${model_name}.sdf" --model-name=${model} -x 1.01 -y 0.98 -z 0.83 2>&1 | grep -q "An instance of Gazebo is not running."; do\n"""
    new = """\tspawn_x="${PX4_GZ_MODEL_POSE_X:-1.01}"\n\tspawn_y="${PX4_GZ_MODEL_POSE_Y:-0.98}"\n\tspawn_z="${PX4_GZ_MODEL_POSE_Z:-0.83}"\n\tspawn_yaw="${PX4_GZ_MODEL_POSE_YAW:-0.0}"\n\n\twhile gz model --verbose --spawn-file="${modelpath}/${model}/${model_name}.sdf" --model-name=${model} -x "${spawn_x}" -y "${spawn_y}" -z "${spawn_z}" -Y "${spawn_yaw}" 2>&1 | grep -q "An instance of Gazebo is not running."; do\n"""
    text = path.read_text()
    if 'spawn_x="${PX4_GZ_MODEL_POSE_X:-1.01}"' in text:
        return False
    if old not in text:
        raise RuntimeError(f"Could not find expected spawn line in {path}")
    path.write_text(text.replace(old, new))
    return True


px4_path = Path(sys.argv[1])
gazebo_path = Path(sys.argv[2])
run_path = Path(sys.argv[3])
px4_changed = patch_px4_cmake(px4_path)
gazebo_changed = patch_gazebo_cmake(gazebo_path)
run_changed = patch_classic_spawn_pose(run_path)

print(f"PX4 cmake patched: {px4_changed}")
print(f"Gazebo Classic submodule patched: {gazebo_changed}")
print(f"Gazebo Classic spawn pose patched: {run_changed}")
PY

echo "Gazebo Classic fallback patch is ready in: $PX4_DIR"
