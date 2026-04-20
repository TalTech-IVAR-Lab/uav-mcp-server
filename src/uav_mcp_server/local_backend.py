"""Local backend for API-level testing without PX4 SITL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from uav_mcp_server.types import (
    AttitudeUpdate,
    BatteryUpdate,
    HealthUpdate,
    MissionWaypoint,
    OrbitYawBehavior,
    PositionUpdate,
)


class _AsyncStream:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[object] = asyncio.Queue()

    async def publish(self, value: object) -> None:
        await self._queue.put(value)

    async def iterate(self) -> AsyncIterator[object]:
        while True:
            yield await self._queue.get()


@dataclass
class LocalSimulationBackend:
    """Small in-process backend that mimics nominal UAV state changes."""

    home_latitude_deg: float
    home_longitude_deg: float
    home_absolute_altitude_m: float = 140.0
    battery_percent: float = 95.0
    connected_to: str | None = None
    takeoff_altitude_m: float = 10.0
    goto_calls: list[tuple[float, float, float, float]] = field(default_factory=list)
    gimbal_pitch_calls: list[float] = field(default_factory=list)
    gimbal_yaw_calls: list[float] = field(default_factory=list)
    roi_calls: list[tuple[float, float, float]] = field(default_factory=list)
    orbit_calls: list[tuple[float, float, float, float, float, str]] = field(default_factory=list)
    uploaded_missions: list[list[MissionWaypoint]] = field(default_factory=list)
    started_missions: int = 0
    _position_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _attitude_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _battery_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _health_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _flight_mode_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _armed_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _in_air_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _home_stream: _AsyncStream = field(default_factory=_AsyncStream)
    _connected: bool = False
    _armed: bool = False
    _in_air: bool = False
    _latitude_deg: float = field(init=False)
    _longitude_deg: float = field(init=False)
    _absolute_altitude_m: float = field(init=False)
    _relative_altitude_m: float = 0.0
    _yaw_deg: float = 0.0
    _pitch_deg: float = 0.0
    _roll_deg: float = 0.0
    _gimbal_pitch_deg: float = 0.0
    _gimbal_yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        self._latitude_deg = self.home_latitude_deg
        self._longitude_deg = self.home_longitude_deg
        self._absolute_altitude_m = self.home_absolute_altitude_m

    async def connect(self, connection_string: str) -> None:
        self._connected = True
        self.connected_to = connection_string
        await self._publish_initial_state()

    async def arm(self) -> None:
        self._ensure_connected()
        self._armed = True
        await self._armed_stream.publish(True)
        await self._flight_mode_stream.publish("HOLD")

    async def disarm(self) -> None:
        self._ensure_connected()
        self._armed = False
        self._in_air = False
        self._relative_altitude_m = 0.0
        self._absolute_altitude_m = self.home_absolute_altitude_m
        await self._armed_stream.publish(False)
        await self._in_air_stream.publish(False)
        await self._position_stream.publish(self._position())

    async def set_takeoff_altitude(self, altitude_m: float) -> None:
        self._ensure_connected()
        self.takeoff_altitude_m = altitude_m

    async def takeoff(self) -> None:
        self._ensure_connected()
        self._armed = True
        self._in_air = True
        self._relative_altitude_m = self.takeoff_altitude_m
        self._absolute_altitude_m = self.home_absolute_altitude_m + self.takeoff_altitude_m
        await self._armed_stream.publish(True)
        await self._in_air_stream.publish(True)
        await self._flight_mode_stream.publish("TAKEOFF")
        await self._position_stream.publish(self._position())

    async def land(self) -> None:
        self._ensure_connected()
        self._in_air = False
        self._armed = False
        self._relative_altitude_m = 0.0
        self._absolute_altitude_m = self.home_absolute_altitude_m
        await self._flight_mode_stream.publish("LAND")
        await self._position_stream.publish(self._position())
        await self._in_air_stream.publish(False)
        await self._armed_stream.publish(False)

    async def hold(self) -> None:
        self._ensure_connected()
        await self._flight_mode_stream.publish("HOLD")

    async def return_to_launch(self) -> None:
        self._ensure_connected()
        self._latitude_deg = self.home_latitude_deg
        self._longitude_deg = self.home_longitude_deg
        await self._flight_mode_stream.publish("RETURN_TO_LAUNCH")
        await self._position_stream.publish(self._position())

    async def goto_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        yaw_deg: float = 0.0,
    ) -> None:
        self._ensure_connected()
        self.goto_calls.append((latitude_deg, longitude_deg, absolute_altitude_m, yaw_deg))
        self._armed = True
        self._in_air = True
        self._latitude_deg = latitude_deg
        self._longitude_deg = longitude_deg
        self._absolute_altitude_m = absolute_altitude_m
        self._relative_altitude_m = absolute_altitude_m - self.home_absolute_altitude_m
        self._yaw_deg = yaw_deg
        await self._armed_stream.publish(True)
        await self._in_air_stream.publish(True)
        await self._flight_mode_stream.publish("GOTO")
        await self._position_stream.publish(self._position())
        await self._attitude_stream.publish(self._attitude())

    async def gimbal_pitch_relative(self, delta_deg: float) -> None:
        self._ensure_connected()
        self.gimbal_pitch_calls.append(delta_deg)
        self._gimbal_pitch_deg = max(-90.0, min(30.0, self._gimbal_pitch_deg + delta_deg))

    def current_gimbal_pitch_deg(self) -> float:
        return self._gimbal_pitch_deg

    async def gimbal_yaw_relative(self, delta_deg: float) -> None:
        self._ensure_connected()
        self.gimbal_yaw_calls.append(delta_deg)
        self._gimbal_yaw_deg = (self._gimbal_yaw_deg + delta_deg) % 360.0

    def current_gimbal_yaw_deg(self) -> float:
        return self._gimbal_yaw_deg

    async def set_roi_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
    ) -> None:
        self._ensure_connected()
        self.roi_calls.append((latitude_deg, longitude_deg, absolute_altitude_m))

    async def orbit(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float,
        yaw_behavior: OrbitYawBehavior,
    ) -> None:
        self._ensure_connected()
        self.orbit_calls.append(
            (
                latitude_deg,
                longitude_deg,
                absolute_altitude_m,
                radius_m,
                velocity_m_s,
                yaw_behavior.value,
            )
        )
        self._armed = True
        self._in_air = True
        self._latitude_deg = latitude_deg
        self._longitude_deg = longitude_deg
        self._absolute_altitude_m = absolute_altitude_m
        self._relative_altitude_m = absolute_altitude_m - self.home_absolute_altitude_m
        await self._armed_stream.publish(True)
        await self._in_air_stream.publish(True)
        await self._flight_mode_stream.publish("ORBIT")
        await self._position_stream.publish(self._position())

    async def upload_mission(self, waypoints: list[MissionWaypoint]) -> None:
        self._ensure_connected()
        self.uploaded_missions.append(waypoints)

    async def start_mission(self) -> None:
        self._ensure_connected()
        self.started_missions += 1
        self._armed = True
        self._in_air = True
        await self._armed_stream.publish(True)
        await self._in_air_stream.publish(True)
        await self._flight_mode_stream.publish("MISSION")
        if self.uploaded_missions and self.uploaded_missions[-1]:
            first_waypoint = self.uploaded_missions[-1][0]
            self._latitude_deg = first_waypoint.latitude_deg
            self._longitude_deg = first_waypoint.longitude_deg
            self._relative_altitude_m = first_waypoint.relative_altitude_m
            self._absolute_altitude_m = (
                self.home_absolute_altitude_m + first_waypoint.relative_altitude_m
            )
            await self._position_stream.publish(self._position())

    def position_updates(self) -> AsyncIterator[PositionUpdate]:
        return self._position_stream.iterate()  # type: ignore[return-value]

    def attitude_updates(self) -> AsyncIterator[AttitudeUpdate]:
        return self._attitude_stream.iterate()  # type: ignore[return-value]

    def battery_updates(self) -> AsyncIterator[BatteryUpdate]:
        return self._battery_stream.iterate()  # type: ignore[return-value]

    def health_updates(self) -> AsyncIterator[HealthUpdate]:
        return self._health_stream.iterate()  # type: ignore[return-value]

    def flight_mode_updates(self) -> AsyncIterator[str]:
        return self._flight_mode_stream.iterate()  # type: ignore[return-value]

    def armed_updates(self) -> AsyncIterator[bool]:
        return self._armed_stream.iterate()  # type: ignore[return-value]

    def in_air_updates(self) -> AsyncIterator[bool]:
        return self._in_air_stream.iterate()  # type: ignore[return-value]

    def home_updates(self) -> AsyncIterator[float]:
        return self._home_stream.iterate()  # type: ignore[return-value]

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Local backend is not connected.")

    def _position(self) -> PositionUpdate:
        return PositionUpdate(
            latitude_deg=self._latitude_deg,
            longitude_deg=self._longitude_deg,
            absolute_altitude_m=self._absolute_altitude_m,
            relative_altitude_m=self._relative_altitude_m,
        )

    def _attitude(self) -> AttitudeUpdate:
        return AttitudeUpdate(
            yaw_deg=self._yaw_deg,
            pitch_deg=self._pitch_deg,
            roll_deg=self._roll_deg,
        )

    async def _publish_initial_state(self) -> None:
        await self._home_stream.publish(self.home_absolute_altitude_m)
        await self._position_stream.publish(self._position())
        await self._attitude_stream.publish(self._attitude())
        await self._battery_stream.publish(BatteryUpdate(battery_percent=self.battery_percent))
        await self._health_stream.publish(
            HealthUpdate(
                is_global_position_ok=True,
                is_home_position_ok=True,
                is_gyrometer_calibration_ok=True,
                is_accelerometer_calibration_ok=True,
                gps_satellites=12,
            )
        )
        await self._flight_mode_stream.publish("HOLD")
        await self._armed_stream.publish(self._armed)
        await self._in_air_stream.publish(self._in_air)
        await self._attitude_stream.publish(self._attitude())
