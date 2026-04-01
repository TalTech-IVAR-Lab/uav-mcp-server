import asyncio

import pytest

from tests.fakes import FakeDroneBackend
from uav_mcp_server.config import Settings
from uav_mcp_server.server import build_services, create_server
from uav_mcp_server.types import ErrorCode, TelemetrySnapshot, WaypointInput


def _server_with_fake_backend() -> tuple[object, FakeDroneBackend]:
    backend = FakeDroneBackend()
    services = build_services(settings=Settings(), backend=backend)
    return create_server(services), backend


def test_server_registers_expected_tools_and_resources() -> None:
    server, _ = _server_with_fake_backend()

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    resource_uris = {str(resource.uri) for resource in server._resource_manager.list_resources()}

    assert tool_names == {
        "connect",
        "arm",
        "disarm",
        "takeoff",
        "land",
        "hold",
        "rtl",
        "goto_relative",
        "run_mission",
        "get_status",
        "get_telemetry",
    }
    assert resource_uris == {
        "uav://status/state",
        "uav://telemetry/snapshot",
        "uav://config/safety",
    }


@pytest.mark.asyncio
async def test_connect_tool_delegates_to_controller() -> None:
    server, backend = _server_with_fake_backend()

    result = await server._tool_manager.get_tool("connect").fn()

    assert result.success is True
    assert backend.connected_to == Settings().px4_connection_string


@pytest.mark.asyncio
async def test_arm_tool_returns_preflight_failure_when_vehicle_is_not_ready() -> None:
    server, backend = _server_with_fake_backend()
    connect_tool = server._tool_manager.get_tool("connect")
    arm_tool = server._tool_manager.get_tool("arm")

    await connect_tool.fn()
    await backend.publish_battery(80.0)
    await asyncio.sleep(0)

    result = await arm_tool.fn()

    assert result.success is False
    assert result.error_code is ErrorCode.PREFLIGHT_FAILED


@pytest.mark.asyncio
async def test_get_telemetry_tool_returns_snapshot() -> None:
    server, backend = _server_with_fake_backend()
    connect_tool = server._tool_manager.get_tool("connect")
    telemetry_tool = server._tool_manager.get_tool("get_telemetry")

    await connect_tool.fn()
    await backend.publish_position()
    await asyncio.sleep(0)

    snapshot = await telemetry_tool.fn()

    assert isinstance(snapshot, TelemetrySnapshot)
    assert snapshot.connected is True
    assert snapshot.latitude_deg == 59.3948


@pytest.mark.asyncio
async def test_run_mission_tool_rejects_out_of_geofence_waypoint() -> None:
    server, backend = _server_with_fake_backend()
    connect_tool = server._tool_manager.get_tool("connect")
    mission_tool = server._tool_manager.get_tool("run_mission")

    await connect_tool.fn()
    await backend.publish_position()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_home()
    await backend.publish_flight_mode("MISSION")
    await backend.publish_armed(True)
    await backend.publish_in_air(True)
    await asyncio.sleep(0)

    result = await mission_tool.fn(
        [
            WaypointInput(latitude_deg=59.5, longitude_deg=24.9, altitude_m=20.0)
        ]
    )

    assert result.success is False
    assert result.error_code is ErrorCode.GEOFENCE_VIOLATION


def test_status_resource_reports_current_state() -> None:
    server, _ = _server_with_fake_backend()

    resource = next(
        resource
        for resource in server._resource_manager.list_resources()
        if str(resource.uri) == "uav://status/state"
    )

    assert resource.fn() == TelemetrySnapshot().state.value
