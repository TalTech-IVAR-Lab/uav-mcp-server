"""Pixel-to-world projection helpers for dashboard target selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, radians, sin, sqrt, tan
from typing import TYPE_CHECKING

from uav_mcp_server.navigation import offset_coordinate

if TYPE_CHECKING:
    from uav_mcp_server.terrain import TerrainSampler

_METERS_PER_DEG_LAT = 111320.0


@dataclass(slots=True)
class CameraParams:
    width_px: int
    height_px: int
    hfov_rad: float
    focal_length_px: float | None = None
    mount_yaw_deg: float = 0.0
    mount_pitch_deg: float = 0.0
    mount_roll_deg: float = 0.0
    # Optical-centre overrides. When None, the principal point defaults to the
    # image centre. Live camera_info from gz publishes the real K matrix, and
    # for cameras with off-centre principal points the difference matters at
    # frame edges.
    principal_x_px: float | None = None
    principal_y_px: float | None = None

    def resolved_focal_length_px(self) -> float:
        if self.focal_length_px is not None:
            return self.focal_length_px
        return self.width_px / (2.0 * tan(self.hfov_rad / 2.0))

    def resolved_principal_x_px(self) -> float:
        if self.principal_x_px is not None:
            return self.principal_x_px
        return self.width_px / 2.0

    def resolved_principal_y_px(self) -> float:
        if self.principal_y_px is not None:
            return self.principal_y_px
        return self.height_px / 2.0

    def to_dict(self) -> dict[str, float | int]:
        values = asdict(self)
        if values["focal_length_px"] is None:
            values["focal_length_px"] = self.resolved_focal_length_px()
        if values["principal_x_px"] is None:
            values["principal_x_px"] = self.resolved_principal_x_px()
        if values["principal_y_px"] is None:
            values["principal_y_px"] = self.resolved_principal_y_px()
        return values


@dataclass(slots=True)
class DronePose:
    lat_deg: float
    lon_deg: float
    absolute_altitude_m: float
    relative_altitude_m: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    home_absolute_altitude_m: float | None = None

    def altitude_agl_m(self) -> float:
        return self.relative_altitude_m

    def ground_absolute_altitude_m(self) -> float:
        if self.home_absolute_altitude_m is not None:
            return self.home_absolute_altitude_m
        return self.absolute_altitude_m - self.relative_altitude_m


@dataclass(slots=True)
class ProjectedPoint:
    latitude_deg: float
    longitude_deg: float
    absolute_altitude_m: float
    north_m: float
    east_m: float
    distance_m: float
    # Diagnostic fields — populated when a terrain sampler is in play. These
    # let the dashboard / debugger see why a particular click landed where it
    # did, since edge-of-frame projection error compounds three independent
    # factors (terrain offset, gimbal lag, drone attitude noise).
    terrain_used: bool = False
    terrain_iterations: int = 0
    terrain_elevation_m: float | None = None
    flat_ground_distance_m: float | None = None

    def to_dict(self) -> dict[str, float | bool | int | None]:
        return asdict(self)


def pixel_to_world(
    u: float,
    v: float,
    camera_params: CameraParams,
    drone_pose: DronePose,
    terrain: "TerrainSampler | None" = None,
    *,
    origin_lat_deg: float | None = None,
    origin_lon_deg: float | None = None,
) -> ProjectedPoint:
    """Project a pixel to a ground point in WGS84.

    The flat-ground path uses ``drone_pose.relative_altitude_m`` as AGL — fine
    over flat terrain at home elevation, but wrong by tens of metres on the
    TalTech heightmap at oblique gimbal angles.

    When ``terrain`` is supplied (with ``origin_lat_deg``/``origin_lon_deg``),
    the function does fixed-point iteration: project with current AGL, sample
    the heightmap at the projected XY, recompute AGL as
    ``drone_world_z - terrain_z_at_target``, re-project, repeat. Converges
    in 2–4 iterations for normal gimbal angles; bails out when the projection
    falls off the heightmap or the iteration drifts upward (ray re-enters the
    sky).
    """
    if not 0.0 <= u <= float(camera_params.width_px):
        raise ValueError("Pixel u coordinate is outside the camera frame.")
    if not 0.0 <= v <= float(camera_params.height_px):
        raise ValueError("Pixel v coordinate is outside the camera frame.")

    altitude_agl_m = drone_pose.altitude_agl_m()
    if altitude_agl_m <= 0.0:
        raise ValueError("Relative altitude must be positive for ground projection.")

    focal_length_px = camera_params.resolved_focal_length_px()
    principal_x = camera_params.resolved_principal_x_px()
    principal_y = camera_params.resolved_principal_y_px()

    ray_camera = _normalize(
        (
            1.0,
            (u - principal_x) / focal_length_px,
            (v - principal_y) / focal_length_px,
        )
    )
    ray_body = _rotate_frd(
        ray_camera,
        yaw_deg=camera_params.mount_yaw_deg,
        pitch_deg=camera_params.mount_pitch_deg,
        roll_deg=camera_params.mount_roll_deg,
    )
    ray_ned = _rotate_frd(
        ray_body,
        yaw_deg=drone_pose.yaw_deg,
        pitch_deg=drone_pose.pitch_deg,
        roll_deg=drone_pose.roll_deg,
    )

    down_component = ray_ned[2]
    if down_component <= 1e-6:
        raise ValueError("Selected pixel projects above the ground horizon.")

    # Initial guess: flat ground at home altitude.
    scale = altitude_agl_m / down_component
    north_m = ray_ned[0] * scale
    east_m = ray_ned[1] * scale
    absolute_altitude_m = drone_pose.ground_absolute_altitude_m()
    flat_ground_distance_m = sqrt(north_m**2 + east_m**2)

    terrain_used = False
    terrain_iterations = 0
    terrain_elevation_m: float | None = None

    # Below ~12° off the horizon the ground projection is geometrically
    # ill-conditioned: a 1 m terrain-elevation change moves the projection
    # by tens of metres because the ray skims almost parallel to the ground.
    # In that regime the terrain-aware iteration produces *worse* answers
    # than the flat-ground assumption (we observed it jumping from 75 m to
    # 2.3 km on a single iteration). Stay on the flat-ground answer there.
    _MIN_DOWN_COMPONENT_FOR_TERRAIN = 0.2  # sin(11.5°)
    terrain_active = (
        terrain is not None
        and origin_lat_deg is not None
        and origin_lon_deg is not None
        and down_component >= _MIN_DOWN_COMPONENT_FOR_TERRAIN
    )

    if terrain_active:
        assert terrain is not None and origin_lat_deg is not None and origin_lon_deg is not None
        drone_world_z = terrain.drone_abs_alt_to_world_z(drone_pose.absolute_altitude_m)
        # Drone position in world ENU (metres relative to spherical_coords origin).
        drone_world_east, drone_world_north = _latlon_to_meters_enu(
            drone_pose.lat_deg, drone_pose.lon_deg, origin_lat_deg, origin_lon_deg
        )

        # Maximum allowed jump in projection distance between iterations.
        # Without this, a single high/low terrain sample on the iteration
        # line can fling the result orders of magnitude away from the prior
        # estimate. Multiplicative bound keeps it stable across drone alts.
        _MAX_RELATIVE_JUMP = 3.0

        last_scale = scale
        for iteration in range(6):
            target_world_east = drone_world_east + east_m
            target_world_north = drone_world_north + north_m
            terrain_z = terrain.elevation_at_world_xy(
                target_world_east, target_world_north
            )
            if terrain_z is None:
                # Off the heightmap — keep the flat-ground result rather than
                # extrapolate. Map will show the projected point with the
                # original home-altitude assumption.
                break
            agl_above_terrain = drone_world_z - terrain_z
            if agl_above_terrain <= 0.0:
                # Ray entered the terrain from below (drone is below the
                # projected ground point). Stop iterating; the flat-ground
                # answer is the best we can offer.
                break
            new_scale = agl_above_terrain / down_component
            # Reject pathological jumps. If the iteration wants to move the
            # ground intersection by more than 3× the previous estimate, the
            # heightmap is probably non-monotonic along the ray; commit the
            # last stable estimate instead of overshooting.
            if (
                last_scale > 0
                and (new_scale / last_scale > _MAX_RELATIVE_JUMP
                     or last_scale / new_scale > _MAX_RELATIVE_JUMP)
            ):
                break
            terrain_iterations = iteration + 1
            terrain_elevation_m = terrain_z
            terrain_used = True
            if abs(new_scale - last_scale) < 0.05:
                # Converged within 5 cm worth of distance change.
                scale = new_scale
                north_m = ray_ned[0] * scale
                east_m = ray_ned[1] * scale
                absolute_altitude_m = terrain.world_z_to_abs_alt(terrain_z)
                break
            scale = new_scale
            last_scale = new_scale
            north_m = ray_ned[0] * scale
            east_m = ray_ned[1] * scale
            absolute_altitude_m = terrain.world_z_to_abs_alt(terrain_z)

    latitude_deg, longitude_deg = offset_coordinate(
        drone_pose.lat_deg,
        drone_pose.lon_deg,
        north_m,
        east_m,
    )
    distance_m = sqrt(north_m**2 + east_m**2)
    return ProjectedPoint(
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        absolute_altitude_m=absolute_altitude_m,
        north_m=north_m,
        east_m=east_m,
        distance_m=distance_m,
        terrain_used=terrain_used,
        terrain_iterations=terrain_iterations,
        terrain_elevation_m=terrain_elevation_m,
        flat_ground_distance_m=flat_ground_distance_m,
    )


def _latlon_to_meters_enu(
    target_lat_deg: float,
    target_lon_deg: float,
    origin_lat_deg: float,
    origin_lon_deg: float,
) -> tuple[float, float]:
    """Return (east_m, north_m) from origin to target.

    Equirectangular small-angle approximation — good to <1 m within a few km
    of the origin, which is well past the gz heightmap footprint.
    """
    east_m = (
        (target_lon_deg - origin_lon_deg)
        * _METERS_PER_DEG_LAT
        * cos(radians(origin_lat_deg))
    )
    north_m = (target_lat_deg - origin_lat_deg) * _METERS_PER_DEG_LAT
    return east_m, north_m


def _rotate_frd(
    vector: tuple[float, float, float],
    *,
    yaw_deg: float,
    pitch_deg: float,
    roll_deg: float,
) -> tuple[float, float, float]:
    yaw_rad = radians(yaw_deg)
    pitch_rad = radians(pitch_deg)
    roll_rad = radians(roll_deg)

    sin_yaw = sin(yaw_rad)
    cos_yaw = cos(yaw_rad)
    sin_pitch = sin(pitch_rad)
    cos_pitch = cos(pitch_rad)
    sin_roll = sin(roll_rad)
    cos_roll = cos(roll_rad)

    rotation = (
        (
            cos_yaw * cos_pitch,
            cos_yaw * sin_pitch * sin_roll - sin_yaw * cos_roll,
            cos_yaw * sin_pitch * cos_roll + sin_yaw * sin_roll,
        ),
        (
            sin_yaw * cos_pitch,
            sin_yaw * sin_pitch * sin_roll + cos_yaw * cos_roll,
            sin_yaw * sin_pitch * cos_roll - cos_yaw * sin_roll,
        ),
        (
            -sin_pitch,
            cos_pitch * sin_roll,
            cos_pitch * cos_roll,
        ),
    )
    return _matmul(rotation, vector)


def _matmul(
    matrix: tuple[tuple[float, float, float], ...],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(
        row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2]
        for row in matrix
    )


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = sqrt(sum(component * component for component in vector))
    if magnitude == 0.0:
        raise ValueError("Zero-length vector cannot be normalized.")
    return tuple(component / magnitude for component in vector)
