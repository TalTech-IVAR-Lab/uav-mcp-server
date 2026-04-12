"""Environment-backed settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    backend_mode: Literal["live", "local"] = Field(default="live")
    px4_connection_string: str = Field(default="udpin://0.0.0.0:14540")
    geofence_center_lat: float = Field(default=46.2331)
    geofence_center_lon: float = Field(default=6.0556)
    geofence_radius_m: float = Field(default=500.0, gt=0)
    min_altitude_m: float = Field(default=2.0, ge=0)
    max_altitude_m: float = Field(default=120.0, gt=0)
    max_speed_m_s: float = Field(default=15.0, gt=0)
    max_relative_move_distance_m: float = Field(default=150.0, gt=0)
    min_orbit_radius_m: float = Field(default=5.0, gt=0)
    max_orbit_radius_m: float = Field(default=200.0, gt=0)
    default_takeoff_altitude_m: float = Field(default=10.0, gt=0)
    default_mission_speed_m_s: float = Field(default=6.0, gt=0)
    command_rate_limit_per_sec: int = Field(default=2, ge=1)
    telemetry_rate_hz: int = Field(default=5, ge=1)
    min_battery_percent: int = Field(default=20, ge=0, le=100)
    camera_enabled: bool = Field(default=True)
    camera_ros_topic: str = Field(default="/usb_cam/image_raw")
    camera_fps: int = Field(default=15, ge=1, le=60)
    camera_helper_python_bin: str = Field(default="python3.10")
    camera_ros_setup_script: str = Field(default="/opt/ros/humble/setup.bash")
    camera_gazebo_topic_suffix: str = Field(default="/fpv_cam/link/camera/image")
    camera_width_px: int = Field(default=320, ge=1)
    camera_height_px: int = Field(default=240, ge=1)
    camera_hfov_rad: float = Field(default=1.047, gt=0)
    camera_focal_length_px: float = Field(default=277.191356, gt=0)
    camera_mount_yaw_deg: float = Field(default=0.0)
    camera_mount_pitch_deg: float = Field(default=0.0)
    camera_mount_roll_deg: float = Field(default=0.0)
    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
