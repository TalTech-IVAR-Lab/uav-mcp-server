"""Telemetry subscription and caching layer."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from uav_mcp_server.types import (
    AttitudeUpdate,
    BatteryUpdate,
    DroneState,
    HealthUpdate,
    PositionUpdate,
    TelemetrySnapshot,
)

logger = logging.getLogger(__name__)


class TelemetryBackend(Protocol):
    def position_updates(self) -> AsyncIterator[PositionUpdate]: ...

    def attitude_updates(self) -> AsyncIterator[AttitudeUpdate]: ...

    def battery_updates(self) -> AsyncIterator[BatteryUpdate]: ...

    def health_updates(self) -> AsyncIterator[HealthUpdate]: ...

    def flight_mode_updates(self) -> AsyncIterator[str]: ...

    def armed_updates(self) -> AsyncIterator[bool]: ...

    def in_air_updates(self) -> AsyncIterator[bool]: ...

    def home_updates(self) -> AsyncIterator[float]: ...


class TelemetryManager:
    """Caches the latest telemetry values from the UAV backend."""

    def __init__(self) -> None:
        self._snapshot = TelemetrySnapshot()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Condition(self._lock)
        self._tasks: list[asyncio.Task[None]] = []

    def get_snapshot(self) -> TelemetrySnapshot:
        return self._snapshot.model_copy(deep=True)

    async def start(self, backend: TelemetryBackend) -> None:
        await self.stop()
        self._tasks = [
            asyncio.create_task(self._consume_positions(backend.position_updates())),
            asyncio.create_task(self._consume_attitude(backend.attitude_updates())),
            asyncio.create_task(self._consume_battery(backend.battery_updates())),
            asyncio.create_task(self._consume_health(backend.health_updates())),
            asyncio.create_task(self._consume_text(backend.flight_mode_updates(), "flight_mode")),
            asyncio.create_task(self._consume_bool(backend.armed_updates(), "armed")),
            asyncio.create_task(self._consume_bool(backend.in_air_updates(), "in_air")),
            asyncio.create_task(self._consume_home(backend.home_updates())),
        ]

    async def stop(self) -> None:
        if not self._tasks:
            return

        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)

    async def update(self, **changes: object) -> None:
        async with self._changed:
            state_override = changes.pop("state", None)
            snapshot = self._snapshot.model_copy(update=changes)
            if state_override is not None:
                snapshot.state = state_override
            else:
                snapshot.state = self._derive_state(snapshot)
            self._snapshot = snapshot
            self._changed.notify_all()

    async def wait_for(
        self,
        predicate,
        timeout_s: float,
    ) -> TelemetrySnapshot:
        async def _await_match() -> TelemetrySnapshot:
            async with self._changed:
                if predicate(self._snapshot):
                    return self._snapshot.model_copy(deep=True)

                await self._changed.wait_for(lambda: predicate(self._snapshot))
                return self._snapshot.model_copy(deep=True)

        return await asyncio.wait_for(_await_match(), timeout=timeout_s)

    async def set_fault(self) -> None:
        await self.update(state=DroneState.FAULT)

    def _derive_state(self, snapshot: TelemetrySnapshot) -> DroneState:
        if not snapshot.connected:
            return DroneState.DISCONNECTED
        if snapshot.in_air:
            if snapshot.flight_mode is not None and "land" in snapshot.flight_mode.lower():
                return DroneState.LANDING
            return DroneState.AIRBORNE
        if snapshot.armed:
            return DroneState.ARMED
        if snapshot.is_global_position_ok and snapshot.is_home_position_ok:
            return DroneState.READY
        return DroneState.CONNECTED

    async def _consume_positions(self, stream: AsyncIterator[PositionUpdate]) -> None:
        try:
            async for update in stream:
                await self.update(
                    connected=True,
                    latitude_deg=update.latitude_deg,
                    longitude_deg=update.longitude_deg,
                    absolute_altitude_m=update.absolute_altitude_m,
                    relative_altitude_m=update.relative_altitude_m,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Position telemetry stream failed: %s", exc)
            await self.set_fault()

    async def _consume_battery(self, stream: AsyncIterator[BatteryUpdate]) -> None:
        try:
            async for update in stream:
                await self.update(connected=True, battery_percent=update.battery_percent)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Battery telemetry stream failed: %s", exc)
            await self.set_fault()

    async def _consume_attitude(self, stream: AsyncIterator[AttitudeUpdate]) -> None:
        try:
            async for update in stream:
                await self.update(
                    connected=True,
                    yaw_deg=update.yaw_deg,
                    pitch_deg=update.pitch_deg,
                    roll_deg=update.roll_deg,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Attitude telemetry stream failed: %s", exc)
            await self.set_fault()

    async def _consume_health(self, stream: AsyncIterator[HealthUpdate]) -> None:
        try:
            async for update in stream:
                await self.update(
                    connected=True,
                    is_global_position_ok=update.is_global_position_ok,
                    is_home_position_ok=update.is_home_position_ok,
                    is_gyrometer_calibration_ok=update.is_gyrometer_calibration_ok,
                    is_accelerometer_calibration_ok=update.is_accelerometer_calibration_ok,
                    gps_satellites=update.gps_satellites,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Health telemetry stream failed: %s", exc)
            await self.set_fault()

    async def _consume_text(self, stream: AsyncIterator[str], field_name: str) -> None:
        try:
            async for value in stream:
                await self.update(connected=True, **{field_name: value})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("%s telemetry stream failed: %s", field_name, exc)
            await self.set_fault()

    async def _consume_bool(self, stream: AsyncIterator[bool], field_name: str) -> None:
        try:
            async for value in stream:
                await self.update(connected=True, **{field_name: value})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("%s telemetry stream failed: %s", field_name, exc)
            await self.set_fault()

    async def _consume_home(self, stream: AsyncIterator[float]) -> None:
        try:
            async for home_absolute_altitude_m in stream:
                await self.update(
                    connected=True,
                    home_absolute_altitude_m=home_absolute_altitude_m,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Home telemetry stream failed: %s", exc)
            await self.set_fault()
