"""Environment-backed settings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True, slots=True)
class Px4ModelProfile:
    model: str
    camera_gazebo_topic_suffix: str
    camera_width_px: int
    camera_height_px: int
    camera_hfov_rad: float
    camera_focal_length_px: float
    supports_gimbal_pitch: bool
    supports_gimbal_yaw: bool = False


IRIS_FPV_CAM_PROFILE = Px4ModelProfile(
    model="gazebo-classic_iris_fpv_cam",
    camera_gazebo_topic_suffix="/fpv_cam/link/camera/image",
    camera_width_px=640,
    camera_height_px=480,
    camera_hfov_rad=1.047,
    camera_focal_length_px=554.382712,
    supports_gimbal_pitch=False,
    supports_gimbal_yaw=False,
)
TYPHOON_H480_PROFILE = Px4ModelProfile(
    model="gazebo-classic_typhoon_h480",
    camera_gazebo_topic_suffix="/cgo3_camera_link/camera/image",
    camera_width_px=640,
    camera_height_px=360,
    camera_hfov_rad=2.0,
    camera_focal_length_px=205.46963709898586,
    supports_gimbal_pitch=True,
    supports_gimbal_yaw=True,
)


def normalize_px4_model_name(model: str | None) -> str:
    normalized = (model or "").strip()
    if normalized == "gazebo-classic":
        return TYPHOON_H480_PROFILE.model
    return normalized


def px4_model_profile(model: str | None) -> Px4ModelProfile | None:
    normalized = normalize_px4_model_name(model)
    if normalized in {IRIS_FPV_CAM_PROFILE.model, "iris_fpv_cam"}:
        return IRIS_FPV_CAM_PROFILE
    if normalized in {TYPHOON_H480_PROFILE.model, "typhoon_h480"}:
        return TYPHOON_H480_PROFILE
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    backend_mode: Literal["live", "local"] = Field(default="live")
    px4_model: str = Field(default="")
    px4_connection_string: str = Field(default="udpin://0.0.0.0:14540")
    geofence_center_lat: float = Field(default=59.3949741)
    geofence_center_lon: float = Field(default=24.6676189)
    sim_classic_world_name: str = Field(default="taltech_campus")
    sim_classic_spawn_x_m: float = Field(default=0.0)
    sim_classic_spawn_y_m: float = Field(default=0.0)
    sim_classic_spawn_z_m: float = Field(default=0.0)
    sim_classic_spawn_yaw_rad: float = Field(default=0.0)
    preflight_wait_timeout_s: float = Field(default=30.0, gt=0)
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
    assistant_enabled: bool = Field(default=True)
    assistant_model: str = Field(default="gemini-2.5-flash")
    assistant_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    assistant_preview_default: bool = Field(default=True)
    assistant_bypass_available: bool = Field(default=True)
    assistant_mcp_url: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)
    manual_control_translation_step_m: float = Field(default=2.0, gt=0)
    manual_control_altitude_step_m: float = Field(default=1.5, gt=0)
    manual_control_yaw_step_deg: float = Field(default=15.0, gt=0)
    manual_control_gimbal_pitch_step_deg: float = Field(default=10.0, gt=0)
    manual_control_gimbal_yaw_step_deg: float = Field(default=15.0, gt=0)
    manual_control_supports_translation: bool = Field(default=True)
    manual_control_supports_altitude: bool = Field(default=True)
    manual_control_supports_yaw: bool = Field(default=True)
    manual_control_supports_gimbal_pitch: bool = Field(default=True)
    manual_control_supports_gimbal_yaw: bool = Field(default=True)
    manual_control_rate_limit_per_sec: int = Field(default=5, ge=1)
    telemetry_rate_hz: int = Field(default=5, ge=1)
    min_battery_percent: int = Field(default=20, ge=0, le=100)
    camera_enabled: bool = Field(default=True)
    camera_ros_topic: str = Field(default="/usb_cam/image_raw")
    camera_fps: int = Field(default=15, ge=1, le=60)
    camera_helper_python_bin: str = Field(default="python3.10")
    camera_ros_setup_script: str = Field(default="/opt/ros/humble/setup.bash")
    camera_gazebo_topic_suffix: str = Field(default="/fpv_cam/link/camera/image")
    camera_width_px: int = Field(default=640, ge=1)
    camera_height_px: int = Field(default=480, ge=1)
    camera_hfov_rad: float = Field(default=1.047, gt=0)
    camera_focal_length_px: float = Field(default=554.382712, gt=0)
    camera_mount_yaw_deg: float = Field(default=0.0)
    camera_mount_pitch_deg: float = Field(default=0.0)
    camera_mount_roll_deg: float = Field(default=0.0)
    log_level: str = Field(default="INFO")

    @model_validator(mode="after")
    def apply_px4_model_profile(self) -> Settings:
        profile = px4_model_profile(self.px4_model)
        if profile is None:
            return self

        self.px4_model = profile.model

        if "camera_gazebo_topic_suffix" not in self.model_fields_set:
            self.camera_gazebo_topic_suffix = profile.camera_gazebo_topic_suffix
        if "camera_width_px" not in self.model_fields_set:
            self.camera_width_px = profile.camera_width_px
        if "camera_height_px" not in self.model_fields_set:
            self.camera_height_px = profile.camera_height_px
        if "camera_hfov_rad" not in self.model_fields_set:
            self.camera_hfov_rad = profile.camera_hfov_rad
        if "camera_focal_length_px" not in self.model_fields_set:
            self.camera_focal_length_px = profile.camera_focal_length_px
        if "manual_control_supports_gimbal_pitch" not in self.model_fields_set:
            self.manual_control_supports_gimbal_pitch = profile.supports_gimbal_pitch
        if "manual_control_supports_gimbal_yaw" not in self.model_fields_set:
            self.manual_control_supports_gimbal_yaw = profile.supports_gimbal_yaw

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
