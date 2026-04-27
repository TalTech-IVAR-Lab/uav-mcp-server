"""Thin operator dashboard served from the existing MCP server process.

Provides real-time telemetry via SSE, status/events APIs, and command
execution that routes through the same controller and safety layer as
MCP tool calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from uav_mcp_server.dashboard_ui import DASHBOARD_HTML
from uav_mcp_server.observability_ui import OBSERVABILITY_HTML
from uav_mcp_server.navigation import coordinate_offset_m
from uav_mcp_server.types import CommandResult, ErrorCode, OrbitYawBehavior, TelemetrySnapshot

logger = logging.getLogger(__name__)

UTC = timezone.utc
MAX_EVENTS = 200

DASHBOARD_COMMANDS = frozenset({
    "connect",
    "guided_takeoff",
    "arm",
    "disarm",
    "land",
    "hold",
    "rtl",
    "goto_relative",
    "orbit",
    "get_status",
    "get_telemetry",
})

DASHBOARD_COMMAND_ORDER = (
    "connect",
    "guided_takeoff",
    "arm",
    "disarm",
    "hold",
    "rtl",
    "land",
    "goto_relative",
    "orbit",
    "get_status",
    "get_telemetry",
)

DASHBOARD_COMMAND_METADATA: dict[str, dict[str, str]] = {
    "connect": {
        "label": "Connect",
        "hint": "Attach the operator surface to the active flight backend.",
        "tone": "neutral",
    },
    "guided_takeoff": {
        "label": "Launch",
        "hint": "Connect if needed, arm if needed, and climb to the configured altitude.",
        "tone": "neutral",
    },
    "arm": {
        "label": "Arm",
        "hint": "Run preflight gates and arm the vehicle.",
        "tone": "neutral",
    },
    "disarm": {
        "label": "Disarm",
        "hint": "Stop motors when the vehicle is on the ground.",
        "tone": "danger",
    },
    "hold": {
        "label": "Hold",
        "hint": "Pause motion and maintain the current position.",
        "tone": "safe",
    },
    "rtl": {
        "label": "RTL",
        "hint": "Return to launch using the safety-gated path.",
        "tone": "safe",
    },
    "land": {
        "label": "Land",
        "hint": "Initiate a controlled landing sequence.",
        "tone": "safe",
    },
    "goto_relative": {
        "label": "Goto",
        "hint": "Move by a bounded relative north/east offset.",
        "tone": "neutral",
    },
    "orbit": {
        "label": "Orbit",
        "hint": "Orbit the active target when one is selected.",
        "tone": "neutral",
    },
    "get_status": {
        "label": "Status",
        "hint": "Fetch the latest status snapshot from the server.",
        "tone": "ghost",
    },
    "get_telemetry": {
        "label": "Telemetry",
        "hint": "Fetch the latest telemetry snapshot from the server.",
        "tone": "ghost",
    },
}

READ_ONLY_COMMANDS = frozenset({"get_status", "get_telemetry"})


def _snapshot_text(snapshot: TelemetrySnapshot | None) -> str:
    if snapshot is None:
        return "telemetry unavailable"
    parts = [snapshot.state.value]
    if snapshot.armed:
        parts.append("armed")
    if snapshot.in_air:
        parts.append("airborne")
    if snapshot.relative_altitude_m is not None:
        parts.append(f"{snapshot.relative_altitude_m:.1f} m agl")
    return ", ".join(parts)


def _config_value(config: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(config, dict):
        return default
    value = config.get(key, default)
    return default if value is None else value


def _proposal(command: str, body: dict[str, Any] | None = None, summary: str | None = None) -> dict[str, Any]:
    return {
        "command": command,
        "body": body or {},
        "summary": summary or command,
    }


def _event_from_plan(operator_text: str, assistant_text: str, proposed_calls: list[dict[str, Any]], target: dict[str, Any] | None) -> DashboardEvent:
    return DashboardEvent(
        timestamp=_now_iso(),
        kind="assistant_plan",
        summary=operator_text.strip() or "assistant plan",
        data={
            "operator_text": operator_text,
            "assistant_text": assistant_text,
            "proposed_calls": proposed_calls,
            "target": target,
        },
    )


def _event_from_execute(operator_text: str, assistant_text: str, executed_calls: list[dict[str, Any]], target: dict[str, Any] | None) -> DashboardEvent:
    return DashboardEvent(
        timestamp=_now_iso(),
        kind="assistant_execute",
        summary=assistant_text,
        data={
            "operator_text": operator_text,
            "assistant_text": assistant_text,
            "executed_calls": executed_calls,
            "target": target,
        },
    )


def _event_from_target(target: dict[str, Any] | None, action: str) -> DashboardEvent:
    label = "target updated" if target else "target cleared"
    return DashboardEvent(
        timestamp=_now_iso(),
        kind="target_update",
        summary=label,
        data={
            "action": action,
            "target": target,
        },
    )


def _is_state_changing(command: str) -> bool:
    return command not in READ_ONLY_COMMANDS


def _assistant_plan_text(
    text: str,
    snapshot: TelemetrySnapshot | None,
    config: dict[str, Any] | None,
    selected_target: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], bool, str | None]:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return "No operator text was provided.", [], False, "empty command"

    altitude_default = float(_config_value(config, "default_takeoff_altitude_m", 5.0))
    mission_speed = float(_config_value(config, "default_mission_speed_m_s", 3.0))
    current_altitude = snapshot.relative_altitude_m if snapshot and snapshot.relative_altitude_m is not None else altitude_default

    if re.search(r"\b(status|telemetry)\b", normalized):
        command = "get_status" if "status" in normalized else "get_telemetry"
        return f"Read-only request. Fetching {command.replace('_', ' ')}.", [_proposal(command)], False, None

    if "connect" in normalized and not re.search(r"\bdisconnect\b", normalized):
        return "Connect the operator surface to the active backend.", [_proposal("connect")], True, None

    if re.search(r"\bdisarm\b", normalized):
        return "Disarm the vehicle when the current state allows it.", [_proposal("disarm")], True, None

    if re.search(r"\barm\b", normalized):
        return "Arm the vehicle through the safety-gated path.", [_proposal("arm")], True, None

    if re.search(r"\bland\b", normalized):
        return "Land the vehicle using the safety-gated landing path.", [_proposal("land")], True, None

    if re.search(r"\b(rtl|return home|return to launch|come back)\b", normalized):
        return "Return to launch using the active safety path.", [_proposal("rtl")], True, None

    if re.search(r"\b(hold|hover|stop)\b", normalized):
        return "Hold position at the current location.", [_proposal("hold")], True, None

    takeoff_match = re.search(r"take\s*off(?:\s+to)?\s+(\d+(?:\.\d+)?)", normalized)
    if takeoff_match or "take off" in normalized:
        altitude = float(takeoff_match.group(1)) if takeoff_match else altitude_default
        proposed_calls = [
            _proposal(
                "guided_takeoff",
                {"altitude_m": altitude},
                f"Connect if needed, arm if needed, and take off to {altitude:.1f} m.",
            )
        ]
        return f"Prepare the aircraft and climb to {altitude:.1f} meters.", proposed_calls, True, None

    goto_match = re.search(r"go\s+(north|south|east|west)\s+(\d+(?:\.\d+)?)\s*(?:meter|meters|m)?", normalized)
    if goto_match:
        direction = goto_match.group(1)
        distance = float(goto_match.group(2))
        payload = {"north_m": 0.0, "east_m": 0.0, "altitude_m": current_altitude}
        if direction == "north":
            payload["north_m"] = distance
        elif direction == "south":
            payload["north_m"] = -distance
        elif direction == "east":
            payload["east_m"] = distance
        elif direction == "west":
            payload["east_m"] = -distance
        return f"Move {direction} by {distance:.1f} meters.", [_proposal("goto_relative", payload)], True, None

    if re.search(r"\borbit\b", normalized):
        if selected_target is None:
            return "Orbit requested, but no map target is selected yet.", [], False, "missing target"
        payload = {
            "latitude_deg": selected_target["latitude_deg"],
            "longitude_deg": selected_target["longitude_deg"],
            "absolute_altitude_m": selected_target.get("absolute_altitude_m")
            if selected_target.get("absolute_altitude_m") is not None
            else (
                snapshot.absolute_altitude_m if snapshot and snapshot.absolute_altitude_m is not None else None
            ),
            "radius_m": float(_config_value(config, "default_orbit_radius_m", 12.0)),
            "velocity_m_s": min(mission_speed, 3.0),
        }
        return "Orbit the selected target from the current operating height.", [_proposal("orbit", payload)], True, None

    if re.search(r"\b(approach|inspect)\b", normalized):
        if selected_target is None:
            return "Approach requested, but no map target is selected yet.", [], False, "missing target"
        if snapshot is None or snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return "Approach target cannot be resolved without current position.", [], False, "missing telemetry"
        north_m, east_m = coordinate_offset_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            selected_target["latitude_deg"],
            selected_target["longitude_deg"],
        )
        payload = {
            "north_m": north_m,
            "east_m": east_m,
            "altitude_m": current_altitude,
        }
        return "Approach the selected map target.", [_proposal("goto_relative", payload)], True, None

    return "Command not recognized by the dashboard fallback parser.", [], False, "unrecognized"


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


def _tool_schema_dict(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None)
    if isinstance(schema, dict):
        return schema
    schema = getattr(tool, "input_schema", None)
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}, "required": []}


def _command_manifest_entry(name: str, tool: Any | None = None) -> dict[str, Any]:
    metadata = DASHBOARD_COMMAND_METADATA[name]
    schema = _tool_schema_dict(tool)
    properties = schema.get("properties")
    return {
        "name": name,
        "label": metadata["label"],
        "hint": metadata["hint"],
        "tone": metadata["tone"],
        "schema": schema,
        "params": list(properties.keys()) if isinstance(properties, dict) else [],
        "required_params": list(schema.get("required", [])) if isinstance(schema, dict) else [],
    }


@dataclass
class DashboardState:
    """Shared mutable state for dashboard route handlers."""

    get_snapshot: Any  # Callable[[], TelemetrySnapshot]
    validate_and_run: Any  # async (str, dict) -> CommandResult
    get_config: Any | None = None  # Callable[[], dict[str, Any]]
    get_runtime_health: Any | None = None  # Callable[[], dict[str, Any]]
    get_evaluation_summary: Any | None = None  # Callable[[], dict[str, Any]]
    observability: Any | None = None
    assistant_plan: Any | None = None  # async (dict[str, Any]) -> dict[str, Any]
    assistant_execute: Any | None = None  # async (dict[str, Any]) -> dict[str, Any]
    project_pixel: Any | None = None  # async (dict[str, Any]) -> dict[str, Any]
    select_and_orbit: Any | None = None  # async (dict[str, Any]) -> CommandResult
    select_and_approach: Any | None = None  # async (dict[str, Any]) -> CommandResult
    manual_move: Any | None = None  # async (dict[str, Any]) -> CommandResult
    manual_yaw: Any | None = None  # async (dict[str, Any]) -> CommandResult
    manual_gimbal_pitch: Any | None = None  # async (dict[str, Any]) -> CommandResult
    target_orbit: Any | None = None  # async (dict[str, Any]) -> CommandResult
    selected_target: dict[str, Any] | None = None
    camera_streamer: Any | None = None
    event_log: EventLog = field(default_factory=EventLog)


def register_dashboard_routes(mcp: Any, state: DashboardState) -> None:
    """Register all dashboard HTTP routes on the FastMCP server."""

    @mcp.custom_route("/dashboard/", methods=["GET"])
    async def dashboard_index(request: Request) -> Response:
        return HTMLResponse(DASHBOARD_HTML)

    @mcp.custom_route("/dashboard/observability/", methods=["GET"])
    async def observability_index(request: Request) -> Response:
        del request
        return HTMLResponse(OBSERVABILITY_HTML)

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

    @mcp.custom_route("/dashboard/api/runtime-health", methods=["GET"])
    async def dashboard_api_runtime_health(request: Request) -> Response:
        del request
        if state.get_runtime_health is None:
            return JSONResponse({"summary": "Runtime health is unavailable."}, status_code=200)
        return JSONResponse(state.get_runtime_health())

    @mcp.custom_route("/dashboard/api/evaluation-summary", methods=["GET"])
    async def dashboard_api_evaluation_summary(request: Request) -> Response:
        del request
        if state.get_evaluation_summary is None:
            return JSONResponse({"summary_line": "Evaluation summary is unavailable."}, status_code=200)
        return JSONResponse(state.get_evaluation_summary())

    @mcp.custom_route("/dashboard/api/observability/summary", methods=["GET"])
    async def dashboard_api_observability_summary(request: Request) -> Response:
        del request
        if state.observability is None:
            return JSONResponse({"summary": "Observability is unavailable."}, status_code=200)
        runtime_health = state.get_runtime_health() if state.get_runtime_health is not None else {}
        return JSONResponse(state.observability.summary(runtime_health=runtime_health))

    @mcp.custom_route("/dashboard/api/observability/runs", methods=["GET"])
    async def dashboard_api_observability_runs(request: Request) -> Response:
        del request
        if state.observability is None:
            return JSONResponse({"runs": [], "run_count": 0}, status_code=200)
        return JSONResponse(state.observability.list_runs())

    @mcp.custom_route("/dashboard/api/observability/runs/{run_id}", methods=["GET"])
    async def dashboard_api_observability_run_detail(request: Request) -> Response:
        if state.observability is None:
            return JSONResponse({"message": "Observability is unavailable."}, status_code=404)
        try:
            return JSONResponse(state.observability.run_detail(request.path_params["run_id"]))
        except FileNotFoundError:
            return JSONResponse({"message": "Observability run not found."}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"message": str(exc)}, status_code=400)

    @mcp.custom_route("/dashboard/api/observability/events", methods=["GET"])
    async def dashboard_api_observability_events(request: Request) -> Response:
        if state.observability is None:
            return JSONResponse({"events": []}, status_code=200)
        limit = 200
        raw_limit = request.query_params.get("limit")
        if raw_limit is not None:
            try:
                limit = max(1, min(int(raw_limit), 1000))
            except ValueError:
                pass
        return JSONResponse({"events": state.observability.recent_events(limit=limit)})

    @mcp.custom_route("/dashboard/api/observability/export", methods=["GET"])
    async def dashboard_api_observability_export(request: Request) -> Response:
        del request
        if state.observability is None:
            return JSONResponse({"message": "Observability is unavailable."}, status_code=404)
        return JSONResponse(state.observability.export())

    @mcp.custom_route("/dashboard/api/commands", methods=["GET"])
    async def dashboard_api_commands(request: Request) -> Response:
        del request
        tools_by_name: dict[str, Any] = {}
        try:
            list_tools = getattr(mcp, "list_tools", None)
            if callable(list_tools):
                for tool in await list_tools():
                    tool_name = getattr(tool, "name", None)
                    if isinstance(tool_name, str):
                        tools_by_name[tool_name] = tool
        except Exception:
            logger.exception("Failed to enumerate MCP tools for the dashboard manifest.")

        commands: list[dict[str, Any]] = []
        for name in DASHBOARD_COMMAND_ORDER:
            tool = tools_by_name.get(name)
            if tools_by_name and tool is None:
                continue
            commands.append(_command_manifest_entry(name, tool))

        return JSONResponse({"commands": commands})

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

    @mcp.custom_route("/dashboard/api/assistant/plan", methods=["POST"])
    async def dashboard_api_assistant_plan(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if state.assistant_plan is not None:
            result = await state.assistant_plan({**body, "selected_target": state.selected_target})
            event_target = result.get("selected_target") or state.selected_target
            event = _event_from_plan(
                str(result.get("operator_text") or body.get("text") or ""),
                str(result.get("assistant_text") or ""),
                list(result.get("proposed_calls") or []),
                event_target if isinstance(event_target, dict) else None,
            )
            if result.get("fallback_reason") is not None:
                event.data = {
                    **(event.data or {}),
                    "fallback_reason": result["fallback_reason"],
                }
            await state.event_log.append(event)
            return JSONResponse(result)

        operator_text = str(body.get("text", "")).strip()
        snapshot = state.get_snapshot()
        config = state.get_config() if state.get_config is not None else {}
        assistant_text, proposed_calls, requires_confirmation, fallback_reason = _assistant_plan_text(
            operator_text,
            snapshot,
            config,
            state.selected_target,
        )

        event = _event_from_plan(operator_text, assistant_text, proposed_calls, state.selected_target)
        if fallback_reason is not None:
            event.data = {
                **(event.data or {}),
                "fallback_reason": fallback_reason,
            }
        await state.event_log.append(event)

        return JSONResponse(
            {
                "source": "fallback",
                "operator_text": operator_text,
                "assistant_text": assistant_text,
                "requires_confirmation": requires_confirmation,
                "proposed_calls": proposed_calls,
                "selected_target": state.selected_target,
                "fallback_reason": fallback_reason,
            }
        )

    @mcp.custom_route("/dashboard/api/assistant/execute", methods=["POST"])
    async def dashboard_api_assistant_execute(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        if state.assistant_execute is not None:
            result = await state.assistant_execute({**body, "selected_target": state.selected_target})
            event_target = result.get("selected_target") or state.selected_target
            await state.event_log.append(
                _event_from_execute(
                    str(result.get("operator_text") or body.get("text") or ""),
                    str(result.get("assistant_text") or ""),
                    list(result.get("executed_calls") or []),
                    event_target if isinstance(event_target, dict) else None,
                )
            )
            return JSONResponse(result)

        operator_text = str(body.get("text", "")).strip()
        snapshot = state.get_snapshot()
        config = state.get_config() if state.get_config is not None else {}

        proposed_calls = body.get("proposed_calls")
        if not isinstance(proposed_calls, list) or not proposed_calls:
            assistant_text, proposed_calls, _, _ = _assistant_plan_text(
                operator_text,
                snapshot,
                config,
                state.selected_target,
            )
        else:
            assistant_text = str(body.get("assistant_text") or "Executing proposed calls.")

        executed_calls: list[dict[str, Any]] = []
        overall_success = True
        for call in proposed_calls:
            command_name = str(call.get("command") or call.get("name") or "").strip()
            body_raw = call.get("body") if isinstance(call.get("body"), dict) else call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            payload = body_raw if isinstance(body_raw, dict) else {}
            if not command_name:
                continue
            if command_name not in DASHBOARD_COMMANDS:
                result = CommandResult.fail(
                    f"Unknown command: {command_name}",
                    ErrorCode.INVALID_PARAMS,
                )
            else:
                result = await state.validate_and_run(command_name, payload)
            executed_calls.append(
                {
                    "command": command_name,
                    "body": payload,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code.value if result.error_code is not None else None,
                    "data": result.data,
                }
            )
            if not result.success:
                overall_success = False
                break

        if executed_calls:
            final_message = executed_calls[-1]["message"]
        else:
            final_message = assistant_text

        event = _event_from_execute(operator_text, final_message, executed_calls, state.selected_target)
        await state.event_log.append(event)

        return JSONResponse(
            {
                "source": "fallback",
                "operator_text": operator_text,
                "assistant_text": assistant_text,
                "executed_calls": executed_calls,
                "success": overall_success,
                "selected_target": state.selected_target,
            }
        )

    @mcp.custom_route("/dashboard/api/manual/move", methods=["POST"])
    async def dashboard_api_manual_move(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if state.manual_move is None:
            return JSONResponse(
                CommandResult.fail(
                    "Manual move control is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        result = await state.manual_move(body)
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/manual/yaw", methods=["POST"])
    async def dashboard_api_manual_yaw(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if state.manual_yaw is None:
            return JSONResponse(
                CommandResult.fail(
                    "Manual yaw control is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        result = await state.manual_yaw(body)
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/manual/gimbal_pitch", methods=["POST"])
    async def dashboard_api_manual_gimbal_pitch(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if state.manual_gimbal_pitch is None:
            return JSONResponse(
                CommandResult.fail(
                    "Manual gimbal pitch control is not configured.",
                    ErrorCode.NOT_IMPLEMENTED,
                ).model_dump(mode="json"),
                status_code=501,
            )
        result = await state.manual_gimbal_pitch(body)
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/target", methods=["GET"])
    async def dashboard_api_target_get(request: Request) -> Response:
        del request
        return JSONResponse({"target": state.selected_target})

    @mcp.custom_route("/dashboard/api/target", methods=["POST"])
    async def dashboard_api_target_post(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            latitude_deg = float(body["latitude_deg"])
            longitude_deg = float(body["longitude_deg"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                CommandResult.fail(
                    "Target requires numeric latitude_deg and longitude_deg.",
                    ErrorCode.INVALID_PARAMS,
                ).model_dump(mode="json"),
                status_code=400,
            )

        target = {
            "latitude_deg": latitude_deg,
            "longitude_deg": longitude_deg,
            "label": str(body.get("label") or "map target"),
            "source": str(body.get("source") or "map"),
        }
        if "absolute_altitude_m" in body and body["absolute_altitude_m"] is not None:
            try:
                target["absolute_altitude_m"] = float(body["absolute_altitude_m"])
            except (TypeError, ValueError):
                return JSONResponse(
                    CommandResult.fail(
                        "Target altitude must be numeric when provided.",
                        ErrorCode.INVALID_PARAMS,
                    ).model_dump(mode="json"),
                    status_code=400,
                )

        state.selected_target = target
        await state.event_log.append(_event_from_target(target, "set"))
        return JSONResponse({"target": target})

    @mcp.custom_route("/dashboard/api/target", methods=["DELETE"])
    async def dashboard_api_target_delete(request: Request) -> Response:
        del request
        state.selected_target = None
        await state.event_log.append(_event_from_target(None, "clear"))
        return JSONResponse({"target": None})

    @mcp.custom_route("/dashboard/api/target/orbit", methods=["POST"])
    async def dashboard_api_target_orbit(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}

        target = state.selected_target
        if not isinstance(target, dict):
            return JSONResponse(
                CommandResult.fail(
                    "No map target is selected.",
                    ErrorCode.INVALID_PARAMS,
                ).model_dump(mode="json"),
                status_code=400,
            )

        if state.target_orbit is not None:
            result = await state.target_orbit({**body, "selected_target": target})
            return JSONResponse(result.model_dump(mode="json"))

        snapshot = state.get_snapshot()
        config = state.get_config() if state.get_config is not None else {}
        if snapshot.absolute_altitude_m is None:
            return JSONResponse(
                CommandResult.fail(
                    "Current altitude is unavailable; orbit target altitude cannot be resolved.",
                    ErrorCode.CONNECTION_LOST,
                ).model_dump(mode="json"),
                status_code=409,
            )

        try:
            radius_m = float(body.get("radius_m", _config_value(config, "default_orbit_radius_m", 12.0)))
            velocity_m_s = float(body.get("velocity_m_s", min(float(_config_value(config, "default_mission_speed_m_s", 3.0)), 3.0)))
            yaw_behavior = OrbitYawBehavior.parse(
                body.get("yaw_behavior", OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value)
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse(
                CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS).model_dump(mode="json"),
                status_code=400,
            )

        result = await state.validate_and_run(
            "orbit",
            {
                "latitude_deg": target["latitude_deg"],
                "longitude_deg": target["longitude_deg"],
                "absolute_altitude_m": float(body.get("absolute_altitude_m", snapshot.absolute_altitude_m)),
                "radius_m": radius_m,
                "velocity_m_s": velocity_m_s,
                "yaw_behavior": yaw_behavior,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["target"] = target
        await state.event_log.append(
            DashboardEvent(
                timestamp=_now_iso(),
                kind="target_action",
                summary=f"target orbit: {'ok' if result.success else 'rejected'}",
                data={
                    "action": "orbit",
                    "target": target,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code.value if result.error_code is not None else None,
                },
            )
        )
        return JSONResponse(result.model_dump(mode="json"))

    @mcp.custom_route("/dashboard/api/target/approach", methods=["POST"])
    async def dashboard_api_target_approach(request: Request) -> Response:
        del request
        target = state.selected_target
        if not isinstance(target, dict):
            return JSONResponse(
                CommandResult.fail(
                    "No map target is selected.",
                    ErrorCode.INVALID_PARAMS,
                ).model_dump(mode="json"),
                status_code=400,
            )

        snapshot = state.get_snapshot()
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return JSONResponse(
                CommandResult.fail(
                    "Current position is unavailable; approach target cannot be resolved.",
                    ErrorCode.CONNECTION_LOST,
                ).model_dump(mode="json"),
                status_code=409,
            )

        north_m, east_m = coordinate_offset_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            target["latitude_deg"],
            target["longitude_deg"],
        )
        result = await state.validate_and_run(
            "goto_relative",
            {
                "north_m": north_m,
                "east_m": east_m,
                "altitude_m": snapshot.relative_altitude_m if snapshot.relative_altitude_m is not None else 0.0,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["target"] = target
        await state.event_log.append(
            DashboardEvent(
                timestamp=_now_iso(),
                kind="target_action",
                summary=f"target approach: {'ok' if result.success else 'rejected'}",
                data={
                    "action": "approach",
                    "target": target,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code.value if result.error_code is not None else None,
                },
            )
        )
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
