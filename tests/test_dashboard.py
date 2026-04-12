"""Tests for the thin operator dashboard routes and safety gating."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from tests.fakes import FakeDroneBackend
from uav_mcp_server.camera import CameraStatus
from uav_mcp_server.config import Settings
from uav_mcp_server.dashboard import DashboardState, EventLog, DashboardEvent, register_dashboard_routes
from uav_mcp_server.server import build_services, create_server
from uav_mcp_server.types import DroneState, ErrorCode, TelemetrySnapshot


def _make_server_and_backend(settings: Settings | None = None):
    backend = FakeDroneBackend()
    services = build_services(settings=settings or Settings(), backend=backend)
    server = create_server(services)
    return server, backend, services


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
    settings = Settings(camera_mount_pitch_deg=-90.0)
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
async def test_dashboard_command_takeoff_rejected_when_not_armed(dashboard_app) -> None:
    from starlette.testclient import TestClient

    app, backend, _ = dashboard_app
    client = TestClient(app, raise_server_exceptions=False)

    # Connect first, then try takeoff (should fail — not armed)
    client.post("/dashboard/api/commands/connect", json={})
    resp = client.post("/dashboard/api/commands/takeoff", json={"altitude_m": 5.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ErrorCode.WRONG_STATE.value


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

    resp = client.post("/dashboard/api/project_pixel", json={"u": 160, "v": 120})
    data = resp.json()
    assert resp.status_code == 200
    assert data["distance_m"] == pytest.approx(0.0, abs=0.2)
    assert data["absolute_altitude_m"] == pytest.approx(140.0)


@pytest.mark.asyncio
async def test_dashboard_project_pixel_rejects_missing_pose(dashboard_projection_app) -> None:
    from starlette.testclient import TestClient

    app, _, _ = dashboard_projection_app
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/dashboard/api/project_pixel", json={"u": 160, "v": 120})
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

    settings = Settings(camera_mount_pitch_deg=-90.0, geofence_radius_m=15.0)
    server, backend, services = _make_server_and_backend(settings=settings)
    client = TestClient(server.streamable_http_app(), raise_server_exceptions=False)

    await _set_airborne_snapshot(services)

    resp = client.post(
        "/dashboard/api/select_and_orbit",
        json={"u": 160, "v": 120, "radius_m": 20.0, "velocity_m_s": 3.0},
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
        json={"u": 160, "v": 120, "altitude_m": 10.0},
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
