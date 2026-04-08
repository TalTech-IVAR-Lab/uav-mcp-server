"""Environment-backed settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    px4_connection_string: str = Field(default="udpin://0.0.0.0:14540")
    geofence_center_lat: float = Field(default=59.3948)
    geofence_center_lon: float = Field(default=24.6614)
    geofence_radius_m: float = Field(default=500.0, gt=0)
    min_altitude_m: float = Field(default=2.0, ge=0)
    max_altitude_m: float = Field(default=120.0, gt=0)
    max_speed_m_s: float = Field(default=15.0, gt=0)
    max_relative_move_distance_m: float = Field(default=150.0, gt=0)
    default_takeoff_altitude_m: float = Field(default=10.0, gt=0)
    default_mission_speed_m_s: float = Field(default=6.0, gt=0)
    command_rate_limit_per_sec: int = Field(default=2, ge=1)
    telemetry_rate_hz: int = Field(default=5, ge=1)
    min_battery_percent: int = Field(default=20, ge=0, le=100)
    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
