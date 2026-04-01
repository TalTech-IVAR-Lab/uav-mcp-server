"""Shared request and response models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DroneState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    READY = "ready"
    ARMED = "armed"
    AIRBORNE = "airborne"
    LANDING = "landing"
    FAULT = "fault"


class CommandResult(BaseModel):
    success: bool
    message: str
    data: dict[str, object] | None = None


class TelemetrySnapshot(BaseModel):
    state: DroneState = DroneState.DISCONNECTED
    armed: bool = False
    in_air: bool = False
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    relative_altitude_m: float | None = None
    battery_percent: float | None = None
    flight_mode: str | None = None


class WaypointInput(BaseModel):
    latitude_deg: float = Field(..., ge=-90, le=90)
    longitude_deg: float = Field(..., ge=-180, le=180)
    altitude_m: float = Field(..., gt=0)
    speed_m_s: float | None = Field(default=None, gt=0)

