"""Terrain elevation sampler for camera-to-ground projection.

The PX4 gz NavSat plugin uses the world's ``<spherical_coordinates>`` block as
the GPS reference, so drone telemetry (``absolute_altitude_m``, AMSL) maps to
world ENU Z via ``Z = abs_alt - origin_alt_amsl``. Camera projection needs the
drone's height above the actual ground at the projected pixel, not above the
takeoff point — the TalTech heightmap varies by ±15 m, and a flat-ground
assumption mis-locates the projected lat/lon by tens of metres at oblique
gimbal angles.

This module loads the 16-bit heightmap PNG once and exposes a bilinear
sampler keyed on world ENU XY. Returns ``None`` outside the heightmap
footprint so callers can fall back to a flat-ground assumption instead of
extrapolating garbage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True, slots=True)
class HeightmapSpec:
    """Heightmap geometry as declared in ``sim/gz/worlds/taltech_campus.world``.

    All metres, ENU world frame. ``pos_*`` is the heightmap's *centre* (matches
    SDF ``<heightmap><pos>``). ``size_z`` is the full vertical range mapped to
    pixel value 0..max; the bottom of the heightmap sits at ``pos_z - size_z/2``
    and the top at ``pos_z + size_z/2``.

    ``origin_alt_amsl`` is the world's ``<spherical_coordinates><elevation>``,
    needed to convert drone telemetry (m AMSL) into world ENU Z.
    """

    png_path: Path
    pos_x: float
    pos_y: float
    pos_z: float
    size_x: float
    size_y: float
    size_z: float
    origin_alt_amsl: float

    @classmethod
    def taltech_default(cls, repo_root: Path) -> HeightmapSpec:
        # Numbers transcribed from sim/gz/worlds/taltech_campus.world. If those
        # change (regenerate the terrain), update here too.
        return cls(
            png_path=repo_root / "sim/gz/worlds/terrain_data/height_map.png",
            pos_x=299.32,
            pos_y=13.91,
            pos_z=-8.01,
            size_x=1352.11,
            size_y=1105.44,
            size_z=30.2,
            origin_alt_amsl=27.8,
        )


class TerrainSampler:
    """Bilinear sampler over a 16-bit grayscale heightmap PNG.

    Thread-safe for concurrent reads (numpy array access is GIL-protected for
    the simple indexing we do). The PNG is loaded once at construction.
    """

    def __init__(self, spec: HeightmapSpec) -> None:
        # Local imports so missing Pillow/numpy doesn't break the server at
        # import time — terrain awareness is optional, not required.
        from PIL import Image
        import numpy as np

        self.spec = spec
        with Image.open(str(spec.png_path)) as image:
            mode = image.mode
            arr: np.ndarray = np.asarray(image)

        if arr.ndim != 2:
            raise ValueError(
                f"Heightmap PNG must be single-channel grayscale; got shape {arr.shape}"
            )

        # 16-bit grayscale ('I' or 'I;16') has max value 65535; 8-bit 'L' has 255.
        self._max_value = 65535.0 if mode.startswith("I") else 255.0
        self._heights = arr.astype("float64", copy=False)
        rows, cols = arr.shape
        self._cols_m1 = float(cols - 1)
        self._rows_m1 = float(rows - 1)
        self._half_x = spec.size_x / 2.0
        self._half_y = spec.size_y / 2.0
        # gz heightmap convention (verified empirically against DART output
        # "translated by z=15.1" and against the known terrain elevation at
        # the world origin): <pos>'s Z is the BOTTOM of the heightmap, not
        # the centre. Pixel value 0 → world Z = pos_z; max value → world Z
        # = pos_z + size_z. So a pixel of ~26 % brightness at the world
        # origin gives Z ≈ -8.01 + 0.26·30.2 ≈ 0 m, which matches the
        # GPS-origin elevation (27.8 m AMSL) seen in flight telemetry.
        self._z_bottom = spec.pos_z

    def elevation_at_world_xy(
        self, x_east_m: float, y_north_m: float
    ) -> float | None:
        """Return terrain world Z (ENU up, metres) at the given world XY.

        Returns ``None`` when the query falls outside the heightmap footprint —
        the caller should fall back to a flat-ground assumption rather than
        extrapolate from edge pixels.
        """
        spec = self.spec
        # Heightmap-local coords: origin at heightmap centre.
        local_x = x_east_m - spec.pos_x
        local_y = y_north_m - spec.pos_y
        if (
            local_x < -self._half_x
            or local_x > self._half_x
            or local_y < -self._half_y
            or local_y > self._half_y
        ):
            return None

        # PNG indexing: column grows with east (+X), row grows with -north
        # (top of the image is +Y / north). This matches gz heightmap's image
        # interpretation; verify against your terrain generator if you swap
        # heightmaps.
        u = (local_x + self._half_x) / spec.size_x  # 0..1, west→east
        v = (self._half_y - local_y) / spec.size_y  # 0..1, north→south
        col = u * self._cols_m1
        row = v * self._rows_m1

        c0 = int(col)
        r0 = int(row)
        c1 = min(c0 + 1, int(self._cols_m1))
        r1 = min(r0 + 1, int(self._rows_m1))
        fc = col - c0
        fr = row - r0

        h00 = self._heights[r0, c0]
        h01 = self._heights[r0, c1]
        h10 = self._heights[r1, c0]
        h11 = self._heights[r1, c1]
        # Bilinear interpolation
        raw = (
            h00 * (1.0 - fc) * (1.0 - fr)
            + h01 * fc * (1.0 - fr)
            + h10 * (1.0 - fc) * fr
            + h11 * fc * fr
        )
        return self._z_bottom + (raw / self._max_value) * spec.size_z

    def drone_abs_alt_to_world_z(self, abs_alt_m: float) -> float:
        """Convert drone MAVLink absolute altitude (m AMSL) to world ENU Z."""
        return abs_alt_m - self.spec.origin_alt_amsl

    def world_z_to_abs_alt(self, world_z_m: float) -> float:
        return world_z_m + self.spec.origin_alt_amsl
