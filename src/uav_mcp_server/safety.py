"""Safety and policy checks for UAV commands."""

from __future__ import annotations

from collections import deque
from time import monotonic

from uav_mcp_server.config import Settings
from uav_mcp_server.navigation import haversine_distance_m, offset_coordinate
from uav_mcp_server.types import CommandResult, DroneState, ErrorCode, TelemetrySnapshot, WaypointInput

READ_ONLY_COMMANDS = {"get_status", "get_telemetry"}
RATE_LIMIT_EXEMPT_COMMANDS = READ_ONLY_COMMANDS | {"land", "rtl"}

ALLOWED_COMMANDS_BY_STATE: dict[DroneState, set[str]] = {
    DroneState.DISCONNECTED: {"connect", *READ_ONLY_COMMANDS},
    DroneState.CONNECTED: {"arm", *READ_ONLY_COMMANDS},
    DroneState.READY: {"arm", *READ_ONLY_COMMANDS},
    DroneState.ARMED: {"disarm", "takeoff", *READ_ONLY_COMMANDS},
    DroneState.AIRBORNE: {
        "land",
        "hold",
        "rtl",
        "goto_relative",
        "orbit",
        "run_mission",
        *READ_ONLY_COMMANDS,
    },
    DroneState.LANDING: {"land", "hold", "rtl", *READ_ONLY_COMMANDS},
    DroneState.FAULT: {"connect", *READ_ONLY_COMMANDS},
}


