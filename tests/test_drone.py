import asyncio

import pytest

from tests.fakes import FakeDroneBackend
from uav_mcp_server.config import Settings
from uav_mcp_server.drone import DroneController, MavsdkBackend
from uav_mcp_server.navigation import relative_to_absolute_altitude_m
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import DroneState, ErrorCode, OrbitYawBehavior, WaypointInput


class DelayedArmTelemetryBackend(FakeDroneBackend):
    def __init__(self, arm_delay_s: float = 0.05) -> None:
        super().__init__()
        self._arm_delay_s = arm_delay_s

    async def arm(self) -> None:
        self._raise_if_configured()
        asyncio.create_task(self._publish_armed_after_delay())

    async def _publish_armed_after_delay(self) -> None:
        await asyncio.sleep(self._arm_delay_s)
        await self.publish_armed(True)


class DelayedTakeoffTelemetryBackend(FakeDroneBackend):
    def __init__(self, takeoff_delay_s: float = 0.05) -> None:
        super().__init__()
        self._takeoff_delay_s = takeoff_delay_s

    async def takeoff(self) -> None:
        self._raise_if_configured()
        asyncio.create_task(self._publish_takeoff_after_delay())

    async def _publish_takeoff_after_delay(self) -> None:
        await asyncio.sleep(self._takeoff_delay_s)
        await self.publish_armed(True)
        await self.publish_in_air(True)
        await self.publish_flight_mode("TAKEOFF")


@pytest.mark.asyncio
async def test_controller_connects_and_starts_telemetry() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.connect()

    assert result.success is True
    assert backend.connected_to == Settings().px4_connection_string

    await backend.publish_health()
    await asyncio.sleep(0)
    assert controller.telemetry_manager.get_snapshot().connected is True

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_translates_relative_move_to_goto_location() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position(absolute_altitude_m=155.0, relative_altitude_m=15.0)
    await backend.publish_home(home_absolute_altitude_m=140.0)
    await asyncio.sleep(0)

    result = await controller.goto_relative(north_m=50.0, east_m=20.0, altitude_m=30.0)

    assert result.success is True
    latitude_deg, longitude_deg, absolute_altitude_m, _ = backend.goto_calls[-1]
    assert latitude_deg != Settings().geofence_center_lat
    assert longitude_deg != Settings().geofence_center_lon
    assert absolute_altitude_m == relative_to_absolute_altitude_m(140.0, 30.0)

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_dispatches_orbit_to_backend() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.orbit(
        latitude_deg=59.3950,
        longitude_deg=24.6620,
        absolute_altitude_m=152.0,
        radius_m=12.0,
        velocity_m_s=3.0,
        yaw_behavior=OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER,
    )

    assert result.success is True
    assert backend.orbit_calls[-1] == (
        59.3950,
        24.6620,
        152.0,
        12.0,
        3.0,
        OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value,
    )


@pytest.mark.asyncio
async def test_controller_rejects_relative_move_without_position() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.goto_relative(north_m=10.0, east_m=0.0, altitude_m=20.0)

    assert result.success is False
    assert result.error_code is ErrorCode.CONNECTION_LOST


@pytest.mark.asyncio
async def test_controller_runs_mission() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(
        Settings(default_mission_speed_m_s=6.5),
        backend,
        TelemetryManager(),
    )

    result = await controller.run_mission(
        [WaypointInput(latitude_deg=59.4, longitude_deg=24.6, altitude_m=10.0)]
    )

    assert result.success is True
    assert backend.started_missions == 1
    assert len(backend.uploaded_missions[-1]) == 1
    assert backend.uploaded_missions[-1][0].speed_m_s == 6.5


@pytest.mark.asyncio
async def test_controller_translates_backend_failures() -> None:
    backend = FakeDroneBackend(should_fail=True)
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.arm()

    assert result.success is False
    assert result.error_code is ErrorCode.BACKEND_ERROR


@pytest.mark.asyncio
async def test_controller_waits_for_armed_telemetry_before_reporting_arm_success() -> None:
    backend = DelayedArmTelemetryBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(False)
    await asyncio.sleep(0)

    started = asyncio.get_running_loop().time()
    result = await controller.arm()
    elapsed_s = asyncio.get_running_loop().time() - started
    snapshot = controller.telemetry_manager.get_snapshot()

    assert result.success is True
    assert elapsed_s >= 0.04
    assert snapshot.armed is True
    assert snapshot.state is DroneState.ARMED

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_waits_for_airborne_telemetry_before_reporting_takeoff_success() -> None:
    backend = DelayedTakeoffTelemetryBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(True)
    await asyncio.sleep(0)

    started = asyncio.get_running_loop().time()
    result = await controller.takeoff(12.0)
    elapsed_s = asyncio.get_running_loop().time() - started
    snapshot = controller.telemetry_manager.get_snapshot()

    assert result.success is True
    assert elapsed_s >= 0.04
    assert backend.takeoff_altitude_m == 12.0
    assert snapshot.in_air is True
    assert snapshot.state is DroneState.AIRBORNE

    await controller.telemetry_manager.stop()


def test_mavsdk_backend_normalizes_battery_percent() -> None:
    backend = object.__new__(MavsdkBackend)

    assert backend._normalize_battery_percent(0.56) == 56.0
    assert backend._normalize_battery_percent(100.0) == 100.0


def test_mavsdk_backend_normalizes_udpin_connection_strings_for_mavsdk() -> None:
    backend = object.__new__(MavsdkBackend)

    assert backend._normalize_connection_string("udpin://0.0.0.0:14540") == "udp://:14540"
    assert backend._normalize_connection_string("udpin://:14541") == "udp://:14541"
