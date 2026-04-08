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


@pytest.mark.asyncio
async def test_server_registers_expected_tools_and_resources() -> None:
    server, _ = _server_with_fake_backend()

    tool_names = {tool.name for tool in await server.list_tools()}
    resource_uris = {str(resource.uri) for resource in await server.list_resources()}

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

    _, result = await server.call_tool("connect", {})

    assert result["success"] is True
    assert backend.connected_to == Settings().px4_connection_string


@pytest.mark.asyncio
async def test_arm_tool_returns_preflight_failure_when_vehicle_is_not_ready() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_battery(80.0)
    await asyncio.sleep(0)

    _, result = await server.call_tool("arm", {})

    assert result["success"] is False
    assert result["error_code"] == ErrorCode.PREFLIGHT_FAILED.value


@pytest.mark.asyncio
async def test_get_telemetry_tool_returns_snapshot() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position()
    await asyncio.sleep(0)

    _, result = await server.call_tool("get_telemetry", {})
    snapshot = TelemetrySnapshot.model_validate(result)

    assert snapshot.connected is True
    assert snapshot.latitude_deg == 59.3948


@pytest.mark.asyncio
async def test_run_mission_tool_rejects_out_of_geofence_waypoint() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_home()
    await backend.publish_flight_mode("MISSION")
    await backend.publish_armed(True)
    await backend.publish_in_air(True)
    await asyncio.sleep(0)

    _, result = await server.call_tool(
        "run_mission",
        {
            "waypoints": [
                WaypointInput(latitude_deg=59.5, longitude_deg=24.9, altitude_m=20.0).model_dump()
            ]
        },
    )

    assert result["success"] is False
    assert result["error_code"] == ErrorCode.GEOFENCE_VIOLATION.value


@pytest.mark.asyncio
async def test_connect_tool_returns_backend_failure_as_structured_result() -> None:
    backend = FakeDroneBackend(should_fail=True)
    server = create_server(build_services(settings=Settings(), backend=backend))

    _, result = await server.call_tool("connect", {})

    assert result["success"] is False
    assert result["error_code"] == ErrorCode.BACKEND_ERROR.value


@pytest.mark.asyncio
async def test_status_resource_reports_current_state() -> None:
    server, _ = _server_with_fake_backend()

    contents = await server.read_resource("uav://status/state")

    assert contents[0].content == TelemetrySnapshot().state.value


@pytest.mark.asyncio
async def test_safety_resource_includes_runtime_defaults() -> None:
    server, _ = _server_with_fake_backend()

    contents = await server.read_resource("uav://config/safety")

    assert "default_takeoff_altitude_m" in contents[0].content
    assert "default_mission_speed_m_s" in contents[0].content