class SafetyValidator:
    """Central command validation for state, bounds, and preflight checks."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._action_window: deque[float] = deque()

    def validate(
        self,
        command_name: str,
        telemetry: TelemetrySnapshot,
        *,
        altitude_m: float | None = None,
        north_m: float | None = None,
        east_m: float | None = None,
        latitude_deg: float | None = None,
        longitude_deg: float | None = None,
        absolute_altitude_m: float | None = None,
        radius_m: float | None = None,
        velocity_m_s: float | None = None,
        waypoints: list[WaypointInput] | None = None,
    ) -> CommandResult | None:
        state_violation = self._validate_state(command_name, telemetry.state)
        if state_violation is not None:
            return state_violation

        if command_name == "arm":
            violation = self._validate_arm(telemetry)
        elif command_name == "takeoff":
            violation = self._validate_takeoff(altitude_m)
        elif command_name == "goto_relative":
            violation = self._validate_relative_move(
                telemetry,
                north_m=north_m,
                east_m=east_m,
                altitude_m=altitude_m,
            )
        elif command_name == "orbit":
            violation = self._validate_orbit(
                telemetry,
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                absolute_altitude_m=absolute_altitude_m,
                radius_m=radius_m,
                velocity_m_s=velocity_m_s,
            )
        elif command_name == "run_mission":
            violation = self._validate_mission(waypoints)
        else:
            violation = None

        if violation is not None:
            return violation

        rate_violation = self._check_rate_limit(command_name)
        if rate_violation is not None:
            return rate_violation

        return None

    def _validate_state(
        self,
        command_name: str,
        state: DroneState,
    ) -> CommandResult | None:
        allowed_commands = ALLOWED_COMMANDS_BY_STATE.get(state, READ_ONLY_COMMANDS)
        if command_name in allowed_commands:
            return None

        return CommandResult.fail(
            f"Command '{command_name}' is not allowed while the drone is in state '{state.value}'.",
            ErrorCode.WRONG_STATE,
            data={"state": state.value, "command_name": command_name},
        )

    def _check_rate_limit(self, command_name: str) -> CommandResult | None:
        if command_name in RATE_LIMIT_EXEMPT_COMMANDS:
            return None

        now = monotonic()
        window_seconds = 1.0
        while self._action_window and now - self._action_window[0] > window_seconds:
            self._action_window.popleft()

        if len(self._action_window) >= self._settings.command_rate_limit_per_sec:
            return CommandResult.fail(
                "Command rate limit exceeded.",
                ErrorCode.RATE_LIMITED,
                data={"command_name": command_name, "limit_per_sec": self._settings.command_rate_limit_per_sec},
            )

        self._action_window.append(now)
        return None

    def _validate_arm(self, telemetry: TelemetrySnapshot) -> CommandResult | None:
        if not telemetry.connected:
            return CommandResult.fail(
                "The vehicle is not connected.",
                ErrorCode.CONNECTION_LOST,
            )

        if not telemetry.is_global_position_ok or not telemetry.is_home_position_ok:
            return CommandResult.fail(
                "Preflight checks failed: global position or home position is not ready.",
                ErrorCode.PREFLIGHT_FAILED,
                data={
                    "is_global_position_ok": telemetry.is_global_position_ok,
                    "is_home_position_ok": telemetry.is_home_position_ok,
                },
            )

        if not telemetry.is_gyrometer_calibration_ok or not telemetry.is_accelerometer_calibration_ok:
            return CommandResult.fail(
                "Preflight checks failed: vehicle sensor calibration is incomplete.",
                ErrorCode.PREFLIGHT_FAILED,
                data={
                    "is_gyrometer_calibration_ok": telemetry.is_gyrometer_calibration_ok,
                    "is_accelerometer_calibration_ok": telemetry.is_accelerometer_calibration_ok,
                },
            )

        if telemetry.battery_percent is None:
            return CommandResult.fail(
                "Preflight checks failed: battery telemetry is unavailable.",
                ErrorCode.PREFLIGHT_FAILED,
            )

        if telemetry.battery_percent < self._settings.min_battery_percent:
            return CommandResult.fail(
                "Preflight checks failed: battery is below the minimum threshold.",
                ErrorCode.LOW_BATTERY,
                data={
                    "battery_percent": telemetry.battery_percent,
                    "minimum_percent": self._settings.min_battery_percent,
                },
            )

        return None

    def _validate_takeoff(self, altitude_m: float | None) -> CommandResult | None:
        if altitude_m is None:
            return CommandResult.fail(
                "Takeoff altitude is required.",
                ErrorCode.INVALID_PARAMS,
            )

        if not self._settings.min_altitude_m <= altitude_m <= self._settings.max_altitude_m:
            return CommandResult.fail(
                "Requested altitude is outside the configured bounds.",
                ErrorCode.INVALID_PARAMS,
                data={
                    "altitude_m": altitude_m,
                    "min_altitude_m": self._settings.min_altitude_m,
                    "max_altitude_m": self._settings.max_altitude_m,
                },
            )

        return None

    def _validate_relative_move(
        self,
        telemetry: TelemetrySnapshot,
        *,
        north_m: float | None,
        east_m: float | None,
        altitude_m: float | None,
    ) -> CommandResult | None:
        if north_m is None or east_m is None or altitude_m is None:
            return CommandResult.fail(
                "Relative movement requires north, east, and altitude parameters.",
                ErrorCode.INVALID_PARAMS,
            )

        altitude_violation = self._validate_takeoff(altitude_m)
        if altitude_violation is not None:
            return altitude_violation

        distance_m = (north_m**2 + east_m**2) ** 0.5
        if distance_m > self._settings.max_relative_move_distance_m:
            return CommandResult.fail(
                "Relative movement distance exceeds the configured limit.",
                ErrorCode.INVALID_PARAMS,
                data={
                    "distance_m": round(distance_m, 2),
                    "max_relative_move_distance_m": self._settings.max_relative_move_distance_m,
                },
            )

        if telemetry.latitude_deg is None or telemetry.longitude_deg is None:
            return CommandResult.fail(
                "Current position is unavailable; cannot validate the target.",
                ErrorCode.CONNECTION_LOST,
            )

        if telemetry.inferred_home_absolute_altitude_m() is None:
            return CommandResult.fail(
                "Home altitude is unavailable; relative movement is not safe yet.",
                ErrorCode.PREFLIGHT_FAILED,
            )

        target_latitude_deg, target_longitude_deg = offset_coordinate(
            telemetry.latitude_deg,
            telemetry.longitude_deg,
            north_m,
            east_m,
        )
        geofence_violation = self._validate_geofence(target_latitude_deg, target_longitude_deg)
        if geofence_violation is not None:
            return geofence_violation

        return None

    def _validate_mission(self, waypoints: list[WaypointInput] | None) -> CommandResult | None:
        if not waypoints:
            return CommandResult.fail(
                "Mission requires at least one waypoint.",
                ErrorCode.INVALID_PARAMS,
            )

        for index, waypoint in enumerate(waypoints):
            altitude_violation = self._validate_takeoff(waypoint.altitude_m)
            if altitude_violation is not None:
                altitude_violation.data = {
                    **(altitude_violation.data or {}),
                    "waypoint_index": index,
                }
                return altitude_violation

            if waypoint.speed_m_s is not None and waypoint.speed_m_s > self._settings.max_speed_m_s:
                return CommandResult.fail(
                    "Mission waypoint speed exceeds the configured maximum.",
                    ErrorCode.INVALID_PARAMS,
                    data={
                        "waypoint_index": index,
                        "speed_m_s": waypoint.speed_m_s,
                        "max_speed_m_s": self._settings.max_speed_m_s,
                    },
                )

            geofence_violation = self._validate_geofence(
                waypoint.latitude_deg,
                waypoint.longitude_deg,
                waypoint_index=index,
            )
            if geofence_violation is not None:
                return geofence_violation

        return None

    def _validate_orbit(
        self,
        telemetry: TelemetrySnapshot,
        *,
        latitude_deg: float | None,
        longitude_deg: float | None,
        absolute_altitude_m: float | None,
        radius_m: float | None,
        velocity_m_s: float | None,
    ) -> CommandResult | None:
        if (
            latitude_deg is None
            or longitude_deg is None
            or absolute_altitude_m is None
            or radius_m is None
            or velocity_m_s is None
        ):
            return CommandResult.fail(
                "Orbit requires latitude, longitude, altitude, radius, and velocity parameters.",
                ErrorCode.INVALID_PARAMS,
            )

        if not self._settings.min_orbit_radius_m <= radius_m <= self._settings.max_orbit_radius_m:
            return CommandResult.fail(
                "Orbit radius is outside the configured bounds.",
                ErrorCode.INVALID_PARAMS,
                data={
                    "radius_m": radius_m,
                    "min_orbit_radius_m": self._settings.min_orbit_radius_m,
                    "max_orbit_radius_m": self._settings.max_orbit_radius_m,
                },
            )

        if velocity_m_s > self._settings.max_speed_m_s:
            return CommandResult.fail(
                "Orbit velocity exceeds the configured maximum.",
                ErrorCode.INVALID_PARAMS,
                data={
                    "velocity_m_s": velocity_m_s,
                    "max_speed_m_s": self._settings.max_speed_m_s,
                },
            )

        home_absolute_altitude_m = telemetry.inferred_home_absolute_altitude_m()
        if home_absolute_altitude_m is None:
            return CommandResult.fail(
                "Home altitude is unavailable; orbit altitude cannot be validated safely.",
                ErrorCode.PREFLIGHT_FAILED,
            )

        altitude_violation = self._validate_takeoff(absolute_altitude_m - home_absolute_altitude_m)
        if altitude_violation is not None:
            altitude_violation.data = {
                **(altitude_violation.data or {}),
                "absolute_altitude_m": absolute_altitude_m,
            }
            return altitude_violation

        distance_m = haversine_distance_m(
            self._settings.geofence_center_lat,
            self._settings.geofence_center_lon,
            latitude_deg,
            longitude_deg,
        )
        if distance_m + radius_m > self._settings.geofence_radius_m:
            return CommandResult.fail(
                "Orbit path would extend outside the configured geofence.",
                ErrorCode.GEOFENCE_VIOLATION,
                data={
                    "target_latitude_deg": latitude_deg,
                    "target_longitude_deg": longitude_deg,
                    "distance_m": round(distance_m, 2),
                    "radius_m": radius_m,
                    "geofence_radius_m": self._settings.geofence_radius_m,
                },
            )

        return None

    def _validate_geofence(
        self,
        latitude_deg: float,
        longitude_deg: float,
        waypoint_index: int | None = None,
    ) -> CommandResult | None:
        distance_m = haversine_distance_m(
            self._settings.geofence_center_lat,
            self._settings.geofence_center_lon,
            latitude_deg,
            longitude_deg,
        )
        if distance_m <= self._settings.geofence_radius_m:
            return None

        data = {
            "target_latitude_deg": latitude_deg,
            "target_longitude_deg": longitude_deg,
            "distance_m": round(distance_m, 2),
            "geofence_radius_m": self._settings.geofence_radius_m,
        }
        if waypoint_index is not None:
            data["waypoint_index"] = waypoint_index

        return CommandResult.fail(
            "Target position is outside the configured geofence.",
            ErrorCode.GEOFENCE_VIOLATION,
            data=data,
        )
