"""Live camera intrinsics discovery via the gz transport CLI.

PX4 SITL renders the simulated camera with whatever ``<horizontal_fov>`` and
image size are declared in the model SDF. The ``.env`` file mirrors those
numbers manually — if the two drift (regenerating a model, swapping a lens,
typoing a focal length), the pixel-to-world projection silently uses wrong
intrinsics and edge-of-frame target selection becomes inaccurate.

This module shells out to ``gz topic --echo`` once at server startup to read
the camera_info message gz publishes for the active camera sensor, and
returns the K matrix the renderer is *actually* using. Pure subprocess call —
no Python gz-transport bindings required, so it works inside the existing
.venv.

Returns None on any failure (gz CLI missing, sim not up yet, topic timeout,
parse mismatch). Callers should fall back to .env-derived intrinsics.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TypedDict


class CameraIntrinsics(TypedDict):
    fx: float
    fy: float
    cx: float
    cy: float
    width_px: int
    height_px: int


def probe_camera_intrinsics_via_gz(
    *,
    gazebo_topic_suffix: str,
    timeout_s: float = 3.0,
) -> CameraIntrinsics | None:
    """Return live camera K matrix from the running gz sim, or None on failure.

    ``gazebo_topic_suffix`` is the same suffix the camera bridge uses to find
    the image topic (e.g. ``/camera_link/sensor/camera/image``). The camera_info
    topic is the image topic with ``/image`` replaced by ``/camera_info``.
    """
    if shutil.which("gz") is None:
        return None

    # Discover the full topic by listing topics matching the camera suffix.
    # gz topic -l completes quickly when the sim is up; on a cold sim it may
    # take a moment, hence the explicit timeout.
    try:
        listed = subprocess.run(
            ["gz", "topic", "-l"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if listed.returncode != 0:
        return None

    image_topic = next(
        (line.strip() for line in listed.stdout.splitlines()
         if line.strip().endswith(gazebo_topic_suffix)),
        None,
    )
    if image_topic is None:
        return None
    if not image_topic.endswith("/image"):
        return None
    camera_info_topic = image_topic[: -len("/image")] + "/camera_info"

    try:
        echoed = subprocess.run(
            ["gz", "topic", "-t", camera_info_topic, "--echo", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if echoed.returncode != 0 or not echoed.stdout.strip():
        return None

    return _parse_camera_info(echoed.stdout)


# The CLI prints a protobuf text dump. We don't pull in a protobuf parser for
# this; the layout is stable across gz-msgs10/11 and a couple of regexes is
# all we need.
_WIDTH_RE = re.compile(r"^width:\s*(\d+)", re.MULTILINE)
_HEIGHT_RE = re.compile(r"^height:\s*(\d+)", re.MULTILINE)
# The K matrix is inside an `intrinsics {}` block as a flat list of 9 floats.
_K_BLOCK_RE = re.compile(r"intrinsics\s*\{([^}]+)\}", re.DOTALL)
_K_FLOAT_RE = re.compile(r"k:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def _parse_camera_info(payload: str) -> CameraIntrinsics | None:
    width_match = _WIDTH_RE.search(payload)
    height_match = _HEIGHT_RE.search(payload)
    if not width_match or not height_match:
        return None
    width = int(width_match.group(1))
    height = int(height_match.group(1))

    k_block = _K_BLOCK_RE.search(payload)
    if k_block is None:
        return None
    floats = [float(m.group(1)) for m in _K_FLOAT_RE.finditer(k_block.group(1))]
    if len(floats) < 9:
        return None

    fx, _, cx, _, fy, cy, *_ = floats
    if fx <= 0 or fy <= 0:
        return None
    return CameraIntrinsics(
        fx=fx, fy=fy, cx=cx, cy=cy,
        width_px=width, height_px=height,
    )
