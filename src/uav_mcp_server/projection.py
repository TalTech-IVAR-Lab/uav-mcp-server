"""Pixel-to-world projection helpers for dashboard target selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, radians, sin, sqrt, tan

from uav_mcp_server.navigation import offset_coordinate


@dataclass(slots=True)
class CameraParams:
    width_px: int
    height_px: int
    hfov_rad: float
    focal_length_px: float | None = None
    mount_yaw_deg: float = 0.0
    mount_pitch_deg: float = 0.0
    mount_roll_deg: float = 0.0

    def resolved_focal_length_px(self) -> float:
        if self.focal_length_px is not None:
            return self.focal_length_px
        return self.width_px / (2.0 * tan(self.hfov_rad / 2.0))

    def to_dict(self) -> dict[str, float | int]:
        values = asdict(self)
        if values["focal_length_px"] is None:
            values["focal_length_px"] = self.resolved_focal_length_px()
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

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def pixel_to_world(
    u: float,
    v: float,
    camera_params: CameraParams,
    drone_pose: DronePose,
) -> ProjectedPoint:
    if not 0.0 <= u <= float(camera_params.width_px):
        raise ValueError("Pixel u coordinate is outside the camera frame.")
    if not 0.0 <= v <= float(camera_params.height_px):
        raise ValueError("Pixel v coordinate is outside the camera frame.")

    altitude_agl_m = drone_pose.altitude_agl_m()
    if altitude_agl_m <= 0.0:
        raise ValueError("Relative altitude must be positive for ground projection.")

    focal_length_px = camera_params.resolved_focal_length_px()
    principal_x = camera_params.width_px / 2.0
    principal_y = camera_params.height_px / 2.0

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

    scale = altitude_agl_m / down_component
    north_m = ray_ned[0] * scale
    east_m = ray_ned[1] * scale
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
        absolute_altitude_m=drone_pose.ground_absolute_altitude_m(),
        north_m=north_m,
        east_m=east_m,
        distance_m=distance_m,
    )


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
