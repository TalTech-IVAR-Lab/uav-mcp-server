"""Tests for the thin operator dashboard routes and safety gating."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from mcp.server.fastmcp import FastMCP

from tests.fakes import FakeDroneBackend
from uav_mcp_server.camera import CameraStatus
from uav_mcp_server.config import Settings
from uav_mcp_server.dashboard import DashboardState, EventLog, DashboardEvent, register_dashboard_routes
import uav_mcp_server.server as server_module
from uav_mcp_server.server import build_services, create_server
from uav_mcp_server.types import DroneState, ErrorCode, TelemetrySnapshot


def _make_server_and_backend(settings: Settings | None = None):
    backend = FakeDroneBackend()
    services = build_services(settings=settings or Settings(_env_file=None), backend=backend)
    server = create_server(services)
    return server, backend, services


def _write_benchmark_artifact(tmp_path, name: str, timestamp: str, summary: dict, records: list[dict] | None = None) -> None:
    run_dir = tmp_path / "evaluation" / "results" / f"{name}-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(
        json.dumps({"summary": summary, "records": records or []}),
        encoding="utf-8",
    )
    (run_dir / "results.csv").write_text("ok\n", encoding="utf-8")


class DummyCameraStreamer:
    boundary = "frame"

    def is_available(self) -> bool:
        return True

    def status(self) -> CameraStatus:
        return CameraStatus(
            enabled=True,
            available=True,
            topic="/usb_cam/image_raw",
            fps=15,
        )

    async def stream_mjpeg(self):
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: 4\r\n\r\n"
            b"test\r\n"
        )


async def _set_airborne_snapshot(services) -> None:
    await services.controller.telemetry_manager.update(
        state=DroneState.AIRBORNE,
        connected=True,
        armed=True,
        in_air=True,
        latitude_deg=services.settings.geofence_center_lat,
        longitude_deg=services.settings.geofence_center_lon,
        absolute_altitude_m=150.0,
        relative_altitude_m=10.0,
        home_absolute_altitude_m=140.0,
        yaw_deg=0.0,
        pitch_deg=0.0,
        roll_deg=0.0,
        battery_percent=80.0,
        flight_mode="HOLD",
        is_global_position_ok=True,
        is_home_position_ok=True,
        is_gyrometer_calibration_ok=True,
        is_accelerometer_calibration_ok=True,
        gps_satellites=12,
    )


# -- EventLog unit tests --


@pytest.mark.asyncio
async def test_event_log_stores_and_retrieves_events() -> None:
    log = EventLog(max_events=10)
    await log.append(DashboardEvent(timestamp="t1", kind="test", summary="first"))
    await log.append(DashboardEvent(timestamp="t2", kind="test", summary="second"))

    events = await log.recent(10)
    assert len(events) == 2
    assert events[0]["summary"] == "first"
    assert events[1]["summary"] == "second"


@pytest.mark.asyncio
async def test_event_log_respects_max_events() -> None:
    log = EventLog(max_events=3)
    for i in range(5):
        await log.append(DashboardEvent(timestamp=f"t{i}", kind="test", summary=f"e{i}"))

    events = await log.recent(10)
    assert len(events) == 3
    assert events[0]["summary"] == "e2"


@pytest.mark.asyncio
async def test_event_log_subscribe_receives_new_events() -> None:
    log = EventLog()
    queue = await log.subscribe()

    await log.append(DashboardEvent(timestamp="t1", kind="cmd", summary="hello"))
    event = queue.get_nowait()
    assert event.summary == "hello"

    await log.unsubscribe(queue)


# -- Dashboard HTTP endpoint tests via Starlette TestClient --


@pytest.fixture()
def dashboard_app():
    """Create a Starlette app with the dashboard routes for testing."""
    server, backend, services = _make_server_and_backend()
    app = server.streamable_http_app()
    return app, backend, services


@pytest.fixture()
def dashboard_projection_app():
    settings = Settings(_env_file=None, camera_mount_pitch_deg=-90.0)
    server, backend, services = _make_server_and_backend(settings=settings)
    app = server.streamable_http_app()
    return app, backend, services


@pytest.mark.asyncio
async def test_dashboard_index_returns_html(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "UAV MCP Dashboard" in resp.text
    assert "assistant-input" in resp.text
    assert "chat-log" in resp.text
    assert "map-target-orbit" in resp.text
    assert "runtime-airframe" in resp.text
    assert "eval-latency" in resp.text
    assert "flag-preflight" in resp.text


@pytest.mark.asyncio
async def test_dashboard_api_status_returns_telemetry_snapshot(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert "connected" in data
    assert data["state"] == "disconnected"


@pytest.mark.asyncio
async def test_dashboard_api_telemetry_returns_snapshot(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "armed" in data
    assert "in_air" in data


@pytest.mark.asyncio
async def test_dashboard_api_config_exposes_map_and_camera_settings(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, services = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["geofence_center_lat"] == services.settings.geofence_center_lat
    assert data["camera"]["params"]["width_px"] == services.settings.camera_width_px
    assert data["manual_control"]["supports_translation"] is True
    assert data["manual_control"]["supports_yaw"] is True
    assert data["monitoring"]["runtime_health_url"] == "/dashboard/api/runtime-health"
    assert data["monitoring"]["evaluation_summary_url"] == "/dashboard/api/evaluation-summary"


@pytest.mark.asyncio
async def test_dashboard_api_runtime_health_surfaces_runtime_and_readiness(monkeypatch, tmp_path) -> None:
    from starlette.testclient import TestClient

    world_path = tmp_path / "sim" / "gazebo-classic" / "worlds" / "taltech_test.world"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text("<world/>", encoding="utf-8")

    run_dir = tmp_path / ".run"
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
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
    (log_dir / "server.log").write_text("server ready\n", encoding="utf-8")
    (run_dir / "sitl.pid").write_text(str(os.getpid()), encoding="utf-8")
    (run_dir / "server.pid").write_text(str(os.getpid()), encoding="utf-8")

    monkeypatch.setattr(server_module, "_server_repo_root", lambda: tmp_path)
    settings = Settings(_env_file=None, camera_enabled=False)
    server, backend, _services = _make_server_and_backend(settings=settings)
    client = TestClient(server.streamable_http_app(), raise_server_exceptions=False)

    await server.call_tool("connect", {})
    await backend.publish_position()
    await backend.publish_battery(92.0)
    await backend.publish_health()
    await backend.publish_home()
    await asyncio.sleep(0)
    await server.call_tool("gimbal_pitch_relative", {"delta_deg": 5.0})

    resp = client.get("/dashboard/api/runtime-health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["airframe"]["label"] == "gazebo-classic_iris_fpv_cam"
    assert data["world"]["label"] == "taltech_test.world"
    assert data["stack"]["status"] in {"healthy", "idle"}
    assert data["camera"]["enabled"] is False
    assert data["gimbal"]["available"] is True
    assert data["readiness"]["flags"]["preflight"] is True
    assert data["readiness"]["flags"]["launch"] is True


@pytest.mark.asyncio
async def test_dashboard_api_evaluation_summary_reads_latest_artifacts(monkeypatch, tmp_path) -> None:
    from starlette.testclient import TestClient

    _write_benchmark_artifact(
        tmp_path,
        "latency",
        "20260417T090000Z",
        {
            "benchmark": "latency",
            "iterations": 4,
            "sample_count": 16,
            "mean_latency_ms": 21.5,
            "max_latency_ms": 34.2,
            "min_latency_ms": 10.5,
        },
        records=[{"tool": "get_status", "latency_ms": 21.5}],
    )
    _write_benchmark_artifact(
        tmp_path,
        "reliability",
        "20260417T100000Z",
        {
            "benchmark": "reliability",
            "iterations": 3,
            "successful_iterations": 3,
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
        records=[{"scenario": "geofence_violation", "passed": True}],
    )

    monkeypatch.setattr(server_module, "_server_repo_root", lambda: tmp_path)
    settings = Settings(_env_file=None, camera_enabled=False)
    server, _, _ = _make_server_and_backend(settings=settings)
    client = TestClient(server.streamable_http_app(), raise_server_exceptions=False)

    resp = client.get("/dashboard/api/evaluation-summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["latest_run"]["benchmark"] == "safety"
    assert data["benchmarks"]["latency"]["headline"] == "21.5 ms mean | 34.2 ms max"
    assert data["benchmarks"]["reliability"]["passed"] is True
    assert data["readiness"]["ready_for_review"] is True


@pytest.mark.asyncio
async def test_dashboard_api_commands_returns_manifest_from_server_tools(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/commands")
    assert resp.status_code == 200
    data = resp.json()
    assert "commands" in data
    names = {command["name"] for command in data["commands"]}
    assert "connect" in names
    assert "guided_takeoff" in names
    assert "takeoff" not in names
    guided_takeoff = next(command for command in data["commands"] if command["name"] == "guided_takeoff")
    assert "altitude_m" in guided_takeoff["params"]


@pytest.mark.asyncio
async def test_dashboard_api_assistant_plan_auto_arms_takeoff(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/dashboard/api/assistant/plan", json={"text": "take off 50 meters"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "fallback"
    assert data["requires_confirmation"] is True
    assert [call["command"] for call in data["proposed_calls"]] == ["guided_takeoff"]


@pytest.mark.asyncio
async def test_dashboard_api_assistant_execute_runs_planned_status(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _services = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    await backend.publish_position()
    await backend.publish_battery(85.0)
    await backend.publish_health()
    await backend.publish_home()
    await asyncio.sleep(0)

    plan = client.post("/dashboard/api/assistant/plan", json={"text": "status"})
    proposed_calls = plan.json()["proposed_calls"]
    resp = client.post(
        "/dashboard/api/assistant/execute",
        json={"text": "status", "proposed_calls": proposed_calls},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["executed_calls"][0]["command"] == "get_status"


@pytest.mark.asyncio
async def test_dashboard_api_assistant_execute_runs_multiple_calls_in_order(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _services = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/dashboard/api/assistant/execute",
        json={
            "text": "connect then status",
            "proposed_calls": [
                {"command": "connect", "body": {}},
                {"command": "get_status", "body": {}},
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert [call["command"] for call in data["executed_calls"]] == ["connect", "get_status"]
    assert backend.connected_to == Settings(_env_file=None).px4_connection_string


@pytest.mark.asyncio
async def test_dashboard_api_target_crud_and_orbit(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, backend, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    set_resp = client.post(
        "/dashboard/api/target",
        json={"latitude_deg": 59.3951, "longitude_deg": 24.6680, "label": "test target"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["target"]["label"] == "test target"

    get_resp = client.get("/dashboard/api/target")
    assert get_resp.status_code == 200
    assert get_resp.json()["target"]["latitude_deg"] == pytest.approx(59.3951)

    orbit_resp = client.post(
        "/dashboard/api/target/orbit",
        json={"radius_m": 12.0, "velocity_m_s": 3.0},
    )
    assert orbit_resp.status_code == 200
    assert orbit_resp.json()["success"] is True
    assert backend.orbit_calls
    orbit_data = orbit_resp.json()["data"]
    assert orbit_data["framing"]["roi"]["attempted"] is True
    assert orbit_data["framing"]["resolved_yaw_behavior"] == "hold_initial_heading"
    assert orbit_data["framing"]["target_absolute_altitude_m"] == pytest.approx(140.0)
    assert backend.orbit_calls[-1][-1] == "hold_initial_heading"
    assert backend.roi_calls
    assert backend.roi_calls[-1][2] == pytest.approx(140.0)

    clear_resp = client.delete("/dashboard/api/target")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["target"] is None


@pytest.mark.asyncio
async def test_dashboard_target_orbit_rejects_target_directly_beneath_aircraft(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, backend, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    snapshot = services.controller.telemetry_manager.get_snapshot()
    client.post(
        "/dashboard/api/target",
        json={
            "latitude_deg": snapshot.latitude_deg,
            "longitude_deg": snapshot.longitude_deg,
            "label": "under aircraft",
        },
    )

    orbit_resp = client.post(
        "/dashboard/api/target/orbit",
        json={"radius_m": 12.0, "velocity_m_s": 3.0},
    )
    assert orbit_resp.status_code == 200
    data = orbit_resp.json()
    assert data["success"] is False
    assert data["error_code"] == ErrorCode.INVALID_PARAMS.value
    assert not backend.orbit_calls


@pytest.mark.asyncio
async def test_dashboard_manual_move_uses_manual_route(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, backend, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post(
        "/dashboard/api/manual/move",
        json={"north_m": 4.0, "east_m": -2.0, "altitude_m": 10.0},
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert backend.goto_calls


@pytest.mark.asyncio
async def test_dashboard_manual_yaw_routes_to_heading_adjustment(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, backend, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post("/dashboard/api/manual/yaw", json={"delta_deg": 15.0})
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert backend.goto_calls[-1][3] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_dashboard_manual_gimbal_pitch_routes_to_backend(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    client.post("/dashboard/api/commands/connect", json={})
    resp = client.post("/dashboard/api/manual/gimbal_pitch", json={"delta_deg": 10.0})
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert backend.gimbal_pitch_calls[-1] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_dashboard_camera_stream_returns_unavailable_when_camera_missing(dashboard_app) -> None:
    from starlette.testclient import TestClient

    server, _, _ = _make_server_and_backend(settings=Settings(camera_enabled=False))
    app = server.streamable_http_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/camera/stream")
    assert resp.status_code == 503
    assert resp.json()["error_code"] == ErrorCode.NOT_IMPLEMENTED.value


@pytest.mark.asyncio
async def test_dashboard_camera_stream_uses_mjpeg_when_camera_is_available() -> None:
    from starlette.testclient import TestClient

    mcp = FastMCP(name="camera-test")
    state = DashboardState(
        get_snapshot=lambda: TelemetrySnapshot(),
        validate_and_run=lambda *args, **kwargs: None,
        camera_streamer=DummyCameraStreamer(),
    )
    register_dashboard_routes(mcp, state)
    client = TestClient(mcp.streamable_http_app(), raise_server_exceptions=False)

    resp = client.get("/dashboard/api/camera/stream")
    assert resp.status_code == 200
    assert "multipart/x-mixed-replace" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_dashboard_api_events_returns_empty_list_initially(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/dashboard/api/events")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_dashboard_command_connect_delegates_through_safety(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/dashboard/api/commands/connect", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert backend.connected_to is not None


@pytest.mark.asyncio
async def test_dashboard_command_arm_rejected_in_wrong_state(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/dashboard/api/commands/arm", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ErrorCode.WRONG_STATE.value


@pytest.mark.asyncio
async def test_dashboard_command_guided_takeoff_connects_and_arms(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    await backend.publish_position()
    await backend.publish_battery(85.0)
    await backend.publish_health()
    await backend.publish_home()
    await asyncio.sleep(0)

    resp = client.post("/dashboard/api/commands/guided_takeoff", json={"altitude_m": 5.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert backend.connected_to is not None
    assert backend.takeoff_altitude_m == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_dashboard_command_unknown_returns_400(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/dashboard/api/commands/self_destruct", json={})
    assert resp.status_code == 400
    data = resp.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_dashboard_command_creates_event(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    client.post("/dashboard/api/commands/connect", json={})
    resp = client.get("/dashboard/api/events")
    events = resp.json()
    assert len(events) >= 1
    assert events[-1]["kind"] == "command_result"
    assert "connect" in events[-1]["summary"]


@pytest.mark.asyncio
async def test_dashboard_project_pixel_returns_world_projection(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, _, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post(
        "/dashboard/api/project_pixel",
        json={
            "u": services.settings.camera_width_px / 2,
            "v": services.settings.camera_height_px / 2,
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["distance_m"] == pytest.approx(0.0, abs=0.2)
    assert data["absolute_altitude_m"] == pytest.approx(140.0)


@pytest.mark.asyncio
async def test_dashboard_project_pixel_rejects_missing_pose(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, _, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/dashboard/api/project_pixel",
        json={
            "u": services.settings.camera_width_px / 2,
            "v": services.settings.camera_height_px / 2,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == ErrorCode.PREFLIGHT_FAILED.value


@pytest.mark.asyncio
async def test_dashboard_events_limit_parameter(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    for _ in range(5):
        client.post("/dashboard/api/commands/connect", json={})

    resp = client.get("/dashboard/api/events?limit=2")
    events = resp.json()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_dashboard_command_invalid_params_returns_error(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    # goto_relative needs north_m, east_m, altitude_m — send wrong params
    client.post("/dashboard/api/commands/connect", json={})
    resp = client.post(
        "/dashboard/api/commands/goto_relative",
        json={"wrong_param": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False


@pytest.mark.asyncio
async def test_dashboard_select_and_orbit_propagates_safety_rejection() -> None:
    from starlette.testclient import TestClient

    settings = Settings(_env_file=None, camera_mount_pitch_deg=-90.0, geofence_radius_m=15.0)
    server, backend, services = _make_server_and_backend(settings=settings)
    client = TestClient(server.streamable_http_app(), raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post(
        "/dashboard/api/select_and_orbit",
        json={
            "u": services.settings.camera_width_px,
            "v": services.settings.camera_height_px / 2,
            "radius_m": 20.0,
            "velocity_m_s": 3.0,
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is False
    assert data["error_code"] == ErrorCode.GEOFENCE_VIOLATION.value


@pytest.mark.asyncio
async def test_dashboard_select_and_approach_uses_existing_goto_path(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, backend, services = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post(
        "/dashboard/api/select_and_approach",
        json={
            "u": services.settings.camera_width_px,
            "v": services.settings.camera_height_px / 2,
            "altitude_m": 10.0,
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True
    assert backend.goto_calls


@pytest.mark.asyncio
async def test_dashboard_command_land_uses_same_safety_as_mcp(dashboard_app) -> None:
    """Land from disconnected state must be rejected — same as MCP tool."""
    from starlette.testclient import TestClient

    app, _, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/dashboard/api/commands/land", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ErrorCode.WRONG_STATE.value
