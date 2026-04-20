import asyncio
import json
import os

import pytest

from tests.fakes import DEFAULT_TEST_LATITUDE_DEG, DEFAULT_TEST_LONGITUDE_DEG, FakeDroneBackend
from uav_mcp_server.config import Settings
import uav_mcp_server.server as server_module
from uav_mcp_server.server import build_services, create_server
from uav_mcp_server.types import ErrorCode, TelemetrySnapshot, WaypointInput


def _server_with_fake_backend() -> tuple[object, FakeDroneBackend]:
    backend = FakeDroneBackend()
    services = build_services(settings=Settings(_env_file=None), backend=backend)
    return create_server(services), backend


def _write_benchmark_artifact(tmp_path, name: str, timestamp: str, summary: dict, records: list[dict] | None = None) -> None:
    run_dir = tmp_path / "evaluation" / "results" / f"{name}-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(
        json.dumps({"summary": summary, "records": records or []}),
        encoding="utf-8",
    )
    (run_dir / "results.csv").write_text("ok\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_server_registers_expected_tools_and_resources() -> None:
    server, _ = _server_with_fake_backend()

    tool_names = {tool.name for tool in await server.list_tools()}
    resource_uris = {str(resource.uri) for resource in await server.list_resources()}
    prompt_names = {prompt.name for prompt in await server.list_prompts()}

    assert tool_names == {
        "connect",
        "guided_takeoff",
        "arm",
        "disarm",
        "takeoff",
        "land",
        "hold",
        "rtl",
        "goto_relative",
        "yaw_relative",
        "gimbal_pitch_relative",
        "orbit",
        "run_mission",
        "get_status",
        "get_telemetry",
    }
    assert resource_uris == {
        "uav://status/state",
        "uav://telemetry/snapshot",
        "uav://config/safety",
        "uav://guide/workflows",
        "uav://runtime/health",
        "uav://evaluation/summary",
    }
    assert prompt_names == {"operator_workflow_brief"}


@pytest.mark.asyncio
async def test_server_exposes_rich_tool_metadata() -> None:
    server, _ = _server_with_fake_backend()

    tool_map = {tool.name: tool for tool in await server.list_tools()}

    guided_takeoff = tool_map["guided_takeoff"]
    get_status = tool_map["get_status"]
    get_telemetry = tool_map["get_telemetry"]

    assert guided_takeoff.title == "Guided Takeoff"
    assert guided_takeoff.description
    assert guided_takeoff.annotations is not None
    assert guided_takeoff.annotations.destructiveHint is True
    assert get_status.annotations is not None
    assert get_status.annotations.readOnlyHint is True
    assert get_status.annotations.idempotentHint is True
    assert get_telemetry.annotations is not None
    assert get_telemetry.annotations.readOnlyHint is True
    assert get_telemetry.annotations.idempotentHint is True


@pytest.mark.asyncio
async def test_server_exposes_resource_and_prompt_metadata() -> None:
    server, _ = _server_with_fake_backend()

    resources = {str(resource.uri): resource for resource in await server.list_resources()}
    prompts = {prompt.name: prompt for prompt in await server.list_prompts()}

    assert getattr(resources["uav://status/state"], "title", None)
    assert getattr(resources["uav://telemetry/snapshot"], "description", None)
    assert getattr(resources["uav://config/safety"], "description", None)
    assert getattr(resources["uav://runtime/health"], "title", None)
    assert getattr(resources["uav://evaluation/summary"], "description", None)
    assert prompts["operator_workflow_brief"].title == "Operator Workflow Brief"
    assert prompts["operator_workflow_brief"].description


@pytest.mark.asyncio
async def test_connect_tool_delegates_to_controller() -> None:
    server, backend = _server_with_fake_backend()

    _, result = await server.call_tool("connect", {})

    assert result["success"] is True
    assert backend.connected_to == Settings().px4_connection_string


@pytest.mark.asyncio
async def test_guided_takeoff_tool_connects_arms_and_takes_off() -> None:
    server, backend = _server_with_fake_backend()

    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(False)
    await asyncio.sleep(0)

    _, result = await server.call_tool("guided_takeoff", {"altitude_m": 12.0})

    assert result["success"] is True
    assert backend.connected_to == Settings().px4_connection_string
    assert backend.takeoff_altitude_m == 12.0


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
    assert snapshot.latitude_deg == DEFAULT_TEST_LATITUDE_DEG


@pytest.mark.asyncio
async def test_yaw_relative_tool_preserves_position_and_changes_heading() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position(absolute_altitude_m=155.0, relative_altitude_m=15.0)
    await backend.publish_home(home_absolute_altitude_m=140.0)
    await backend.publish_attitude(yaw_deg=90.0, pitch_deg=0.0, roll_deg=0.0)
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(True)
    await backend.publish_in_air(True)
    await asyncio.sleep(0)

    _, result = await server.call_tool("yaw_relative", {"delta_deg": 30.0})

    assert result["success"] is True
    assert backend.goto_calls[-1] == (
        DEFAULT_TEST_LATITUDE_DEG,
        DEFAULT_TEST_LONGITUDE_DEG,
        155.0,
        120.0,
    )


@pytest.mark.asyncio
async def test_gimbal_pitch_relative_tool_delegates_to_backend() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await asyncio.sleep(0)

    _, result = await server.call_tool("gimbal_pitch_relative", {"delta_deg": -10.0})

    assert result["success"] is True
    assert backend.gimbal_pitch_calls[-1] == -10.0


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
async def test_orbit_tool_dispatches_to_backend() -> None:
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position(absolute_altitude_m=150.0, relative_altitude_m=10.0)
    await backend.publish_attitude(yaw_deg=90.0, pitch_deg=-5.0, roll_deg=2.0)
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_home()
    await backend.publish_flight_mode("HOLD")
    await backend.publish_armed(True)
    await backend.publish_in_air(True)
    await asyncio.sleep(0)

    test_settings = Settings(_env_file=None)
    _, result = await server.call_tool(
        "orbit",
        {
            "latitude_deg": test_settings.geofence_center_lat + 0.0001,
            "longitude_deg": test_settings.geofence_center_lon + 0.0001,
            "absolute_altitude_m": 150.0,
            "radius_m": 12.0,
            "velocity_m_s": 3.0,
        },
    )

    assert result["success"] is True
    assert backend.orbit_calls[-1][:5] == (
        test_settings.geofence_center_lat + 0.0001,
        test_settings.geofence_center_lon + 0.0001,
        150.0,
        12.0,
        3.0,
    )


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
    assert "assistant_model" in contents[0].content
    assert "manual_control" in contents[0].content


@pytest.mark.asyncio
async def test_runtime_health_resource_reports_runtime_context(monkeypatch, tmp_path) -> None:
    run_dir = tmp_path / ".run"
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    world_path = tmp_path / "sim" / "gazebo-classic" / "worlds" / "cern_science_gateway.world"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text("<world/>", encoding="utf-8")
    (log_dir / "sitl.log").write_text(
        "\n".join(
            [
                "Runtime: classic",
                "Model: gazebo-classic",
                "Make target: gazebo-classic_iris_fpv_cam",
                f"World: {world_path}",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "sitl.pid").write_text(str(os.getpid()), encoding="utf-8")
    (run_dir / "server.pid").write_text(str(os.getpid()), encoding="utf-8")

    monkeypatch.setattr(server_module, "_server_repo_root", lambda: tmp_path)
    server, backend = _server_with_fake_backend()

    await server.call_tool("connect", {})
    await backend.publish_position()
    await backend.publish_battery(90.0)
    await backend.publish_health()
    await backend.publish_home()
    await asyncio.sleep(0)
    await server.call_tool("gimbal_pitch_relative", {"delta_deg": -5.0})

    contents = await server.read_resource("uav://runtime/health")

    assert "gazebo-classic_iris_fpv_cam" in contents[0].content
    assert "cern_science_gateway.world" in contents[0].content
    assert '"available": true' in contents[0].content
    assert '"launch": true' in contents[0].content


@pytest.mark.asyncio
async def test_evaluation_summary_resource_reports_latest_artifacts(monkeypatch, tmp_path) -> None:
    _write_benchmark_artifact(
        tmp_path,
        "latency",
        "20260417T090000Z",
        {
            "benchmark": "latency",
            "iterations": 3,
            "sample_count": 12,
            "mean_latency_ms": 18.2,
            "max_latency_ms": 24.7,
            "min_latency_ms": 9.1,
        },
        records=[{"tool": "get_status", "latency_ms": 18.2}],
    )
    _write_benchmark_artifact(
        tmp_path,
        "reliability",
        "20260417T100000Z",
        {
            "benchmark": "reliability",
            "iterations": 2,
            "successful_iterations": 2,
            "success_rate": 1.0,
            "pass_threshold": 1.0,
            "passed": True,
        },
        records=[{"iteration": 1, "success": True}],
    )
    _write_benchmark_artifact(
        tmp_path,
        "safety",
        "20260417T110000Z",
        {
            "benchmark": "safety",
            "scenario_count": 2,
            "passed_scenarios": 2,
            "passed": True,
        },
        records=[{"scenario": "takeoff_from_ready", "passed": True}],
    )

    monkeypatch.setattr(server_module, "_server_repo_root", lambda: tmp_path)
    server, _ = _server_with_fake_backend()

    contents = await server.read_resource("uav://evaluation/summary")

    assert '"ready_for_review": true' in contents[0].content
    assert "18.2 ms mean | 24.7 ms max" in contents[0].content
    assert '"benchmark": "safety"' in contents[0].content
