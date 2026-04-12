"""Thin operator dashboard served from the existing MCP server process.

Provides real-time telemetry via SSE, status/events APIs, and command
execution that routes through the same controller and safety layer as
MCP tool calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from uav_mcp_server.dashboard_ui import DASHBOARD_HTML
from uav_mcp_server.types import CommandResult, ErrorCode, TelemetrySnapshot

logger = logging.getLogger(__name__)

MAX_EVENTS = 200

DASHBOARD_COMMANDS = frozenset({
    "connect",
    "arm",
    "disarm",
    "takeoff",
    "land",
    "hold",
    "rtl",
    "goto_relative",
    "orbit",
    "get_status",
    "get_telemetry",
})


@dataclass
class DashboardEvent:
    timestamp: str
    kind: str
    summary: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "summary": self.summary,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


class EventLog:
    """Thread-safe bounded event log with SSE fan-out."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._events: deque[DashboardEvent] = deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue[DashboardEvent]] = []
        self._lock = asyncio.Lock()

    async def append(self, event: DashboardEvent) -> None:
        async with self._lock:
            self._events.append(event)
            dead: list[asyncio.Queue[DashboardEvent]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.remove(queue)

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._lock:
            tail = list(self._events)[-limit:]
        return [event.to_dict() for event in tail]

    async def subscribe(self) -> asyncio.Queue[DashboardEvent]:
        queue: asyncio.Queue[DashboardEvent] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[DashboardEvent]) -> None:
        async with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


def _snapshot_dict(snapshot: TelemetrySnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")


@dataclass
class DashboardState:
    """Shared mutable state for dashboard route handlers."""

    get_snapshot: Any  # Callable[[], TelemetrySnapshot]
    validate_and_run: Any  # async (str, dict) -> CommandResult
    get_config: Any | None = None  # Callable[[], dict[str, Any]]
    project_pixel: Any | None = None  # async (dict[str, Any]) -> dict[str, Any]
    select_and_orbit: Any | None = None  # async (dict[str, Any]) -> CommandResult
    select_and_approach: Any | None = None  # async (dict[str, Any]) -> CommandResult
    camera_streamer: Any | None = None
    event_log: EventLog = field(default_factory=EventLog)


def register_dashboard_routes(mcp: Any, state: DashboardState) -> None:
    """Register all dashboard HTTP routes on the FastMCP server."""

    @mcp.custom_route("/dashboard/", methods=["GET"])
    async def dashboard_index(request: Request) -> Response:
        return HTMLResponse(DASHBOARD_HTML)

    @mcp.custom_route("/dashboard/api/status", methods=["GET"])
    async def dashboard_api_status(request: Request) -> Response:
        snapshot = state.get_snapshot()
        return JSONResponse(_snapshot_dict(snapshot))

    @mcp.custom_route("/dashboard/api/config", methods=["GET"])
    async def dashboard_api_config(request: Request) -> Response:
        del request
        if state.get_config is None:
            return JSONResponse({}, status_code=200)
        return JSONResponse(state.get_config())

    @mcp.custom_route("/dashboard/api/telemetry", methods=["GET"])
    async def dashboard_api_telemetry(request: Request) -> Response:
        snapshot = state.get_snapshot()
        return JSONResponse(_snapshot_dict(snapshot))

    @mcp.custom_route("/dashboard/api/events", methods=["GET"])
    async def dashboard_api_events(request: Request) -> Response:
        limit = 50
        raw_limit = request.query_params.get("limit")
        if raw_limit is not None:
            try:
                limit = max(1, min(int(raw_limit), MAX_EVENTS))
            except ValueError:
                pass
        events = await state.event_log.recent(limit)
        return JSONResponse(events)

    @mcp.custom_route("/dashboard/api/commands/{name}", methods=["POST"])
    async def dashboard_api_command(request: Request) -> Response:
        command_name = request.path_params["name"]

        if command_name not in DASHBOARD_COMMANDS:
            return JSONResponse(
                CommandResult.fail(f"Unknown command: {command_name}", ErrorCode.INVALID_PARAMS).model_dump(mode="json"),
                status_code=400,
            )

        try:
            body = await request.json()
        except Exception:
            body = {}

        result = await state.validate_and_run(command_name, body)

        event = DashboardEvent(
            timestamp=_now_iso(),
            kind="command_result",
            summary=f"{command_name}: {'ok' if result.success else 'rejected'}",
            data={
                "command": command_name,
                "success": result.success,
                "message": result.message,
                "error_code": result.error_code,
            },
        )
        await state.event_log.append(event)

        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/project_pixel", methods=["POST"])
    async def dashboard_api_project_pixel(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if state.project_pixel is None:
            return JSONResponse(
                CommandResult.fail(
                    "Pixel projection is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        try:
            projected = await state.project_pixel(body)
        except ValueError as exc:
            return JSONResponse(
                CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS).model_dump(mode="json"),
                status_code=400,
            )
        except RuntimeError as exc:
            return JSONResponse(
                CommandResult.fail(str(exc), ErrorCode.PREFLIGHT_FAILED).model_dump(mode="json"),
                status_code=409,
            )

        return JSONResponse(projected)

    @mcp.custom_route("/dashboard/api/select_and_orbit", methods=["POST"])
    async def dashboard_api_select_and_orbit(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if state.select_and_orbit is None:
            return JSONResponse(
                CommandResult.fail(
                    "Target-selection orbit flow is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        result = await state.select_and_orbit(body)
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/select_and_approach", methods=["POST"])
    async def dashboard_api_select_and_approach(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if state.select_and_approach is None:
            return JSONResponse(
                CommandResult.fail(
                    "Target-selection approach flow is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        result = await state.select_and_approach(body)
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/telemetry/stream", methods=["GET"])
    async def dashboard_api_telemetry_stream(request: Request) -> Response:
        async def event_generator():
            last_json = ""
            while True:
                if await request.is_disconnected():
                    break
                snapshot = state.get_snapshot()
                current_json = json.dumps(_snapshot_dict(snapshot), sort_keys=True)
                if current_json != last_json:
                    last_json = current_json
                    yield f"event: telemetry\ndata: {current_json}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @mcp.custom_route("/dashboard/api/camera/stream", methods=["GET"])
    async def dashboard_api_camera_stream(request: Request) -> Response:
        streamer = state.camera_streamer
        if streamer is None or not streamer.is_available():
            camera_status = (
                streamer.status().to_dict()
                if streamer is not None
                else {"enabled": False, "available": False, "reason": "Camera streamer is absent."}
            )
            return JSONResponse(
                CommandResult.fail(
                    "Camera stream is unavailable.",
                    ErrorCode.NOT_IMPLEMENTED,
                    data={"camera": camera_status},
                ).model_dump(mode="json"),
                status_code=503,
            )

        async def event_generator():
            async for chunk in streamer.stream_mjpeg():
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(
            event_generator(),
            media_type=f"multipart/x-mixed-replace; boundary={streamer.boundary}",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @mcp.custom_route("/dashboard/api/events/stream", methods=["GET"])
    async def dashboard_api_events_stream(request: Request) -> Response:
        queue = await state.event_log.subscribe()

        async def event_generator():
            try:
                while True:
                    event = await queue.get()
                    payload = json.dumps(event.to_dict(), sort_keys=True)
                    yield f"event: dashboard_event\ndata: {payload}\n\n"
            except asyncio.CancelledError:
                return
            finally:
                await state.event_log.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
