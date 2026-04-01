import asyncio

import pytest

from tests.fakes import FakeDroneBackend
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import DroneState


@pytest.mark.asyncio
async def test_telemetry_manager_updates_snapshot_from_backend_streams() -> None:
    backend = FakeDroneBackend()
    telemetry = TelemetryManager()

    await telemetry.start(backend)
    await backend.publish_position()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_home()
    await asyncio.sleep(0)

    snapshot = telemetry.get_snapshot()
    assert snapshot.connected is True
    assert snapshot.latitude_deg == 59.3948
    assert snapshot.battery_percent == 75.0
    assert snapshot.home_absolute_altitude_m == 140.0
    assert snapshot.state is DroneState.READY

    await telemetry.stop()
