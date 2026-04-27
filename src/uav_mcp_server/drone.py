"""PX4 / MAVSDK integration layer.

The controller stays testable by depending on a backend protocol instead of
directly on MAVSDK objects.
"""

from __future__ import annotations

import asyncio
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

    async def gimbal_pitch_relative(self, delta_deg: float) -> None: ...

    async def gimbal_yaw_relative(self, delta_deg: float) -> None: ...

    def current_gimbal_pitch_deg(self) -> float: ...

    def current_gimbal_yaw_deg(self) -> float: ...

    async def set_roi_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
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

    _FORWARD_FACING_GIMBAL_YAW_DEG = 0.0
    _GIMBAL_PITCH_MIN_DEG = -90.0
    _GIMBAL_PITCH_MAX_DEG = 30.0
    _GIMBAL_PITCH_NEUTRAL_DEG = -30.0

    def __init__(self) -> None:
        try:
            from mavsdk import System
        except ImportError as exc:
            raise RuntimeError(
                "mavsdk is required to use the live PX4 backend."
            ) from exc

        self._system = System()
        self._last_known_gimbal_pitch_deg: float | None = self._GIMBAL_PITCH_NEUTRAL_DEG
        self._last_known_gimbal_yaw_deg: float = self._FORWARD_FACING_GIMBAL_YAW_DEG

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

    async def gimbal_pitch_relative(self, delta_deg: float) -> None:
        from mavsdk.gimbal import GimbalMode, SendMode

        device_gimbal_id = await self._first_gimbal_id()
        control_gimbal_id = await self._take_primary_gimbal_control(device_gimbal_id)
        try:
            current_pitch_deg = await self._current_gimbal_pitch_deg(device_gimbal_id)
            target_pitch_deg = self._clamp(
                current_pitch_deg + delta_deg,
                self._GIMBAL_PITCH_MIN_DEG,
                self._GIMBAL_PITCH_MAX_DEG,
            )
            await self._system.gimbal.set_angles(
                control_gimbal_id,
                0.0,
                target_pitch_deg,
                self._FORWARD_FACING_GIMBAL_YAW_DEG,
                GimbalMode.YAW_FOLLOW,
                SendMode.ONCE,
            )
            self._last_known_gimbal_pitch_deg = target_pitch_deg
            self._last_known_gimbal_yaw_deg = self._FORWARD_FACING_GIMBAL_YAW_DEG
        finally:
            await self._system.gimbal.release_control(control_gimbal_id)

    async def gimbal_yaw_relative(self, delta_deg: float) -> None:
        del delta_deg
        raise NotImplementedError(
            "Gimbal yaw control is disabled; the camera stays aligned with the drone nose."
        )

    async def set_roi_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
    ) -> None:
        control_gimbal_id = await self._take_primary_gimbal_control(await self._first_gimbal_id())
        try:
            await self._system.gimbal.set_roi_location(
                control_gimbal_id,
                latitude_deg,
                longitude_deg,
                absolute_altitude_m,
            )
        finally:
            await self._system.gimbal.release_control(control_gimbal_id)

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

    async def _first_gimbal_id(self) -> int:
        gimbal_stream = self._system.gimbal.gimbal_list()
        try:
            gimbal_list = await asyncio.wait_for(anext(gimbal_stream), timeout=3.0)
        except StopAsyncIteration as exc:
            raise NotImplementedError("No gimbal is available on the active backend.") from exc
        except TimeoutError as exc:
            raise NotImplementedError("No gimbal is available on the active backend.") from exc
        finally:
            await gimbal_stream.aclose()
        if not gimbal_list.gimbals:
            raise NotImplementedError("No gimbal is available on the active backend.")
        return gimbal_list.gimbals[0].gimbal_id

    async def _take_primary_gimbal_control(self, device_gimbal_id: int) -> int:
        from mavsdk.gimbal import ControlMode

        candidate_ids = [device_gimbal_id]
        if device_gimbal_id != 0:
            candidate_ids.append(0)

        last_exc: Exception | None = None
        for control_gimbal_id in candidate_ids:
            try:
                await self._system.gimbal.take_control(control_gimbal_id, ControlMode.PRIMARY)
                return control_gimbal_id
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise NotImplementedError("No gimbal control route is available on the active backend.")

    async def _current_gimbal_pitch_deg(self, device_gimbal_id: int) -> float:
        if self._last_known_gimbal_pitch_deg is not None:
            return self._last_known_gimbal_pitch_deg

        try:
            attitude = await self._system.gimbal.get_attitude(device_gimbal_id)
        except Exception:
            return self._last_known_gimbal_pitch_deg_or_neutral()

        pitch_deg = getattr(attitude, "pitch_deg", None)
        if pitch_deg is None:
            euler_angle_forward = getattr(attitude, "euler_angle_forward", None)
            pitch_deg = getattr(euler_angle_forward, "pitch_deg", None)
        if pitch_deg is None:
            pitch_deg = self._last_known_gimbal_pitch_deg_or_neutral()

        self._last_known_gimbal_pitch_deg = pitch_deg
        return pitch_deg

    def current_gimbal_pitch_deg(self) -> float:
        return self._last_known_gimbal_pitch_deg_or_neutral()

    def current_gimbal_yaw_deg(self) -> float:
        return self._FORWARD_FACING_GIMBAL_YAW_DEG

    def _last_known_gimbal_pitch_deg_or_neutral(self) -> float:
        if self._last_known_gimbal_pitch_deg is None:
            return self._GIMBAL_PITCH_NEUTRAL_DEG
        return self._last_known_gimbal_pitch_deg

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

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
    _DEFAULT_PREFLIGHT_WAIT_TIMEOUT_S = 30.0

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

    def current_gimbal_pitch_deg(self) -> float:
        return self._backend.current_gimbal_pitch_deg()

    def current_gimbal_yaw_deg(self) -> float:
        return self._backend.current_gimbal_yaw_deg()

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
                snapshot.yaw_deg or 0.0,
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

    async def yaw_relative(self, delta_deg: float) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return CommandResult.fail(
                "Current position is unavailable; cannot adjust heading.",
                ErrorCode.CONNECTION_LOST,
            )

        if snapshot.absolute_altitude_m is None:
            return CommandResult.fail(
                "Current altitude is unavailable; cannot adjust heading.",
                ErrorCode.CONNECTION_LOST,
            )

        target_yaw_deg = self._normalize_yaw_deg((snapshot.yaw_deg or 0.0) + delta_deg)
        return await self._run_backend_action(
            lambda: self._backend.goto_location(
                snapshot.latitude_deg,
                snapshot.longitude_deg,
                snapshot.absolute_altitude_m,
                target_yaw_deg,
            ),
            "Heading adjustment command accepted.",
            data={
                "delta_deg": delta_deg,
                "target_yaw_deg": target_yaw_deg,
                "latitude_deg": snapshot.latitude_deg,
                "longitude_deg": snapshot.longitude_deg,
                "absolute_altitude_m": snapshot.absolute_altitude_m,
            },
        )

    async def gimbal_pitch_relative(self, delta_deg: float) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if not snapshot.connected:
            return CommandResult.fail(
                "The vehicle is not connected.",
                ErrorCode.CONNECTION_LOST,
            )

        try:
            await self._backend.gimbal_pitch_relative(delta_deg)
        except NotImplementedError:
            return CommandResult.fail(
                "Gimbal pitch control is unavailable on the active backend.",
                ErrorCode.NOT_IMPLEMENTED,
            )
        except Exception as exc:
            return CommandResult.fail(
                "Gimbal pitch adjustment command failed.",
                ErrorCode.BACKEND_ERROR,
                data={"delta_deg": delta_deg, "details": str(exc)},
            )

        return CommandResult.ok(
            "Gimbal pitch adjustment command accepted.",
            data={
                "delta_deg": delta_deg,
                "gimbal_pitch_deg": self._backend.current_gimbal_pitch_deg(),
                "gimbal_yaw_deg": self._backend.current_gimbal_yaw_deg(),
            },
        )

    async def gimbal_yaw_relative(self, delta_deg: float) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if not snapshot.connected:
            return CommandResult.fail(
                "The vehicle is not connected.",
                ErrorCode.CONNECTION_LOST,
            )

        try:
            await self._backend.gimbal_yaw_relative(delta_deg)
        except NotImplementedError:
            return CommandResult.fail(
                "Gimbal yaw control is disabled; the camera stays aligned with the drone nose.",
                ErrorCode.NOT_IMPLEMENTED,
            )
        except Exception as exc:
            return CommandResult.fail(
                "Gimbal yaw adjustment command failed.",
                ErrorCode.BACKEND_ERROR,
                data={"delta_deg": delta_deg, "details": str(exc)},
            )

        return CommandResult.ok(
            "Gimbal yaw adjustment command accepted.",
            data={
                "delta_deg": delta_deg,
                "gimbal_pitch_deg": self._backend.current_gimbal_pitch_deg(),
                "gimbal_yaw_deg": self._backend.current_gimbal_yaw_deg(),
            },
        )

    async def point_gimbal_at(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
    ) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if not snapshot.connected:
            return CommandResult.fail(
                "The vehicle is not connected.",
                ErrorCode.CONNECTION_LOST,
            )

        try:
            await self._backend.set_roi_location(
                latitude_deg,
                longitude_deg,
                absolute_altitude_m,
            )
        except NotImplementedError:
            return CommandResult.fail(
                "Gimbal ROI control is unavailable on the active backend.",
                ErrorCode.NOT_IMPLEMENTED,
            )
        except Exception as exc:
            return CommandResult.fail(
                "Gimbal ROI command failed.",
                ErrorCode.BACKEND_ERROR,
                data={
                    "latitude_deg": latitude_deg,
                    "longitude_deg": longitude_deg,
                    "absolute_altitude_m": absolute_altitude_m,
                    "details": str(exc),
                },
            )

        return CommandResult.ok(
            "Gimbal ROI command accepted.",
            data={
                "latitude_deg": latitude_deg,
                "longitude_deg": longitude_deg,
                "absolute_altitude_m": absolute_altitude_m,
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

    async def guided_takeoff(
        self,
        altitude_m: float,
        connection_string: str | None = None,
    ) -> CommandResult:
        snapshot = self._telemetry.get_snapshot()
        if not snapshot.connected:
            connect_result = await self.connect(connection_string)
            if not connect_result.success:
                return connect_result

        snapshot = self._telemetry.get_snapshot()
        if not snapshot.armed:
            preflight_timeout = getattr(
                self._settings, "preflight_wait_timeout_s", self._DEFAULT_PREFLIGHT_WAIT_TIMEOUT_S
            )
            try:
                await self._telemetry.wait_for(
                    lambda telemetry: (
                        telemetry.connected
                        and telemetry.is_global_position_ok
                        and telemetry.is_home_position_ok
                        and telemetry.is_gyrometer_calibration_ok
                        and telemetry.is_accelerometer_calibration_ok
                        and telemetry.battery_percent is not None
                        and telemetry.battery_percent >= self._settings.min_battery_percent
                    ),
                    timeout_s=preflight_timeout,
                )
            except TimeoutError:
                snapshot = self._telemetry.get_snapshot()
                return CommandResult.fail(
                    "Vehicle was not ready for guided takeoff within the preflight timeout. "
                    "Check that GPS/EKF2 has converged (global_position_ok, home_position_ok) "
                    "and sensors are calibrated.",
                    ErrorCode.PREFLIGHT_FAILED,
                    data={
                        "is_global_position_ok": snapshot.is_global_position_ok,
                        "is_home_position_ok": snapshot.is_home_position_ok,
                        "is_gyrometer_calibration_ok": snapshot.is_gyrometer_calibration_ok,
                        "is_accelerometer_calibration_ok": snapshot.is_accelerometer_calibration_ok,
                        "battery_percent": snapshot.battery_percent,
                        "preflight_wait_timeout_s": preflight_timeout,
                    },
                )
            arm_result = await self.arm()
            if not arm_result.success:
                return arm_result

        return await self.takeoff(altitude_m)

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

    def _normalize_yaw_deg(self, yaw_deg: float) -> float:
        return ((yaw_deg + 180.0) % 360.0) - 180.0

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
