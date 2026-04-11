"""Tests for the thin operator dashboard routes and safety gating."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.fakes import FakeDroneBackend
from uav_mcp_server.config import Settings
from uav_mcp_server.dashboard import DashboardState, EventLog, DashboardEvent, register_dashboard_routes
from uav_mcp_server.server import build_services, create_server
from uav_mcp_server.types import ErrorCode


def _make_server_and_backend():
    backend = FakeDroneBackend()
    services = build_services(settings=Settings(), backend=backend)
    server = create_server(services)
    return server, backend, services


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
