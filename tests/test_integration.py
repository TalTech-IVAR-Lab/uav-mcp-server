from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

from evaluation.mcp_http import HttpMcpClient


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_GEOFENCE_RADIUS_M = "60"


def _integration_enabled() -> bool:
    return os.environ.get("RUN_UAV_SITL_TESTS") == "1"


def _resolve_live_stack_url() -> str:
    configured_url = os.environ.get("UAV_MCP_HTTP_URL", "http://127.0.0.1:8000/mcp")
    parsed = urlparse(configured_url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.path != "/mcp":
        raise RuntimeError(f"Unsupported UAV_MCP_HTTP_URL for integration tests: {configured_url}")
    port = parsed.port or 8000
    return f"http://{parsed.hostname}:{port}/mcp"


@pytest.fixture()
def live_stack() -> str:
    if not _integration_enabled():
        pytest.skip("Set RUN_UAV_SITL_TESTS=1 to run SITL tests.")

    http_url = _resolve_live_stack_url()
    parsed = urlparse(http_url)
    launch_env = os.environ.copy()
    # Use a tighter test geofence so the live suite can exercise geofence rejection
    # without increasing the single-command movement limit used by normal operation.
    launch_env["GEOFENCE_RADIUS_M"] = TEST_GEOFENCE_RADIUS_M
    launch_env["HOST"] = parsed.hostname or "127.0.0.1"
    launch_env["PORT"] = str(parsed.port or 8000)

    subprocess.run(
        ["scripts/stop_live_stack.sh", "--force"],
        cwd=REPO_ROOT,
        check=False,
        env=os.environ.copy(),
    )
    subprocess.run(
        ["scripts/launch_live_stack.sh"],
        cwd=REPO_ROOT,
        check=True,
        env=launch_env,
    )
    try:
        yield http_url
    finally:
        subprocess.run(
            ["scripts/stop_live_stack.sh"],
            cwd=REPO_ROOT,
            check=False,
            env=os.environ.copy(),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_px4_sitl_connect_smoke(live_stack: str) -> None:
    async with HttpMcpClient(live_stack) as client:
        telemetry = await client.ensure_connected(timeout_s=60.0)

    assert telemetry["connected"] is True
    assert telemetry["state"] in {"ready", "armed", "airborne"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_px4_sitl_nominal_flight_smoke(live_stack: str) -> None:
    async with HttpMcpClient(live_stack) as client:
        final_snapshot = await client.run_nominal_flight(timeout_s=90.0)

    assert final_snapshot["state"] == "ready"
    assert final_snapshot["armed"] is False
    assert final_snapshot["in_air"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_px4_sitl_rtl_path(live_stack: str) -> None:
    async with HttpMcpClient(live_stack) as client:
        await client.reset_to_ready(timeout_s=60.0)

        arm = await client.arm_until_confirmed(timeout_s=60.0)
        assert arm["success"] is True

        takeoff = await client.call_tool("takeoff", {"altitude_m": 3.0})
        assert takeoff["success"] is True
        await client.wait_for_telemetry(lambda telemetry: telemetry["in_air"], timeout_s=60.0)

        rtl = await client.call_tool("rtl")
        assert rtl["success"] is True
        await client.wait_for_telemetry(lambda telemetry: not telemetry["in_air"], timeout_s=90.0)
        final_snapshot = await client.reset_to_ready(timeout_s=60.0)

    assert final_snapshot["state"] == "ready"
    assert final_snapshot["armed"] is False
    assert final_snapshot["in_air"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_px4_sitl_takeoff_from_ready_is_rejected(live_stack: str) -> None:
    async with HttpMcpClient(live_stack) as client:
        await client.reset_to_ready(timeout_s=60.0)
        result = await client.call_tool("takeoff", {"altitude_m": 3.0})

    assert result["success"] is False
    assert result["error_code"] == "wrong_state"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_px4_sitl_geofence_violation_is_rejected(live_stack: str) -> None:
    async with HttpMcpClient(live_stack) as client:
        await client.reset_to_ready(timeout_s=60.0)

        arm = await client.arm_until_confirmed(timeout_s=60.0)
        assert arm["success"] is True

        takeoff = await client.call_tool("takeoff", {"altitude_m": 3.0})
        assert takeoff["success"] is True
        await client.wait_for_telemetry(lambda telemetry: telemetry["in_air"], timeout_s=60.0)

        result = await client.call_tool(
            "goto_relative",
            {"north_m": 100.0, "east_m": 0.0, "altitude_m": 3.0},
        )
        cleanup_snapshot = await client.reset_to_ready(timeout_s=90.0)

    assert result["success"] is False
    assert result["error_code"] == "geofence_violation"
    assert cleanup_snapshot["state"] == "ready"
