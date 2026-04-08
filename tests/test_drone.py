import asyncio

import pytest

from tests.fakes import FakeDroneBackend
from uav_mcp_server.config import Settings
from uav_mcp_server.drone import DroneController
from uav_mcp_server.navigation import relative_to_absolute_altitude_m
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import ErrorCode, WaypointInput


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
    assert latitude_deg != 59.3948
    assert longitude_deg != 24.6614
    assert absolute_altitude_m == relative_to_absolute_altitude_m(140.0, 30.0)

    await controller.telemetry_manager.stop()


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
