#!/usr/bin/env bash

set -euo pipefail

sitl_supported_models() {
  printf '%s\n' "gz_x500 gazebo-classic gazebo-classic_typhoon_h480 gazebo-classic_iris_fpv_cam"
}

sitl_has_gz_harmonic_stack() {
  local packages

  packages="$(pkg-config --list-all 2>/dev/null || true)"
  grep -Eq '^gz-sim' <<<"$packages" \
    && grep -Eq '^gz-transport' <<<"$packages" \
    && grep -Eq '^gz-plugin' <<<"$packages" \
    && grep -Eq '^gz-sensors' <<<"$packages"
}

sitl_has_gazebo_classic_stack() {
  pkg-config --exists gazebo 2>/dev/null
}

sitl_model_runtime() {
  local model="$1"

  case "$model" in
    gz_x500)
      printf '%s\n' "harmonic"
      ;;
    gazebo-classic|gazebo-classic_typhoon_h480|gazebo-classic_iris_fpv_cam)
      printf '%s\n' "classic"
      ;;
    *)
      echo "Unsupported PX4 model '$model'." >&2
      echo "Supported PX4_MODEL values: $(sitl_supported_models)" >&2
      return 1
      ;;
  esac
}

sitl_make_target() {
  local model="$1"

  case "$model" in
    gz_x500)
      printf '%s\n' "gz_x500"
      ;;
    gazebo-classic)
      printf '%s\n' "gazebo-classic_typhoon_h480"
      ;;
    gazebo-classic_typhoon_h480)
      printf '%s\n' "gazebo-classic_typhoon_h480"
      ;;
    gazebo-classic_iris_fpv_cam)
      printf '%s\n' "gazebo-classic_iris_fpv_cam"
      ;;
    *)
      echo "Unsupported PX4 model '$model'." >&2
      echo "Supported PX4_MODEL values: $(sitl_supported_models)" >&2
      return 1
      ;;
  esac
}

sitl_require_model_supported() {
  local model="$1"
  local runtime

  runtime="$(sitl_model_runtime "$model")"

  case "$runtime" in
    harmonic)
      if ! sitl_has_gz_harmonic_stack; then
        echo "PX4 model '$model' requires the Gazebo Harmonic development packages." >&2
        return 1
      fi
      ;;
    classic)
      if ! sitl_has_gazebo_classic_stack; then
        echo "PX4 model '$model' requires Gazebo Classic to be installed." >&2
        return 1
      fi
      ;;
  esac
}

sitl_resolve_px4_model() {
  local requested_model="${1:-}"

  if [ -n "$requested_model" ]; then
    sitl_require_model_supported "$requested_model"
    printf '%s\n' "$requested_model"
    return
  fi

  if sitl_has_gz_harmonic_stack; then
    printf '%s\n' "gz_x500"
    return
  fi

  if sitl_has_gazebo_classic_stack; then
    printf '%s\n' "gazebo-classic"
    return
  fi

  echo "No supported PX4 simulator stack detected." >&2
  echo "Install Gazebo Harmonic for gz_x500 or Gazebo Classic for the fallback path." >&2
  return 1
}
