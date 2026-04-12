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

DEFAULT_TEST_LATITUDE_DEG = 46.2331
DEFAULT_TEST_LONGITUDE_DEG = 6.0556


class _AsyncStream:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[object] = asyncio.Queue()

    async def publish(self, value: object) -> None:
        await self._queue.put(value)

    async def iterate(self) -> AsyncIterator[object]:
        while True:
            yield await self._queue.get()


@dataclass
class FakeDroneBackend:
    should_fail: bool = False
    connected_to: str | None = None
    takeoff_altitude_m: float | None = None
    goto_calls: list[tuple[float, float, float, float]] = field(default_factory=list)
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

    async def connect(self, connection_string: str) -> None:
        self._raise_if_configured()
        self.connected_to = connection_string

    async def arm(self) -> None:
        self._raise_if_configured()
        await self._armed_stream.publish(True)

    async def disarm(self) -> None:
        self._raise_if_configured()
        await self._armed_stream.publish(False)
        await self._in_air_stream.publish(False)

    async def set_takeoff_altitude(self, altitude_m: float) -> None:
        self._raise_if_configured()
        self.takeoff_altitude_m = altitude_m

    async def takeoff(self) -> None:
        self._raise_if_configured()
        await self._armed_stream.publish(True)
        await self._in_air_stream.publish(True)
        await self._flight_mode_stream.publish("TAKEOFF")

    async def land(self) -> None:
        self._raise_if_configured()
        await self._flight_mode_stream.publish("LAND")
        await self._in_air_stream.publish(False)
        await self._armed_stream.publish(False)

    async def hold(self) -> None:
        self._raise_if_configured()
        await self._flight_mode_stream.publish("HOLD")

    async def return_to_launch(self) -> None:
        self._raise_if_configured()
        await self._flight_mode_stream.publish("RETURN_TO_LAUNCH")

    async def goto_location(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        yaw_deg: float = 0.0,
    ) -> None:
        self._raise_if_configured()
        self.goto_calls.append((latitude_deg, longitude_deg, absolute_altitude_m, yaw_deg))

    async def orbit(
        self,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float,
        yaw_behavior: OrbitYawBehavior,
    ) -> None:
        self._raise_if_configured()
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

    async def upload_mission(self, waypoints: list[MissionWaypoint]) -> None:
        self._raise_if_configured()
        self.uploaded_missions.append(waypoints)

    async def start_mission(self) -> None:
        self._raise_if_configured()
        self.started_missions += 1
        await self._flight_mode_stream.publish("MISSION")

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

    async def publish_position(
        self,
        latitude_deg: float = DEFAULT_TEST_LATITUDE_DEG,
        longitude_deg: float = DEFAULT_TEST_LONGITUDE_DEG,
        absolute_altitude_m: float = 150.0,
        relative_altitude_m: float = 10.0,
    ) -> None:
        await self._position_stream.publish(
            PositionUpdate(
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                absolute_altitude_m=absolute_altitude_m,
                relative_altitude_m=relative_altitude_m,
            )
        )

    async def publish_battery(self, battery_percent: float = 75.0) -> None:
        await self._battery_stream.publish(BatteryUpdate(battery_percent=battery_percent))

    async def publish_attitude(
        self,
        yaw_deg: float = 90.0,
        pitch_deg: float = 0.0,
        roll_deg: float = 0.0,
    ) -> None:
        await self._attitude_stream.publish(
            AttitudeUpdate(yaw_deg=yaw_deg, pitch_deg=pitch_deg, roll_deg=roll_deg)
        )

    async def publish_health(
        self,
        is_global_position_ok: bool = True,
        is_home_position_ok: bool = True,
        is_gyrometer_calibration_ok: bool = True,
        is_accelerometer_calibration_ok: bool = True,
        gps_satellites: int | None = 10,
    ) -> None:
        await self._health_stream.publish(
            HealthUpdate(
                is_global_position_ok=is_global_position_ok,
                is_home_position_ok=is_home_position_ok,
                is_gyrometer_calibration_ok=is_gyrometer_calibration_ok,
                is_accelerometer_calibration_ok=is_accelerometer_calibration_ok,
                gps_satellites=gps_satellites,
            )
        )

    async def publish_home(self, home_absolute_altitude_m: float = 140.0) -> None:
        await self._home_stream.publish(home_absolute_altitude_m)

    async def publish_flight_mode(self, flight_mode: str) -> None:
        await self._flight_mode_stream.publish(flight_mode)

    async def publish_armed(self, armed: bool) -> None:
        await self._armed_stream.publish(armed)

    async def publish_in_air(self, in_air: bool) -> None:
        await self._in_air_stream.publish(in_air)

    def _raise_if_configured(self) -> None:
        if self.should_fail:
            raise RuntimeError("configured failure")
