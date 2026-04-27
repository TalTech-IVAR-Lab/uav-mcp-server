"""Assistant planning and fallback parsing for the operator dashboard."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from uav_mcp_server.config import Settings
from uav_mcp_server.navigation import coordinate_offset_m
from uav_mcp_server.types import TelemetrySnapshot

READ_ONLY_COMMANDS = frozenset({"get_status", "get_telemetry"})
ASSISTANT_ALLOWED_COMMANDS = frozenset(
    {
        "connect",
        "arm",
        "disarm",
        "guided_takeoff",
        "hold",
        "rtl",
        "land",
        "goto_relative",
        "orbit",
        "get_status",
        "get_telemetry",
    }
)


class AssistantToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class AssistantTarget(BaseModel):
    source: str = "map"
    latitude_deg: float
    longitude_deg: float
    absolute_altitude_m: float | None = None
    north_m: float | None = None
    east_m: float | None = None
    distance_m: float | None = None
    label: str | None = None


class AssistantCameraTarget(BaseModel):
    found: bool
    label: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    u: float | None = None
    v: float | None = None
    bbox_xyxy: list[float] | None = None
    selection_anchor: str = "ground_footpoint"
    rationale: str = ""


class AssistantPlan(BaseModel):
    source: str
    operator_text: str
    assistant_text: str
    requires_confirmation: bool
    proposed_calls: list[AssistantToolCall] = Field(default_factory=list)
    fallback_reason: str | None = None


class _GeminiPlan(BaseModel):
    assistant_text: str
    calls: list[AssistantToolCall] = Field(default_factory=list)


class _GeminiVisionTarget(BaseModel):
    found: bool = False
    label: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    u: float | None = None
    v: float | None = None
    bbox_xyxy: list[float] | None = None
    selection_anchor: str | None = None
    rationale: str = ""


class AssistantGroundingContext(BaseModel):
    source: str = "local"
    command_manifest: list[dict[str, Any]] = Field(default_factory=list)
    server_instructions: str = ""
    workflow_guide: str = ""
    operator_prompt: str = ""
    safety_config: dict[str, Any] = Field(default_factory=dict)


def workflow_guide_text(settings: Settings) -> str:
    return (
        "Use guided_takeoff for normal launch requests such as 'take off to 50 meters'. "
        "guided_takeoff may connect and arm first when needed. "
        "Use arm only when the operator explicitly wants arming without takeoff. "
        "Use takeoff only for low-level armed takeoff flows; prefer guided_takeoff in normal language. "
        "Use goto_relative for bounded relative movement. "
        "Use orbit only when there is an explicit target position. "
        "Use hold, rtl, and land for recovery workflows. "
        "Never invent unsupported commands, never bypass safety, and never execute more than 4 tool calls in one turn. "
        f"Altitude must stay within {settings.min_altitude_m:.1f} m and {settings.max_altitude_m:.1f} m. "
        f"Orbit radius must stay within {settings.min_orbit_radius_m:.1f} m and {settings.max_orbit_radius_m:.1f} m."
    )


def operator_prompt_text() -> str:
    return (
        "You are the UAV operator copilot. Translate the operator request into explicit tool calls. "
        "Prefer the smallest safe action sequence. For state-changing actions, summarize what will happen plainly. "
        "If the request is ambiguous or unsupported, return no tool calls and explain the gap briefly."
    )


_CAMERA_TARGET_ACTION_RE = re.compile(
    r"\b(orbit|circle|approach|inspect|look at|go to|goto|track|follow)\b",
    re.IGNORECASE,
)
_CAMERA_TARGET_CUE_RE = re.compile(
    r"\b("
    r"camera|image|video|feed|frame|screen|reticle|middle|center|centre|left|right|top|"
    r"bottom|front|behind|near|visible|building|object|target|car|vehicle|person|tree"
    r")\b",
    re.IGNORECASE,
)


def needs_camera_target_resolution(
    operator_text: str,
    *,
    selected_target: AssistantTarget | None = None,
) -> bool:
    if selected_target is not None:
        return False
    normalized = operator_text.strip()
    if not normalized:
        return False
    return bool(_CAMERA_TARGET_ACTION_RE.search(normalized) and _CAMERA_TARGET_CUE_RE.search(normalized))


def _normalize_calls(calls: list[AssistantToolCall]) -> list[AssistantToolCall]:
    normalized: list[AssistantToolCall] = []
    for call in calls[:4]:
        if call.name not in ASSISTANT_ALLOWED_COMMANDS:
            raise ValueError(f"Command '{call.name}' is not allowed in dashboard assistant mode.")
        if not isinstance(call.arguments, dict):
            raise ValueError(f"Command '{call.name}' arguments must be an object.")
        normalized.append(
            AssistantToolCall(
                name=call.name,
                arguments=call.arguments,
                summary=call.summary or call.name.replace("_", " "),
            )
        )
    return normalized


def _requires_confirmation(calls: list[AssistantToolCall]) -> bool:
    return any(call.name not in READ_ONLY_COMMANDS for call in calls)


def _target_orbit_call(
    target: AssistantTarget,
    snapshot: TelemetrySnapshot,
    settings: Settings,
    *,
    radius_m: float | None = None,
    velocity_m_s: float | None = None,
) -> AssistantToolCall:
    absolute_altitude_m = target.absolute_altitude_m or snapshot.absolute_altitude_m
    if absolute_altitude_m is None:
        home_absolute_altitude_m = snapshot.inferred_home_absolute_altitude_m()
        if home_absolute_altitude_m is not None:
            absolute_altitude_m = home_absolute_altitude_m + settings.default_takeoff_altitude_m
    if absolute_altitude_m is None:
        raise ValueError("Current altitude is unavailable; orbit target altitude cannot be resolved.")
    resolved_radius = radius_m or max(settings.min_orbit_radius_m, 12.0)
    resolved_velocity = velocity_m_s or min(settings.default_mission_speed_m_s, 3.0)
    return AssistantToolCall(
        name="orbit",
        arguments={
            "latitude_deg": target.latitude_deg,
            "longitude_deg": target.longitude_deg,
            "absolute_altitude_m": absolute_altitude_m,
            "radius_m": resolved_radius,
            "velocity_m_s": resolved_velocity,
        },
        summary=(
            f"Orbit target at {target.latitude_deg:.6f}, {target.longitude_deg:.6f} "
            f"from the current operating altitude."
        ),
    )


def _target_approach_call(
    target: AssistantTarget,
    snapshot: TelemetrySnapshot,
    settings: Settings,
) -> AssistantToolCall:
    north_m = target.north_m
    east_m = target.east_m
    if north_m is None or east_m is None:
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            raise ValueError("Current position is unavailable; cannot compute an approach vector.")
        north_m, east_m = coordinate_offset_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            target.latitude_deg,
            target.longitude_deg,
        )
    altitude_m = snapshot.relative_altitude_m or settings.default_takeoff_altitude_m
    return AssistantToolCall(
        name="goto_relative",
        arguments={
            "north_m": north_m,
            "east_m": east_m,
            "altitude_m": altitude_m,
        },
        summary="Approach the selected target while holding the current altitude.",
    )


def fallback_plan(
    operator_text: str,
    *,
    settings: Settings,
    telemetry: TelemetrySnapshot,
    selected_target: AssistantTarget | None = None,
) -> AssistantPlan:
    normalized = operator_text.strip().lower()
    calls: list[AssistantToolCall] = []
    if not normalized:
        return AssistantPlan(
            source="fallback",
            operator_text=operator_text,
            assistant_text="No command text was provided.",
            requires_confirmation=False,
            proposed_calls=[],
        )

    if re.search(r"\b(status|state|mode)\b", normalized):
        calls = [AssistantToolCall(name="get_status", summary="Fetch the current vehicle status.")]
    elif re.search(r"\b(telemetry|position|battery)\b", normalized):
        calls = [AssistantToolCall(name="get_telemetry", summary="Fetch the latest telemetry snapshot.")]
    elif "connect" in normalized:
        calls = [AssistantToolCall(name="connect", summary="Connect to the active flight backend.")]
    elif "disarm" in normalized:
        calls = [AssistantToolCall(name="disarm", summary="Disarm the vehicle.")]
    elif re.search(r"\barm\b", normalized):
        calls = [AssistantToolCall(name="arm", summary="Arm the vehicle after preflight checks.")]
    elif re.search(r"\bland\b", normalized):
        calls = [AssistantToolCall(name="land", summary="Land the vehicle.")]
    elif re.search(r"\b(rtl|return|come back)\b", normalized):
        calls = [AssistantToolCall(name="rtl", summary="Return to launch.")]
    elif re.search(r"\b(hold|hover|stop)\b", normalized):
        calls = [AssistantToolCall(name="hold", summary="Hold the current position.")]
    else:
        takeoff_match = re.search(r"take\s*off(?:\s+to)?\s+(\d+(?:\.\d+)?)?", normalized)
        goto_match = re.search(
            r"go\s+(north|south|east|west)\s+(\d+(?:\.\d+)?)\s*(?:meter|meters|m)?",
            normalized,
        )
        orbit_match = re.search(r"\b(circle|orbit)\b", normalized)
        approach_match = re.search(r"\b(approach|inspect|go to target)\b", normalized)

        if takeoff_match:
            altitude = (
                float(takeoff_match.group(1))
                if takeoff_match.group(1)
                else settings.default_takeoff_altitude_m
            )
            calls = [
                AssistantToolCall(
                    name="guided_takeoff",
                    arguments={"altitude_m": altitude},
                    summary=f"Connect if needed, arm if needed, and take off to {altitude:.1f} m.",
                )
            ]
        elif goto_match:
            direction = goto_match.group(1)
            distance = float(goto_match.group(2))
            north_m = 0.0
            east_m = 0.0
            if direction == "north":
                north_m = distance
            elif direction == "south":
                north_m = -distance
            elif direction == "east":
                east_m = distance
            elif direction == "west":
                east_m = -distance
            altitude_m = telemetry.relative_altitude_m or settings.default_takeoff_altitude_m
            calls = [
                AssistantToolCall(
                    name="goto_relative",
                    arguments={
                        "north_m": north_m,
                        "east_m": east_m,
                        "altitude_m": altitude_m,
                    },
                    summary=f"Move {direction} by {distance:.1f} m at the current altitude.",
                )
            ]
        elif orbit_match and selected_target is not None:
            calls = [_target_orbit_call(selected_target, telemetry, settings)]
        elif approach_match and selected_target is not None:
            calls = [_target_approach_call(selected_target, telemetry, settings)]

    if calls:
        return AssistantPlan(
            source="fallback",
            operator_text=operator_text,
            assistant_text="Parsed the operator request with the local dashboard fallback planner.",
            requires_confirmation=_requires_confirmation(calls),
            proposed_calls=calls,
        )

    missing_target = (
        " Select a camera or map target first for orbit and target-approach requests."
        if re.search(r"\b(circle|orbit|approach|inspect|target)\b", normalized)
        else ""
    )
    return AssistantPlan(
        source="fallback",
        operator_text=operator_text,
        assistant_text=f"The fallback parser could not safely map that request to a supported command.{missing_target}",
        requires_confirmation=False,
        proposed_calls=[],
    )


class DashboardAssistant:
    """Gemini-first planner with a deterministic local fallback."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.assistant_enabled

    @property
    def api_available(self) -> bool:
        return bool(self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))

    async def plan(
        self,
        operator_text: str,
        *,
        telemetry: TelemetrySnapshot,
        selected_target: AssistantTarget | None,
        grounding: AssistantGroundingContext,
    ) -> AssistantPlan:
        fallback_reason: str | None = None
        if self.enabled and self.api_available:
            try:
                gemini_plan = self._plan_with_gemini(
                    operator_text,
                    telemetry=telemetry,
                    selected_target=selected_target,
                    grounding=grounding,
                )
                calls = _normalize_calls(gemini_plan.calls)
                return AssistantPlan(
                    source="gemini",
                    operator_text=operator_text,
                    assistant_text=gemini_plan.assistant_text,
                    requires_confirmation=_requires_confirmation(calls),
                    proposed_calls=calls,
                )
            except Exception as exc:
                fallback_reason = str(exc)

        fallback = fallback_plan(
            operator_text,
            settings=self._settings,
            telemetry=telemetry,
            selected_target=selected_target,
        )
        if fallback_reason is not None:
            fallback.fallback_reason = fallback_reason
        return fallback

    async def locate_camera_target(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        if not self.enabled:
            raise RuntimeError("Assistant is disabled; camera target analysis is unavailable.")
        if not self._settings.assistant_vision_enabled:
            raise RuntimeError("Assistant vision is disabled in settings.")
        if not self.api_available:
            raise RuntimeError("Gemini API key is not configured; camera target analysis is unavailable.")
        return await self._locate_camera_target_with_gemini(
            operator_text,
            image_jpeg=image_jpeg,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
        )

    async def _locate_camera_target_with_gemini(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        import asyncio

        return await asyncio.to_thread(
            self._locate_camera_target_with_gemini_sync,
            operator_text,
            image_jpeg=image_jpeg,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
        )

    def _locate_camera_target_with_gemini_sync(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))
        prompt_payload = {
            "task": "Locate the single visual target in the current drone camera frame.",
            "operator_request": operator_text,
            "image_width_px": image_width_px,
            "image_height_px": image_height_px,
            "instructions": [
                "Return only JSON.",
                "Use pixel coordinates in the original image coordinate system.",
                "If the target is a ground object or building, return the bottom-center footpoint of the visible target, not its visual centroid.",
                "If the operator refers to an object behind or near another object, choose the most likely visible target satisfying that spatial relation.",
                "If the target is not visible or ambiguous, set found=false and do not guess.",
            ],
            "required_json_shape": {
                "found": "boolean",
                "label": "short target label or null",
                "confidence": "0.0 to 1.0",
                "u": "target pixel x coordinate, null if not found",
                "v": "target pixel y coordinate, null if not found",
                "bbox_xyxy": "[left, top, right, bottom] in pixels, null if unavailable",
                "selection_anchor": "ground_footpoint, object_center, or clicked_pixel",
                "rationale": "one short sentence",
            },
        }
        image_part = _gemini_image_part(types, image_jpeg, "image/jpeg")
        response = client.models.generate_content(
            model=self._settings.assistant_model,
            contents=[json.dumps(prompt_payload, ensure_ascii=True), image_part],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a precise UAV visual target localizer. You do not command the UAV; "
                    "you only identify the requested target pixel for downstream calibrated projection."
                ),
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty camera target response.")
        raw = _GeminiVisionTarget.model_validate(_extract_json_payload(text))
        return _camera_target_from_gemini(raw, image_width_px, image_height_px)

    def _plan_with_gemini(
        self,
        operator_text: str,
        *,
        telemetry: TelemetrySnapshot,
        selected_target: AssistantTarget | None,
        grounding: AssistantGroundingContext,
    ) -> _GeminiPlan:
        from google import genai

        client = genai.Client(api_key=self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))
        tool_summary = [
            {
                "name": command["name"],
                "label": command.get("label"),
                "hint": command.get("hint"),
                "params": command.get("params", []),
                "required_params": command.get("required_params", []),
            }
            for command in grounding.command_manifest
            if command.get("name") in ASSISTANT_ALLOWED_COMMANDS
        ]
        prompt_payload = {
            "operator_request": operator_text,
            "telemetry": telemetry.model_dump(mode="json"),
            "selected_target": selected_target.model_dump(mode="json") if selected_target else None,
            "tools": tool_summary,
            "workflow_guide": grounding.workflow_guide or workflow_guide_text(self._settings),
            "operator_prompt": grounding.operator_prompt or operator_prompt_text(),
            "safety_config": grounding.safety_config,
            "required_json_shape": {
                "assistant_text": "short plain-language summary",
                "calls": [
                    {
                        "name": "tool name from the provided list",
                        "arguments": {"parameter": "value"},
                        "summary": "short explanation of the call",
                    }
                ],
            },
        }
        response = client.models.generate_content(
            model=self._settings.assistant_model,
            contents=json.dumps(prompt_payload, ensure_ascii=True),
            config=genai.types.GenerateContentConfig(
                system_instruction=grounding.server_instructions or operator_prompt_text(),
                temperature=self._settings.assistant_temperature,
                response_mime_type="application/json",
            ),
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return _GeminiPlan.model_validate(_extract_json_payload(text))


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _gemini_image_part(types_module: Any, image_bytes: bytes, mime_type: str) -> Any:
    part_type = getattr(types_module, "Part")
    if hasattr(part_type, "from_bytes"):
        return part_type.from_bytes(data=image_bytes, mime_type=mime_type)
    blob_type = getattr(types_module, "Blob")
    return part_type(inline_data=blob_type(mime_type=mime_type, data=image_bytes))


def _camera_target_from_gemini(
    raw: _GeminiVisionTarget,
    image_width_px: int,
    image_height_px: int,
) -> AssistantCameraTarget:
    if not raw.found:
        return AssistantCameraTarget(
            found=False,
            label=raw.label,
            confidence=raw.confidence,
            rationale=raw.rationale,
        )

    u = raw.u
    v = raw.v
    anchor = raw.selection_anchor or "ground_footpoint"
    if raw.bbox_xyxy is not None and len(raw.bbox_xyxy) == 4:
        left, top, right, bottom = raw.bbox_xyxy
        if u is None:
            u = (left + right) / 2.0
        if v is None:
            v = bottom if anchor == "ground_footpoint" else (top + bottom) / 2.0

    if u is None or v is None:
        return AssistantCameraTarget(
            found=False,
            label=raw.label,
            confidence=raw.confidence,
            rationale="Vision model did not return usable pixel coordinates.",
        )

    clamped_u = max(0.0, min(float(image_width_px), float(u)))
    clamped_v = max(0.0, min(float(image_height_px), float(v)))
    return AssistantCameraTarget(
        found=True,
        label=raw.label,
        confidence=raw.confidence,
        u=clamped_u,
        v=clamped_v,
        bbox_xyxy=raw.bbox_xyxy,
        selection_anchor=anchor,
        rationale=raw.rationale,
    )


def _resource_payload(resource: Any) -> Any:
    if hasattr(resource, "content") and getattr(resource, "content") is not None:
        return getattr(resource, "content")
    if hasattr(resource, "text") and getattr(resource, "text") is not None:
        return getattr(resource, "text")
    if hasattr(resource, "blob") and getattr(resource, "blob") is not None:
        return getattr(resource, "blob")
    if hasattr(resource, "model_dump"):
        dumped = resource.model_dump(mode="json")
        if "content" in dumped:
            return dumped["content"]
        if "text" in dumped:
            return dumped["text"]
        if "blob" in dumped:
            return dumped["blob"]
        return dumped
    return resource


def _resource_text(resources: Sequence[Any]) -> str:
    parts: list[str] = []
    for resource in resources:
        payload = _resource_payload(resource)
        if isinstance(payload, (dict, list)):
            parts.append(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        elif payload is not None:
            parts.append(str(payload))
    return "\n".join(part for part in parts if part).strip()


def _resource_dict(resources: Sequence[Any]) -> dict[str, Any]:
    for resource in resources:
        payload = _resource_payload(resource)
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return {}


def _prompt_text(messages: Sequence[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        text = getattr(content, "text", None)
        if text:
            parts.append(str(text).strip())
            continue
        if hasattr(content, "model_dump"):
            parts.append(json.dumps(content.model_dump(mode="json"), ensure_ascii=True, sort_keys=True))
            continue
        if content is not None:
            parts.append(str(content).strip())
    return "\n\n".join(part for part in parts if part).strip()


def build_command_manifest(tools: Sequence[Any]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if not isinstance(name, str) or name not in ASSISTANT_ALLOWED_COMMANDS:
            continue
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        manifest.append(
            {
                "name": name,
                "label": getattr(tool, "title", None) or name,
                "hint": getattr(tool, "description", None) or "",
                "params": list(properties.keys()) if isinstance(properties, dict) else [],
                "required_params": list(schema.get("required", [])) if isinstance(schema, dict) else [],
            }
        )
    return manifest


async def fetch_mcp_grounding(url: str) -> AssistantGroundingContext:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url, timeout=3.0, sse_read_timeout=5.0) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            initialize_result = await session.initialize()
            tools_result = await session.list_tools()
            await session.list_resources()
            await session.list_prompts()
            workflow_result = await session.read_resource("uav://guide/workflows")
            safety_result = await session.read_resource("uav://config/safety")
            prompt_result = await session.get_prompt("operator_workflow_brief")

    return AssistantGroundingContext(
        source="mcp_http",
        command_manifest=build_command_manifest(tools_result.tools),
        server_instructions=getattr(initialize_result, "instructions", "") or "",
        workflow_guide=_resource_text(workflow_result.contents),
        operator_prompt=_prompt_text(prompt_result.messages),
        safety_config=_resource_dict(safety_result.contents),
    )
