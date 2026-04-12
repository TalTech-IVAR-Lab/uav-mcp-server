"""PX4 / MAVSDK integration layer.

The controller stays testable by depending on a backend protocol instead of
directly on MAVSDK objects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol
from urllib.parse import urlparse

from uav_mcp_server.config import Settings
from uav_mcp_server.mission import MissionManager
from uav_mcp_server.navigation import offset_coordinate, relative_to_absolute_altitude_m
from uav_mcp_server.telemetry import TelemetryBackend, TelemetryManager
from uav_mcp_server.types import (
    AttitudeUpdate,
    BatteryUpdate,
    CommandResult,
    DroneState,
    ErrorCode,
    HealthUpdate,
    MissionWaypoint,
    OrbitYawBehavior,
    PositionUpdate,
    TelemetrySnapshot,
    WaypointInput,
)


class DroneBackend(TelemetryBackend, Protocol):
    async def connect(self, connection_string: str) -> None: ...

    async def arm(self) -> None: ...

    async def disarm(self) -> None: ...

    async def set_takeoff_altitude(self, altitude_m: float) -> None: ...

    async def takeoff(self) -> None: ...

    async def land(self) -> None: ...

    async def hold(self) -> None: ...

    async def return_to_launch(self) -> None: ...

    async def goto_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        yaw_deg: float = 0.0,
    ) -> None: ...

    async def orbit(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float,
        yaw_behavior: OrbitYawBehavior,
    ) -> None: ...

    async def upload_mission(self, waypoints: list[MissionWaypoint]) -> None: ...

    async def start_mission(self) -> None: ...


class MavsdkBackend:
    """Thin adapter that isolates MAVSDK-specific APIs from the rest of the code."""

    def __init__(self) -> None:
        try:
            from mavsdk import System
        except ImportError as exc:
            raise RuntimeError(
                "mavsdk is required to use the live PX4 backend."
            ) from exc

        self._system = System()

    async def connect(self, connection_string: str) -> None:
        await self._system.connect(system_address=self._normalize_connection_string(connection_string))
        async for connection_state in self._system.core.connection_state():
            if connection_state.is_connected:
                return

    async def arm(self) -> None:
        await self._system.action.arm()

    async def disarm(self) -> None:
        await self._system.action.disarm()

    async def set_takeoff_altitude(self, altitude_m: float) -> None:
        await self._system.action.set_takeoff_altitude(altitude_m)

    async def takeoff(self) -> None:
        await self._system.action.takeoff()

    async def land(self) -> None:
        await self._system.action.land()

    async def hold(self) -> None:
        await self._system.action.hold()

    async def return_to_launch(self) -> None:
        await self._system.action.return_to_launch()

    async def goto_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        yaw_deg: float = 0.0,
    ) -> None:
        await self._system.action.goto_location(
            latitude_deg,
            longitude_deg,
            absolute_altitude_m,
            yaw_deg,
        )

    async def orbit(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float,
        yaw_behavior: OrbitYawBehavior,
    ) -> None:
        from mavsdk.action import OrbitYawBehavior as MavsdkOrbitYawBehavior

        await self._system.action.do_orbit(
            radius_m=radius_m,
            velocity_ms=velocity_m_s,
            yaw_behavior=getattr(
                MavsdkOrbitYawBehavior,
                self._orbit_yaw_behavior_name(yaw_behavior),
            ),
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            absolute_altitude_m=absolute_altitude_m,
        )

    async def upload_mission(self, waypoints: list[MissionWaypoint]) -> None:
        from mavsdk.mission import MissionItem, MissionPlan

        mission_items = [
            MissionItem(
                waypoint.latitude_deg,
                waypoint.longitude_deg,
                waypoint.relative_altitude_m,
                waypoint.speed_m_s,
                waypoint.is_fly_through,
                float("nan"),
                float("nan"),
                MissionItem.CameraAction.NONE,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                MissionItem.VehicleAction.NONE,
            )
            for waypoint in waypoints
        ]
        await self._system.mission.set_return_to_launch_after_mission(True)
        await self._system.mission.upload_mission(MissionPlan(mission_items))

    async def start_mission(self) -> None:
        await self._system.mission.start_mission()

    async def position_updates(self) -> AsyncIterator[PositionUpdate]:
        async for position in self._system.telemetry.position():
            yield PositionUpdate(
                latitude_deg=position.latitude_deg,
                longitude_deg=position.longitude_deg,
                absolute_altitude_m=position.absolute_altitude_m,
                relative_altitude_m=position.relative_altitude_m,
            )

    async def battery_updates(self) -> AsyncIterator[BatteryUpdate]:
        async for battery in self._system.telemetry.battery():
            yield BatteryUpdate(
                battery_percent=self._normalize_battery_percent(battery.remaining_percent)
            )

    async def attitude_updates(self) -> AsyncIterator[AttitudeUpdate]:
        async for attitude in self._system.telemetry.attitude_euler():
            yield AttitudeUpdate(
                yaw_deg=attitude.yaw_deg,
                pitch_deg=attitude.pitch_deg,
                roll_deg=attitude.roll_deg,
            )

    async def health_updates(self) -> AsyncIterator[HealthUpdate]:
        async for health in self._system.telemetry.health():
            yield HealthUpdate(
                is_global_position_ok=health.is_global_position_ok,
                is_home_position_ok=health.is_home_position_ok,
                is_gyrometer_calibration_ok=getattr(
                    health,
                    "is_gyrometer_calibration_ok",
                    False,
                ),
                is_accelerometer_calibration_ok=getattr(
                    health,
                    "is_accelerometer_calibration_ok",
                    False,
                ),
            )

    async def flight_mode_updates(self) -> AsyncIterator[str]:
        async for flight_mode in self._system.telemetry.flight_mode():
            yield str(flight_mode)

    async def armed_updates(self) -> AsyncIterator[bool]:
        async for armed in self._system.telemetry.armed():
            yield armed

    async def in_air_updates(self) -> AsyncIterator[bool]:
        async for in_air in self._system.telemetry.in_air():
            yield in_air

    async def home_updates(self) -> AsyncIterator[float]:
        async for home in self._system.telemetry.home():
            yield home.absolute_altitude_m

    def _normalize_connection_string(self, connection_string: str) -> str:
        parsed = urlparse(connection_string)
        if parsed.scheme != "udpin":
            return connection_string

        host = parsed.hostname or ""
        port = parsed.port or 14540
        if host in {"", "0.0.0.0"}:
            return f"udp://:{port}"
        return f"udp://{host}:{port}"

    def _normalize_battery_percent(self, remaining_percent: float) -> float:
        if remaining_percent <= 1.0:
            return round(remaining_percent * 100, 2)
        return round(min(remaining_percent, 100.0), 2)

    def _orbit_yaw_behavior_name(self, yaw_behavior: OrbitYawBehavior) -> str:
        return {
            OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER: "HOLD_FRONT_TO_CIRCLE_CENTER",
            OrbitYawBehavior.HOLD_FRONT_TANGENT_TO_CIRCLE: "HOLD_FRONT_TANGENT_TO_CIRCLE",
            OrbitYawBehavior.RC_CONTROLLED: "RC_CONTROLLED",
            OrbitYawBehavior.UNCONTROLLED: "UNCONTROLLED",
            OrbitYawBehavior.HOLD_INITIAL_HEADING: "HOLD_INITIAL_HEADING",
        }[yaw_behavior]


class DroneController:
    """High-level UAV control interface."""

    _ARM_CONFIRMATION_TIMEOUT_S = 5.0
    _DISARM_CONFIRMATION_TIMEOUT_S = 5.0
    _TAKEOFF_CONFIRMATION_TIMEOUT_S = 15.0

    def __init__(
        self,
        settings: Settings,
        backend: DroneBackend,
        telemetry_manager: TelemetryManager | None = None,
        mission_manager: MissionManager | None = None,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._telemetry = telemetry_manager or TelemetryManager()
        self._mission_manager = mission_manager or MissionManager(
            settings.default_mission_speed_m_s
        )

    @property
    def telemetry_manager(self) -> TelemetryManager:
        return self._telemetry

    async def connect(self, connection_string: str | None = None) -> CommandResult:
        resolved_connection_string = connection_string or self._settings.px4_connection_string
        return await self._run_backend_action(
            lambda: self._backend.connect(resolved_connection_string),
            "Connected to PX4 backend.",
            data={"connection_string": resolved_connection_string},
            on_success=lambda: self._after_connect(),
        )

    async def arm(self) -> CommandResult:
        return await self._run_backend_action(
            self._backend.arm,
            "Vehicle armed.",
            postcondition=lambda snapshot: snapshot.armed,
            postcondition_timeout_s=self._ARM_CONFIRMATION_TIMEOUT_S,
            postcondition_failure_message="Arm command was accepted but telemetry never confirmed an armed state.",
        )

    async def disarm(self) -> CommandResult:
        return await self._run_backend_action(
            self._backend.disarm,
            "Vehicle disarmed.",
            postcondition=lambda snapshot: not snapshot.armed and not snapshot.in_air,
            postcondition_timeout_s=self._DISARM_CONFIRMATION_TIMEOUT_S,
            postcondition_failure_message=(
                "Disarm command was accepted but telemetry never confirmed a landed, disarmed state."
            ),
        )

    async def takeoff(self, altitude_m: float) -> CommandResult:
        async def command() -> None:
            await self._backend.set_takeoff_altitude(altitude_m)
            await self._backend.takeoff()

        return await self._run_backend_action(
            command,
            "Takeoff command accepted.",
            data={"target_altitude_m": altitude_m},
            postcondition=lambda snapshot: snapshot.armed and snapshot.in_air,
            postcondition_timeout_s=self._TAKEOFF_CONFIRMATION_TIMEOUT_S,
            postcondition_failure_message=(
                "Takeoff command was accepted but telemetry never confirmed an airborne state."
            ),
        )

    async def land(self) -> CommandResult:
        return await self._run_backend_action(
            self._backend.land,
            "Landing command accepted.",
            on_success=lambda: self._telemetry.update(state=DroneState.LANDING),
        )

    async def hold(self) -> CommandResult:
        return await self._run_backend_action(
            self._backend.hold,
            "Hold command accepted.",
            on_success=lambda: self._telemetry.update(flight_mode="HOLD"),
        )

    async def rtl(self) -> CommandResult:
        return await self._run_backend_action(
            self._backend.return_to_launch,
            "Return-to-launch command accepted.",
            on_success=lambda: self._telemetry.update(flight_mode="RETURN_TO_LAUNCH"),
        )

    async def goto_relative(
        self,
        north_m: float,
        east_m: float,
        altitude_m: float,
    ) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return CommandResult.fail(
                "Current position is unavailable; cannot compute a relative target.",
                ErrorCode.CONNECTION_LOST,
            )

        home_absolute_altitude_m = snapshot.inferred_home_absolute_altitude_m()
        if home_absolute_altitude_m is None:
            return CommandResult.fail(
                "Home altitude is unavailable; cannot convert relative altitude to AMSL.",
                ErrorCode.CONNECTION_LOST,
            )

        target_latitude_deg, target_longitude_deg = offset_coordinate(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            north_m,
            east_m,
        )
        target_absolute_altitude_m = relative_to_absolute_altitude_m(
            home_absolute_altitude_m,
            altitude_m,
        )

        return await self._run_backend_action(
            lambda: self._backend.goto_location(
                target_latitude_deg,
                target_longitude_deg,
                target_absolute_altitude_m,
            ),
            "Relative move command accepted.",
            data={
                "north_m": north_m,
                "east_m": east_m,
                "target_altitude_m": altitude_m,
                "target_latitude_deg": target_latitude_deg,
                "target_longitude_deg": target_longitude_deg,
            },
        )

    async def orbit(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float,
        yaw_behavior: OrbitYawBehavior = OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER,
    ) -> CommandResult:
        return await self._run_backend_action(
            lambda: self._backend.orbit(
                latitude_deg,
                longitude_deg,
                absolute_altitude_m,
                radius_m,
                velocity_m_s,
                yaw_behavior,
            ),
            "Orbit command accepted.",
            data={
                "target_latitude_deg": latitude_deg,
                "target_longitude_deg": longitude_deg,
                "absolute_altitude_m": absolute_altitude_m,
                "radius_m": radius_m,
                "velocity_m_s": velocity_m_s,
                "yaw_behavior": yaw_behavior.value,
            },
            on_success=lambda: self._telemetry.update(flight_mode="ORBIT"),
        )

    async def run_mission(self, waypoints: list[WaypointInput]) -> CommandResult:
        try:
            return await self._mission_manager.run(self._backend, waypoints)
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        except Exception as exc:
            return CommandResult.fail(
                "Mission command failed.",
                ErrorCode.BACKEND_ERROR,
                data={"details": str(exc), "waypoint_count": len(waypoints)},
            )

    async def get_status(self) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        return CommandResult.ok("Status retrieved.", data=snapshot.model_dump())

    async def get_telemetry(self) -> TelemetrySnapshot:
        return self._telemetry.get_snapshot()

    async def _after_connect(self) -> None:
        await self._telemetry.update(connected=True)
        await self._telemetry.start(self._backend)

    async def _run_backend_action(
        self,
        action: Any,
        success_message: str,
        data: dict[str, Any] | None = None,
        on_success: Any | None = None,
        postcondition: Callable[[TelemetrySnapshot], bool] | None = None,
        postcondition_timeout_s: float | None = None,
        postcondition_failure_message: str | None = None,
    ) -> CommandResult:
        try:
            await action()
            if on_success is not None:
                await on_success()
            if postcondition is not None:
                try:
                    await self._telemetry.wait_for(
                        postcondition,
                        timeout_s=postcondition_timeout_s or self._ARM_CONFIRMATION_TIMEOUT_S,
                    )
                except TimeoutError:
                    snapshot = self._telemetry.get_snapshot()
                    return CommandResult.fail(
                        postcondition_failure_message
                        or f"{success_message.rstrip('.')} was not confirmed by telemetry.",
                        ErrorCode.BACKEND_ERROR,
                        data={**(data or {}), "telemetry": snapshot.model_dump(mode="json")},
                    )
            return CommandResult.ok(success_message, data=data)
        except Exception as exc:
            return CommandResult.fail(
                f"{success_message.rstrip('.')} failed.",
                ErrorCode.BACKEND_ERROR,
                data={"details": str(exc), **(data or {})},
            )
