from __future__ import annotations

import os

import pytest

from uav_mcp_server.config import Settings
from uav_mcp_server.drone import DroneController, MavsdkBackend


def _integration_enabled() -> bool:
    return os.environ.get("RUN_UAV_SITL_TESTS") == "1"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not _integration_enabled(), reason="Set RUN_UAV_SITL_TESTS=1 to run SITL tests.")
async def test_px4_sitl_connect_smoke() -> None:
    controller = DroneController(settings=Settings(), backend=MavsdkBackend())

    result = await controller.connect()
    telemetry = await controller.get_telemetry()

    assert result.success is True
    assert telemetry.connected is True
