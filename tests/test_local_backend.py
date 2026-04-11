import asyncio

import pytest

from uav_mcp_server.config import Settings
from uav_mcp_server.drone import DroneController
from uav_mcp_server.local_backend import LocalSimulationBackend
from uav_mcp_server.server import build_services
from uav_mcp_server.telemetry import TelemetryManager


def test_build_services_uses_local_backend_when_requested() -> None:
    services = build_services(settings=Settings(backend_mode="local"))

    assert isinstance(services.controller._backend, LocalSimulationBackend)


@pytest.mark.asyncio
async def test_local_backend_supports_nominal_control_path() -> None:
    backend = LocalSimulationBackend(home_latitude_deg=59.3948, home_longitude_deg=24.6614)
    controller = DroneController(Settings(backend_mode="local"), backend, TelemetryManager())

    connect_result = await controller.connect()
    await asyncio.sleep(0)
    arm_result = await controller.arm()
    takeoff_result = await controller.takeoff(12.0)
    await asyncio.sleep(0)
    telemetry = await controller.get_telemetry()

    assert connect_result.success is True
    assert arm_result.success is True
    assert takeoff_result.success is True
    assert telemetry.connected is True
    assert telemetry.armed is True
    assert telemetry.in_air is True
    assert telemetry.relative_altitude_m == 12.0

    await controller.telemetry_manager.stop()
