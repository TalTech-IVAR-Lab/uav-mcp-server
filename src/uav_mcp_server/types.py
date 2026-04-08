"""Shared request and response models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DroneState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    READY = "ready"
    ARMED = "armed"
    AIRBORNE = "airborne"
    LANDING = "landing"
    FAULT = "fault"


class ErrorCode(StrEnum):
    BACKEND_ERROR = "backend_error"
    PREFLIGHT_FAILED = "preflight_failed"
    WRONG_STATE = "wrong_state"
    GEOFENCE_VIOLATION = "geofence_violation"
    RATE_LIMITED = "rate_limited"
    CONNECTION_LOST = "connection_lost"
    LOW_BATTERY = "low_battery"
    NOT_IMPLEMENTED = "not_implemented"
    INVALID_PARAMS = "invalid_params"


class CommandResult(BaseModel):
    success: bool
    message: str
    data: dict[str, Any] | None = None
    error_code: ErrorCode | None = None

    @classmethod
    def ok(cls, message: str, data: dict[str, Any] | None = None) -> "CommandResult":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(
        cls,
        message: str,
        error_code: ErrorCode,
        data: dict[str, Any] | None = None,
    ) -> "CommandResult":
        return cls(success=False, message=message, data=data, error_code=error_code)


class TelemetrySnapshot(BaseModel):
    state: DroneState = DroneState.DISCONNECTED
    connected: bool = False
    armed: bool = False
    in_air: bool = False
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    absolute_altitude_m: float | None = None
    relative_altitude_m: float | None = None
    battery_percent: float | None = None
    flight_mode: str | None = None
    home_absolute_altitude_m: float | None = None
    is_global_position_ok: bool = False
    is_home_position_ok: bool = False
    is_gyrometer_calibration_ok: bool = False
    is_accelerometer_calibration_ok: bool = False
    gps_satellites: int | None = Field(default=None, ge=0)

    def inferred_home_absolute_altitude_m(self) -> float | None:
        if self.home_absolute_altitude_m is not None:
            return self.home_absolute_altitude_m
        if self.absolute_altitude_m is None or self.relative_altitude_m is None:
            return None
        return self.absolute_altitude_m - self.relative_altitude_m


class WaypointInput(BaseModel):
    latitude_deg: float = Field(..., ge=-90, le=90)
    longitude_deg: float = Field(..., ge=-180, le=180)
    altitude_m: float = Field(..., gt=0)
    speed_m_s: float | None = Field(default=None, gt=0)


class PositionUpdate(BaseModel):
    latitude_deg: float = Field(..., ge=-90, le=90)
    longitude_deg: float = Field(..., ge=-180, le=180)
    absolute_altitude_m: float
    relative_altitude_m: float


class BatteryUpdate(BaseModel):
    battery_percent: float = Field(..., ge=0, le=100)


class HealthUpdate(BaseModel):
    is_global_position_ok: bool = False
    is_home_position_ok: bool = False
    is_gyrometer_calibration_ok: bool = False
    is_accelerometer_calibration_ok: bool = False
    gps_satellites: int | None = Field(default=None, ge=0)


class MissionWaypoint(BaseModel):
    latitude_deg: float = Field(..., ge=-90, le=90)
    longitude_deg: float = Field(..., ge=-180, le=180)
    relative_altitude_m: float = Field(..., gt=0)
    speed_m_s: float = Field(..., gt=0)
    is_fly_through: bool = True


class MissionProgress(BaseModel):
    current: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class SafetyViolation(BaseModel):
    command_name: str
    message: str
    error_code: ErrorCode
    data: dict[str, Any] | None = None
